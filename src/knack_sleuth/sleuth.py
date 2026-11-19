"""Core search functionality for finding object and field usages in Knack metadata."""

import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from functools import cached_property
from typing import Any, Literal, NamedTuple

from knack_sleuth.app_summary_report import (
    AccessPatterns,
    ApplicationSummary,
    AppSummary,
    ConnectionEdge,
    CouplingPair,
    DataPatterns,
    DependencyCluster,
    DomainModel,
    EntitySummary,
    Extensibility,
    HubObject,
    NamedObject,
    OrphanedObject,
    RelationshipMap,
    TechnicalDebt,
    TemporalObject,
    UiArchitecture,
)
from knack_sleuth.impact_report import (
    AffectedField,
    DirectImpacts,
    FormImpact,
    FormulaImpact,
    ImpactAnalysis,
    RuleImpact,
)
from knack_sleuth.models import (
    KnackAppMetadata,
    KnackObject,
    Scene,
    SecurityReport,
    View,
)
from knack_sleuth.security import generate_security_report
from knack_sleuth.system_fields import metadata_without_system_connections

# Heuristic thresholds for the technical analysis (impact, domain model,
# graph and technical-debt sections). Changing them changes report wording,
# not correctness.
HUB_MIN_CONNECTIONS = 3  # README "Hub Object": 3+ connections in total
CORE_HUB_MIN_CONNECTIONS = 5  # a hub with high bidirectional connectivity
BOTTLENECK_MIN_INBOUND = 5
HIGH_FANOUT_MIN_OUTBOUND = 5
HIGH_RISK_BOTTLENECK_COUNT = 2  # more bottlenecks than this is high refactoring risk
LARGE_TABLE_RECORDS = 100  # at or above: transactional; below: possible lookup table
OBJECT_RISK_LOW_MAX = 5  # impact score bands for changing an object
OBJECT_RISK_MEDIUM_MAX = 15
FIELD_RISK_LOW_MAX = 3  # impact bands for changing a field
FIELD_RISK_MEDIUM_MAX = 10
CLUSTER_MIN_SHARED_NEIGHBORS = 2
TIGHT_COUPLING_MIN_SHARED = 3
COHESION_HIGH = 0.7  # share of a cluster's connections that stay inside it
COHESION_MEDIUM = 0.4
MODULARITY_HIGH = 0.7
MODULARITY_MEDIUM = 0.4
HUB_AND_SPOKE_MAX_MODULARITY = 0.5
MODULAR_MIN_MODULARITY = 0.6
FORMULA_FIELDS_HIGH = 30
FORMULA_FIELDS_MODERATE = 10
HIERARCHY_DEPTH_HIGH = 4
HIERARCHY_DEPTH_MODERATE = 2


@dataclass
class Usage:
    """Represents a usage of an object or field."""

    location_type: (
        str  # "connection", "view_source", "view_column", "field_equation", etc.
    )
    context: str  # Human-readable description of where it's used
    details: dict[str, Any]  # Additional context-specific information


@dataclass
class OrphanedView:
    """A view defined on a scene but left out of that scene's page layout."""

    scene: Scene
    view: View


@dataclass
class DanglingLayoutKey:
    """A page layout slot naming a view that is not on that scene."""

    scene: Scene
    view_key: str
    moved_to: str | None  # Scene key the view now lives on, or None if deleted


@dataclass
class StaleViewRuleReference:
    """A rule naming a view that no longer renders (or no longer exists)."""

    scene: Scene
    rule_path: str  # e.g. "rules.0.view_keys" or "views.2.rules.1.view_keys"
    view_key: str
    reason: str  # "orphaned" (defined but off-layout) or "missing" (gone)


FIELD_KEY_PATTERN = re.compile(r"(?<![A-Za-z0-9_])(field_\d+)(?![A-Za-z0-9_])")


def _iter_rule_view_keys(
    value: Any,
    path: tuple[str, ...] = (),
) -> Iterator[tuple[str, str]]:
    """Yield ``(view_key, path)`` for every ``view_keys`` entry in metadata.

    Page rules and view rules both target views through a ``view_keys`` list,
    at depths that vary by rule type, so this walks rather than indexes.
    """
    if isinstance(value, dict):
        for key, nested_value in value.items():
            nested_path = (*path, str(key))
            if key == "view_keys" and isinstance(nested_value, list):
                joined = ".".join(nested_path)
                for view_key in nested_value:
                    if isinstance(view_key, str):
                        yield view_key, joined
                continue
            yield from _iter_rule_view_keys(nested_value, nested_path)
    elif isinstance(value, list):
        for index, nested_value in enumerate(value):
            yield from _iter_rule_view_keys(nested_value, (*path, str(index)))


def _scene_layout_keys(scene: Scene) -> set[str]:
    """Return the view keys the scene's page layout actually places.

    Knack stores the layout separately from the view definitions, as
    ``groups[].columns[].keys[]``. Nothing keeps the two in sync.
    """
    return {
        key
        for group in scene.groups or []
        for column in (group or {}).get("columns") or []
        for key in (column or {}).get("keys") or []
    }


def _iter_field_references(
    value: Any,
    path: tuple[str, ...] = (),
) -> Iterator[tuple[str, tuple[str, ...]]]:
    """Yield ``(field_key, path)`` pairs from arbitrary metadata."""
    if isinstance(value, dict):
        for key, nested_value in value.items():
            nested_path = (*path, str(key))
            if isinstance(key, str):
                for match in FIELD_KEY_PATTERN.finditer(key):
                    yield match.group(1), nested_path
            yield from _iter_field_references(nested_value, nested_path)
    elif isinstance(value, list):
        for index, nested_value in enumerate(value):
            yield from _iter_field_references(
                nested_value,
                (*path, str(index)),
            )
    elif isinstance(value, str):
        for match in FIELD_KEY_PATTERN.finditer(value):
            yield match.group(1), path


def _is_typed_view_reference(path: tuple[str, ...]) -> bool:
    """Return whether an existing typed check already covers this path."""
    match path:
        case ("columns", _, "field", "key", *_) | ("source", "sort", _, "field", *_):
            return True
        case (
            ("source", "parent_source", "connection")
            | ("source", "connection_key")
            | ("inputs", _, "key")
        ):
            return True
    return False


# Object attributes that _find_field_usages checks directly, or that hold the
# object's own fields (indexed one field at a time).
_OBJECT_TYPED_ATTRS = {"key", "fields", "connections", "identifier", "sort"}


def _is_typed_equation_reference(
    field_key: str, path: tuple[str, ...], field_data: dict[str, Any]
) -> bool:
    """Return whether the field_equation check already reports this reference.

    That check only matches a literal ``{field_key}``; a connected-field
    reference such as ``{field_2.field_1}`` or an equation stored as a list
    falls through to the generic index.
    """
    if path[:2] != ("format", "equation"):
        return False
    equation = (field_data.get("format") or {}).get("equation")
    return f"{{{field_key}}}" in str(equation)


_HintKind = Literal["forms", "views", "connections", "formulas", "rules"]

# Workflow hint per kind of direct impact, in the order hints are listed.
_WORKFLOW_HINTS: dict[_HintKind, str] = {
    "forms": "User data entry forms",
    "views": "Data display views",
    "connections": "Related data relationships",
    "formulas": "Calculated fields and formulas",
    "rules": "Rules, validations and scheduled tasks",
}


def _risk_level(score: int, low_max: int, medium_max: int) -> str:
    """Breaking-change likelihood for an impact score."""
    if score == 0:
        return "none"
    if score <= low_max:
        return "low"
    if score <= medium_max:
        return "medium"
    return "high"


def _count_direct_impacts(direct: DirectImpacts) -> int:
    """Impacts that score: a view or form on no page is listed but not counted."""
    return (
        len(direct["connections"])
        + sum(1 for view in direct["views"] if not view["orphaned_view"])
        + len(direct["formulas"])
        + sum(1 for form in direct["forms"] if not form["orphaned_view"])
        + len(direct["rules"])
    )


def _workflow_hints(direct: DirectImpacts, kinds: tuple[_HintKind, ...]) -> list[str]:
    return [_WORKFLOW_HINTS[kind] for kind in kinds if direct[kind]]


def _formula_impact(usage: Usage) -> FormulaImpact:
    """A computed field that depends on the target: an equation, or a sum,
    count or similar field whose settings name it (equation is None then)."""
    return {
        "field_key": usage.details.get("field_key"),
        "field_name": usage.details.get("field_name"),
        "object_key": usage.details.get("object_key"),
        "equation": usage.details.get("equation"),
    }


def _form_impact(usage: Usage) -> FormImpact:
    return {
        "view_key": usage.details.get("view_key"),
        "view_name": usage.details.get("view_name"),
        "scene_key": usage.details.get("scene_key"),
        "orphaned_view": bool(usage.details.get("orphaned_view")),
    }


def _rule_impact(usage: Usage) -> RuleImpact:
    """A rule, validation or task on an object, or a page rule, naming the target."""
    return {
        "type": usage.location_type,
        "description": usage.context,
        "object_key": usage.details.get("object_key"),
        "scene_key": usage.details.get("scene_key"),
        "reference_path": usage.details.get("reference_path"),
    }


def _record_dependent(direct: DirectImpacts, usage: Usage) -> None:
    """File a formula, form or rule usage under its direct impact; other
    usage types are left to the caller."""
    if usage.location_type in ("field_equation", "field_reference"):
        direct["formulas"].append(_formula_impact(usage))
    elif usage.location_type == "form_input":
        direct["forms"].append(_form_impact(usage))
    elif usage.location_type in ("object_reference", "scene_reference"):
        direct["rules"].append(_rule_impact(usage))


def _note_scene(scenes_seen: dict[str, None], usage: Usage) -> None:
    """A page the usage is on, unless it is a view no page shows."""
    scene_key = usage.details.get("scene_key")
    if scene_key and not usage.details.get("orphaned_view"):
        scenes_seen[scene_key] = None


def _affected_objects(direct: DirectImpacts, own_object: str) -> list[str]:
    """Other objects that connect to, compute from, or have rules on the target."""
    named: list[Any] = []
    for connection in direct["connections"]:
        named += [connection.get("source_object"), connection.get("target_object")]
    named += [formula["object_key"] for formula in direct["formulas"]]
    named += [rule["object_key"] for rule in direct["rules"]]
    # dict, not set: first-seen order keeps the output stable.
    return list(dict.fromkeys(key for key in named if key and key != own_object))


def _score_importance(summaries: list[EntitySummary]) -> None:
    """Set each summary's importance_score: 60% volume, 40% connectivity,
    each normalised to the largest in the list."""
    if not summaries:
        return
    max_volume = max(s["record_count"] for s in summaries) or 1
    max_connectivity = max(s["total_connections"] for s in summaries) or 1
    for summary in summaries:
        volume_score = summary["record_count"] / max_volume
        connectivity_score = summary["total_connections"] / max_connectivity
        summary["importance_score"] = (volume_score * 0.6) + (connectivity_score * 0.4)


def _core_entity_keys(summaries: list[EntitySummary]) -> set[str]:
    """Keys of the top N by importance: N is 20% of the list, at least 4, at most 10."""
    max_core_entities = min(10, max(4, int(len(summaries) * 0.2)))
    ranked = sorted(summaries, key=lambda x: x.get("importance_score", 0), reverse=True)
    return {summary["object_key"] for summary in ranked[:max_core_entities]}


def _cohesion(internal: int, total: int) -> str:
    """How much of a cluster's connectivity stays inside it."""
    if total == 0:
        return "low"
    ratio = internal / total
    if ratio > COHESION_HIGH:
        return "high"
    if ratio > COHESION_MEDIUM:
        return "medium"
    return "low"


class _ReferenceOwner(NamedTuple):
    """Where an indexed field reference lives, for building its Usage."""

    location_type: str
    where: str
    details: dict[str, Any]


class KnackSleuth:
    """Search engine for finding object and field usages in Knack metadata."""

    def __init__(self, app_export: KnackAppMetadata):
        self.app_export = app_export
        self.app = app_export.application
        self._build_indexes()

    def _build_indexes(self) -> None:
        """Build lookup indexes for faster searching."""
        # Object index
        self.objects_by_key: dict[str, KnackObject] = {
            obj.key: obj for obj in self.app.objects
        }

        # Field index (field_key -> object_key)
        self.field_to_object: dict[str, str] = {}
        for obj in self.app.objects:
            for field in obj.fields:
                self.field_to_object[field.key] = obj.key

        # View index (view_key -> scene_key), for spotting layout slots that
        # point at a view living on some other scene.
        self.view_to_scene: dict[str, str] = {
            view.key: scene.key for scene in self.app.scenes for view in scene.views
        }

        # Untyped view containers vary by view type and Knack version. Index
        # their field references once so orphan checks remain linear in the
        # metadata size rather than recursively scanning every view per field.
        self.view_field_references: dict[
            str, list[tuple[Any, Any, tuple[str, ...]]]
        ] = {}
        for scene in self.app.scenes:
            for view in scene.views:
                view_data = view.model_dump(mode="python", exclude_none=True)
                for field_key, path in _iter_field_references(view_data):
                    if (
                        field_key not in self.field_to_object
                        or _is_typed_view_reference(path)
                    ):
                        continue
                    reference = (scene, view, path)
                    references = self.view_field_references.setdefault(field_key, [])
                    if reference not in references:
                        references.append(reference)

        self.metadata_field_references = self._index_metadata_references()

        # A view left out of its page layout never renders, so a reference
        # living only there does not keep a field or object alive. Cached
        # because every usage scan consults it.
        self.orphaned_view_keys: set[str] = {
            orphan.view.key for orphan in self.find_orphaned_views()
        }

    def _index_metadata_references(self) -> dict[str, list[Usage]]:
        """Index field references that live outside views.

        Other fields' definitions (formulas, sum/count fields and their
        filters, conditional rules, validation), object tasks and page rules
        all name fields. A field's references to itself don't count, and those
        the typed checks in _find_field_usages report are skipped.
        """
        index: dict[str, list[Usage]] = {}
        for obj in self.app.objects:
            for field in obj.fields:
                data = field.model_dump(mode="python", exclude_none=True, by_alias=True)
                owner = _ReferenceOwner(
                    "field_reference",
                    f"{obj.name}.{field.name} ({field.key})",
                    {
                        "object_key": obj.key,
                        "object_name": obj.name,
                        "field_key": field.key,
                        "field_name": field.name,
                    },
                )
                for field_key, path in _iter_field_references(data):
                    if field_key != field.key and not _is_typed_equation_reference(
                        field_key, path, data
                    ):
                        self._add_reference(index, field_key, path, owner)
            data = obj.model_dump(
                mode="python", exclude_none=True, exclude=_OBJECT_TYPED_ATTRS
            )
            owner = _ReferenceOwner(
                "object_reference",
                f"object {obj.name} ({obj.key})",
                {"object_key": obj.key, "object_name": obj.name},
            )
            for field_key, path in _iter_field_references(data):
                self._add_reference(index, field_key, path, owner)
        for scene in self.app.scenes:
            data = scene.model_dump(mode="python", exclude_none=True, exclude={"views"})
            owner = _ReferenceOwner(
                "scene_reference",
                f"page '{scene.name}' ({scene.key})",
                {"scene_key": scene.key, "scene_name": scene.name},
            )
            for field_key, path in _iter_field_references(data):
                self._add_reference(index, field_key, path, owner)
        return index

    def _add_reference(
        self,
        index: dict[str, list[Usage]],
        field_key: str,
        path: tuple[str, ...],
        owner: _ReferenceOwner,
    ) -> None:
        """Record one reference to a known field, once per owner and path."""
        if field_key not in self.field_to_object:
            return
        reference_path = ".".join(path)
        usage = Usage(
            location_type=owner.location_type,
            context=f"Referenced at {reference_path} in {owner.where}",
            details={**owner.details, "reference_path": reference_path},
        )
        usages = index.setdefault(field_key, [])
        if usage not in usages:
            usages.append(usage)

    def search_object(self, object_key: str) -> dict[str, list[Usage]]:
        """
        Search for all usages of an object and cascade to its fields.

        Returns a dict with:
        - "object_usages": list of usages of the object itself
        - field keys (e.g., "field_116"): list of usages for each field
        """
        if object_key not in self.objects_by_key:
            return {}

        obj = self.objects_by_key[object_key]
        results: dict[str, list[Usage]] = {"object_usages": []}

        # Search for object-level usages
        results["object_usages"] = self._find_object_usages(object_key)

        # Cascade: search for each field in the object
        for field in obj.fields:
            field_usages = self._find_field_usages(field.key)
            if field_usages:
                results[field.key] = field_usages

        return results

    def search_field(self, field_key: str) -> list[Usage]:
        """Search for all usages of a specific field."""
        if field_key not in self.field_to_object:
            return []

        return self._find_field_usages(field_key)

    def _find_object_usages(self, object_key: str) -> list[Usage]:
        """Find all places where an object is referenced."""
        # 1. Connections (inbound and outbound)
        usages = self._object_connection_usages(object_key)

        # 2. Check view sources
        for scene in self.app.scenes:
            for view in scene.views:
                if view.source and view.source.object == object_key:
                    usages.append(
                        Usage(
                            location_type="view_source",
                            context=f"View '{view.name}' ({view.key}) in scene '{scene.name}' ({scene.key}) displays this object",
                            details={
                                "scene_key": scene.key,
                                "scene_name": scene.name,
                                "view_key": view.key,
                                "view_name": view.name,
                                "view_type": view.type,
                            },
                        )
                    )

                # Check parent_source
                if (
                    view.source
                    and view.source.parent_source
                    and view.source.parent_source.object == object_key
                ):
                    usages.append(
                        Usage(
                            location_type="view_parent_source",
                            context=f"View '{view.name}' ({view.key}) uses this object as parent source",
                            details={
                                "scene_key": scene.key,
                                "scene_name": scene.name,
                                "view_key": view.key,
                                "view_name": view.name,
                            },
                        )
                    )

        return self._tag_orphaned_view_usages(usages)

    def _object_connection_usages(self, object_key: str) -> list[Usage]:
        """Connections on other objects that point at, or come from, this object."""
        usages: list[Usage] = []
        for obj in self.app.objects:
            if obj.connections:
                # Check outbound connections
                for conn in obj.connections.outbound:
                    if conn.object == object_key:
                        usages.append(
                            Usage(
                                location_type="connection_outbound",
                                context=f"{obj.name} ({obj.key}) connects to this object via {conn.name} ({conn.key})",
                                details={
                                    "source_object": obj.key,
                                    "source_object_name": obj.name,
                                    "connection_field": conn.key,
                                    "connection_name": conn.name,
                                    "relationship": conn.relationship_type(),
                                },
                            )
                        )

                # Check inbound connections
                for conn in obj.connections.inbound:
                    if conn.object == object_key:
                        usages.append(
                            Usage(
                                location_type="connection_inbound",
                                context=f"This object connects from {obj.name} ({obj.key}) via {conn.name} ({conn.key})",
                                details={
                                    "target_object": obj.key,
                                    "target_object_name": obj.name,
                                    "connection_field": conn.key,
                                    "connection_name": conn.name,
                                    "relationship": conn.relationship_type(),
                                },
                            )
                        )
        return usages

    def _tag_orphaned_view_usages(self, usages: list[Usage]) -> list[Usage]:
        """Mark usages that live in a view no page layout places.

        The reference is still reported -- the user needs to see where the dead
        pointer is -- but it no longer counts as keeping anything alive.
        """
        for usage in usages:
            view_key = usage.details.get("view_key")
            if view_key is not None:
                usage.details["orphaned_view"] = view_key in self.orphaned_view_keys
        return usages

    def _find_field_usages(self, field_key: str) -> list[Usage]:
        """Find all places where a field is referenced."""
        usages = [
            *self._connection_field_usages(field_key),
            *self._object_setting_usages(field_key),
            *self._equation_usages(field_key),
            *self._view_column_usages(field_key),
            *self._view_source_usages(field_key),
            *self._form_input_usages(field_key),
            *self._view_reference_usages(field_key),
            *self._metadata_reference_usages(field_key),
        ]
        return self._tag_orphaned_view_usages(usages)

    def _views(self) -> Iterator[tuple[Scene, View]]:
        for scene in self.app.scenes:
            for view in scene.views:
                yield scene, view

    @staticmethod
    def _view_details(scene: Scene, view: View, **extra: Any) -> dict[str, Any]:
        return {
            "scene_key": scene.key,
            "scene_name": scene.name,
            "view_key": view.key,
            "view_name": view.name,
            **extra,
        }

    def _connection_field_usages(self, field_key: str) -> Iterator[Usage]:
        """The field is a connection defined on an object."""
        for obj in self.app.objects:
            if not obj.connections:
                continue
            for conn in obj.connections.outbound:
                if conn.key == field_key:
                    yield Usage(
                        location_type="connection_field",
                        context=f"Connection field in {obj.name} ({obj.key})",
                        details={
                            "object_key": obj.key,
                            "object_name": obj.name,
                            "target_object": conn.object,
                            "connection_name": conn.name,
                        },
                    )

    def _object_setting_usages(self, field_key: str) -> Iterator[Usage]:
        """The field sorts an object's records or identifies them."""
        for obj in self.app.objects:
            if obj.sort and obj.sort.field == field_key:
                yield Usage(
                    location_type="object_sort",
                    context=f"Used as sort field for {obj.name} ({obj.key})",
                    details={
                        "object_key": obj.key,
                        "object_name": obj.name,
                        "sort_order": obj.sort.order,
                    },
                )
            if obj.identifier == field_key:
                yield Usage(
                    location_type="object_identifier",
                    context=f"Used as identifier field for {obj.name} ({obj.key})",
                    details={"object_key": obj.key, "object_name": obj.name},
                )

    def _equation_usages(self, field_key: str) -> Iterator[Usage]:
        """Another field's equation contains a literal ``{field_key}``."""
        for obj in self.app.objects:
            for field in obj.fields:
                if field.format is None:
                    continue
                equation = field.format.model_dump().get("equation")
                if equation and f"{{{field_key}}}" in str(equation):
                    yield Usage(
                        location_type="field_equation",
                        context=f"Referenced in equation for {obj.name}.{field.name} ({field.key})",
                        details={
                            "object_key": obj.key,
                            "object_name": obj.name,
                            "field_key": field.key,
                            "field_name": field.name,
                            "equation": equation,
                        },
                    )

    def _view_column_usages(self, field_key: str) -> Iterator[Usage]:
        """A table view shows the field as a column."""
        for scene, view in self._views():
            for col in view.columns:
                if col.field and col.field.get("key") == field_key:
                    yield Usage(
                        location_type="view_column",
                        context=f"Column in view '{view.name}' ({view.key}) in scene '{scene.name}'",
                        details=self._view_details(
                            scene, view, view_type=view.type, column_header=col.header
                        ),
                    )

    def _view_source_usages(self, field_key: str) -> Iterator[Usage]:
        """A view's data source sorts by the field or connects through it."""
        for scene, view in self._views():
            source = view.source
            if not source:
                continue
            for sort in source.sort or []:
                if sort.field == field_key:
                    yield Usage(
                        location_type="view_sort",
                        context=f"Sort field in view '{view.name}' ({view.key})",
                        details=self._view_details(scene, view, sort_order=sort.order),
                    )
            if source.parent_source and source.parent_source.connection == field_key:
                yield Usage(
                    location_type="view_parent_connection",
                    context=f"Parent connection in view '{view.name}' ({view.key})",
                    details=self._view_details(scene, view),
                )
            if source.connection_key == field_key:
                yield Usage(
                    location_type="view_connection_key",
                    context=f"Connection key in view '{view.name}' ({view.key})",
                    details=self._view_details(scene, view),
                )

    def _form_input_usages(self, field_key: str) -> Iterator[Usage]:
        """A form view's top-level inputs include the field."""
        for scene, view in self._views():
            for input_field in view.inputs:
                if (
                    isinstance(input_field, dict)
                    and input_field.get("key") == field_key
                ):
                    yield Usage(
                        location_type="form_input",
                        context=f"Input field in form '{view.name}' ({view.key})",
                        details=self._view_details(scene, view),
                    )

    def _view_reference_usages(self, field_key: str) -> Iterator[Usage]:
        """Untyped view metadata names the field.

        Knack stores important field references in containers such as form
        groups, view rules, totals, preset filters, and report calculations.
        These vary by view type, so _build_indexes walks each complete view
        rather than maintain an incomplete list of schemas, skipping what the
        typed checks above already report.
        """
        for scene, view, path in self.view_field_references.get(field_key, []):
            reference_path = ".".join(path)
            yield Usage(
                location_type="view_field_reference",
                context=(
                    f"Referenced at {reference_path} in view '{view.name}' ({view.key})"
                ),
                details=self._view_details(
                    scene, view, view_type=view.type, reference_path=reference_path
                ),
            )

    def _metadata_reference_usages(self, field_key: str) -> Iterator[Usage]:
        """Other fields' definitions, object tasks and page rules name the field.

        Copies, so a caller that edits a Usage can't change the shared index.
        """
        for usage in self.metadata_field_references.get(field_key, []):
            yield replace(usage, details=dict(usage.details))

    def get_object_info(self, object_key: str) -> KnackObject | None:
        """Get the object definition."""
        return self.objects_by_key.get(object_key)

    def get_field_info(self, field_key: str) -> tuple[KnackObject | None, Any]:
        """Get the field definition and its parent object."""
        object_key = self.field_to_object.get(field_key)
        if not object_key:
            return None, None

        obj = self.objects_by_key[object_key]
        for field in obj.fields:
            if field.key == field_key:
                return obj, field

        return obj, None

    def find_orphaned_fields(self) -> list[tuple[KnackObject, Any]]:
        """Find fields with no usages anywhere (views, equations, connections).

        Returns a list of (object, field) pairs. Note that system fields and
        identifier fields can legitimately appear here — callers should let
        users judge those rather than auto-flagging them for deletion.
        """
        orphans: list[tuple[KnackObject, Any]] = []
        for obj in self.app.objects:
            for field in obj.fields:
                live_usages = [
                    usage
                    for usage in self._find_field_usages(field.key)
                    if not usage.details.get("orphaned_view")
                ]
                if not live_usages:
                    orphans.append((obj, field))
        return orphans

    def find_orphaned_objects(self) -> list[KnackObject]:
        """Find objects with no connections and no views displaying them.

        User profile objects (those with a profile_key) are excluded — they are
        referenced through Knack's auth system rather than connections/views.
        """
        orphans: list[KnackObject] = []
        for obj in self.app.objects:
            if obj.profile_key:
                continue

            if obj.connections and (
                obj.connections.inbound or obj.connections.outbound
            ):
                continue

            used_in_views = any(
                view.source
                and view.source.object == obj.key
                and view.key not in self.orphaned_view_keys
                for scene in self.app.scenes
                for view in scene.views
            )
            if not used_in_views:
                orphans.append(obj)
        return orphans

    def find_orphaned_views(self) -> list[OrphanedView]:
        """Find views defined on a scene but absent from its page layout.

        Such a view never renders: Knack draws a page from
        ``groups[].columns[].keys[]``, not from ``scene.views``. They
        accumulate when a page is copied or a view is moved.

        Two exclusions keep this honest, both measured against a real app:

        - ``login`` views are rendered from the scene chrome, so 48 of 49 sit
          outside the layout legitimately.
        - A scene whose layout is *entirely* empty has no layout to be excluded
          from. Knack leaves ``groups`` empty on the child pages it generates
          for Edit/Details/Delete links.

        Without those, the check reports 114 hits on an app that has 24.
        """
        orphans: list[OrphanedView] = []
        for scene in self.app.scenes:
            layout_keys = _scene_layout_keys(scene)
            if not layout_keys:
                continue
            for view in scene.views:
                if view.type == "login":
                    continue
                if view.key not in layout_keys:
                    orphans.append(OrphanedView(scene=scene, view=view))
        return orphans

    def find_dangling_layout_keys(self) -> list[DanglingLayoutKey]:
        """Find layout slots pointing at views the scene does not have.

        The inverse of an orphaned view. ``moved_to`` distinguishes the two
        causes: a view relocated to another scene leaves the old layout
        pointing across scenes, while a deleted view leaves nothing at all.
        """
        dangling: list[DanglingLayoutKey] = []
        for scene in self.app.scenes:
            own_keys = {view.key for view in scene.views}
            for view_key in sorted(_scene_layout_keys(scene) - own_keys):
                dangling.append(
                    DanglingLayoutKey(
                        scene=scene,
                        view_key=view_key,
                        moved_to=self.view_to_scene.get(view_key),
                    )
                )
        return dangling

    def find_stale_view_rule_references(self) -> list[StaleViewRuleReference]:
        """Find rules targeting views that no longer render.

        A ``hide_views`` rule keeps naming its target after the view leaves the
        layout or is deleted outright, so these outlive the view itself and are
        the clearest signal that a page was edited around a leftover.
        """
        stale: list[StaleViewRuleReference] = []
        for scene in self.app.scenes:
            scene_data = scene.model_dump(mode="python", exclude_none=True)
            for view_key, rule_path in _iter_rule_view_keys(scene_data):
                if view_key in self.orphaned_view_keys:
                    reason = "orphaned"
                elif view_key not in self.view_to_scene:
                    reason = "missing"
                else:
                    continue
                stale.append(
                    StaleViewRuleReference(
                        scene=scene,
                        rule_path=rule_path,
                        view_key=view_key,
                        reason=reason,
                    )
                )
        return stale

    def generate_impact_analysis(
        self, target_key: str, target_type: str = "auto"
    ) -> ImpactAnalysis:
        """
        Generate a comprehensive impact analysis for AI consumption.

        Args:
            target_key: The object or field key to analyze (e.g., 'object_12' or 'field_116')
            target_type: 'object', 'field', or 'auto' (default: auto-detect)

        Returns:
            A structured dictionary with impact analysis suitable for AI agents.
            When the target cannot be analysed it has an ``error`` key and
            every list is empty.
        """
        # Auto-detect target type
        error: str | None = None
        if target_type == "auto":
            if target_key.startswith("object_"):
                target_type = "object"
            elif target_key.startswith("field_"):
                target_type = "field"
            else:
                error = "Could not detect target type from key"
        elif target_type not in ("object", "field"):
            error = f"Unknown target type '{target_type}': use object or field"

        # Initialize analysis structure
        analysis: ImpactAnalysis = {
            "target": {
                "key": target_key,
                "type": target_type,
                "name": None,
                "description": None,
            },
            "direct_impacts": {
                "connections": [],
                "views": [],
                "scenes": [],
                "formulas": [],
                "forms": [],
                "rules": [],
            },
            "cascade_impacts": {
                "affected_fields": [],
                "affected_objects": [],
                "affected_scenes": [],
            },
            "risk_assessment": {
                "breaking_change_likelihood": "unknown",
                "impact_score": 0,
                "affected_user_workflows": [],
            },
            "metadata": {
                "total_direct_impacts": 0,
                "total_cascade_impacts": 0,
            },
        }

        if error:
            analysis["error"] = error
            return analysis
        if target_type == "object":
            return self._analyze_object_impact(target_key, analysis)
        return self._analyze_field_impact(target_key, analysis)

    def _analyze_object_impact(
        self, object_key: str, analysis: ImpactAnalysis
    ) -> ImpactAnalysis:
        """Analyze impact of changes to an object."""
        obj = self.get_object_info(object_key)
        if not obj:
            analysis["error"] = f"Object {object_key} not found"
            return analysis

        analysis["target"]["name"] = obj.name
        analysis["target"]["description"] = f"{len(obj.fields)} fields"

        results = self.search_object(object_key)
        direct = analysis["direct_impacts"]
        # dict, not set: keeps first-seen order so output is stable across
        # processes (str hashing is randomized per PYTHONHASHSEED).
        scenes_seen: dict[str, None] = {}

        for usage in results.get("object_usages", []):
            if "connection" in usage.location_type:
                direct["connections"].append(
                    {
                        "type": usage.location_type,
                        "description": usage.context,
                        "source_object": usage.details.get("source_object"),
                        "connection_field": usage.details.get("connection_field"),
                    }
                )
            elif "view" in usage.location_type:
                self._record_view_impact(analysis, usage, scenes_seen)

        for field_key, usages in results.items():
            if field_key.startswith("field_"):
                field_impact = self._field_cascade(
                    field_key, usages, analysis, scenes_seen
                )
                if field_impact:
                    analysis["cascade_impacts"]["affected_fields"].append(field_impact)

        self._record_scenes(analysis, scenes_seen)
        analysis["cascade_impacts"]["affected_objects"] = _affected_objects(
            direct, object_key
        )

        affected_fields = len(analysis["cascade_impacts"]["affected_fields"])
        total_impacts = _count_direct_impacts(direct)
        analysis["metadata"]["total_direct_impacts"] = total_impacts
        analysis["metadata"]["total_cascade_impacts"] = affected_fields
        impact_score = total_impacts + affected_fields
        analysis["risk_assessment"]["impact_score"] = impact_score
        analysis["risk_assessment"]["breaking_change_likelihood"] = _risk_level(
            impact_score, OBJECT_RISK_LOW_MAX, OBJECT_RISK_MEDIUM_MAX
        )
        analysis["risk_assessment"]["affected_user_workflows"] += _workflow_hints(
            direct, ("forms", "views", "connections", "rules")
        )
        return analysis

    def _field_cascade(
        self,
        field_key: str,
        usages: list[Usage],
        analysis: ImpactAnalysis,
        scenes_seen: dict[str, None],
    ) -> AffectedField | None:
        """One of an object's fields: its usages, plus the formulas, forms and
        rules they put in the object's direct impacts."""
        _, field_info = self.get_field_info(field_key)
        if not field_info:
            return None
        for usage in usages:
            _record_dependent(analysis["direct_impacts"], usage)
            _note_scene(scenes_seen, usage)
        return {
            "field_key": field_key,
            "field_name": field_info.name,
            "field_type": field_info.type,
            "usage_count": len(usages),
            "usages": [
                {"type": usage.location_type, "context": usage.context}
                for usage in usages
            ],
        }

    def _analyze_field_impact(
        self, field_key: str, analysis: ImpactAnalysis
    ) -> ImpactAnalysis:
        """Analyze impact of changes to a field."""
        obj_info, field_info = self.get_field_info(field_key)
        if not field_info or not obj_info:
            analysis["error"] = f"Field {field_key} not found"
            return analysis

        analysis["target"]["name"] = f"{obj_info.name}.{field_info.name}"
        analysis["target"]["description"] = f"{field_info.type} field"

        direct = analysis["direct_impacts"]
        # dict, not set: keeps first-seen order so output is stable across
        # processes (str hashing is randomized per PYTHONHASHSEED).
        scenes_seen: dict[str, None] = {}

        for usage in self.search_field(field_key):
            if usage.location_type == "connection_field":
                direct["connections"].append(
                    {
                        "type": "connection",
                        "description": usage.context,
                        "target_object": usage.details.get("target_object"),
                    }
                )
            elif "view" in usage.location_type:
                self._record_view_impact(analysis, usage, scenes_seen)
            else:
                _record_dependent(direct, usage)
                _note_scene(scenes_seen, usage)

        self._record_scenes(analysis, scenes_seen)
        analysis["cascade_impacts"]["affected_objects"] = _affected_objects(
            direct, obj_info.key
        )

        total_impacts = _count_direct_impacts(direct)
        analysis["metadata"]["total_direct_impacts"] = total_impacts
        analysis["risk_assessment"]["impact_score"] = total_impacts
        analysis["risk_assessment"]["breaking_change_likelihood"] = _risk_level(
            total_impacts, FIELD_RISK_LOW_MAX, FIELD_RISK_MEDIUM_MAX
        )
        analysis["risk_assessment"]["affected_user_workflows"] += _workflow_hints(
            direct, ("forms", "views", "formulas", "rules")
        )
        return analysis

    @staticmethod
    def _record_view_impact(
        analysis: ImpactAnalysis, usage: Usage, scenes_seen: dict[str, None]
    ) -> None:
        _note_scene(scenes_seen, usage)
        analysis["direct_impacts"]["views"].append(
            {
                "view_key": usage.details.get("view_key"),
                "view_name": usage.details.get("view_name"),
                "view_type": usage.details.get("view_type"),
                "scene_key": usage.details.get("scene_key"),
                "scene_name": usage.details.get("scene_name"),
                "orphaned_view": bool(usage.details.get("orphaned_view")),
            }
        )

    def _record_scenes(
        self, analysis: ImpactAnalysis, scenes_seen: dict[str, None]
    ) -> None:
        """Add the scenes seen, in first-seen order, skipping unknown keys."""
        scenes_by_key: dict[str, Scene] = {}
        for scene in self.app.scenes:
            scenes_by_key.setdefault(scene.key, scene)
        for scene_key in scenes_seen:
            scene = scenes_by_key.get(scene_key)
            if scene is None:
                continue
            analysis["direct_impacts"]["scenes"].append(
                {
                    "scene_key": scene_key,
                    "scene_name": scene.name,
                    "scene_slug": scene.slug,
                }
            )
            analysis["cascade_impacts"]["affected_scenes"].append(scene_key)

    def generate_app_summary(
        self, include_system_connections: bool = False
    ) -> AppSummary:
        """
        Generate a comprehensive architectural summary of the entire application.

        This provides universal context for any architectural discussion or change,
        including domain model, relationships, patterns, and extensibility.

        Args:
            include_system_connections: Count Knack's own audit connections
                (Created By, Updated By, Owned By) as relationships. Off by
                default: they join every object to Accounts and hide the
                app's real structure.

        Returns:
            A structured dictionary with complete app architecture summary
        """
        # Relationships are read from a view without the system connections.
        # Orphans are not: there the connection is what makes the field used.
        model, excluded = self, 0
        if not include_system_connections:
            export, excluded = metadata_without_system_connections(self.app_export)
            if excluded:
                model = KnackSleuth(export)
        application = model._analyze_application_metadata()
        application["complexity_metrics"]["system_connections_excluded"] = excluded
        return {
            "application": application,
            "domain_model": model._analyze_domain_model(),
            "relationship_map": model._analyze_relationship_topology(),
            "data_patterns": self._analyze_data_patterns(),
            "ui_architecture": self._analyze_ui_architecture(),
            "access_patterns": self._analyze_access_patterns(),
            "technical_debt_indicators": self._analyze_technical_debt(model),
            "extensibility_assessment": model._analyze_extensibility(),
        }

    def _analyze_application_metadata(self) -> ApplicationSummary:
        """Extract basic application metadata and complexity metrics."""
        total_fields = sum(len(obj.fields) for obj in self.app.objects)
        total_views = sum(len(scene.views) for scene in self.app.scenes)
        total_records = self.app.counts.get("total_entries", 0)

        # Calculate connection density
        total_objects = len(self.app.objects)
        actual_connections = sum(
            len(obj.connections.inbound) + len(obj.connections.outbound)
            if obj.connections
            else 0
            for obj in self.app.objects
        )
        possible_connections = total_objects * (total_objects - 1)
        connection_density = (
            actual_connections / possible_connections
            if possible_connections > 0
            else 0.0
        )

        return {
            "name": self.app.name,
            "id": self.app.id,
            "complexity_metrics": {
                "total_objects": total_objects,
                "total_fields": total_fields,
                "total_scenes": len(self.app.scenes),
                "total_views": total_views,
                "total_records": total_records,
                "connection_density": round(connection_density, 3),
            },
        }

    def _classify_object_roles(self, obj: KnackObject) -> dict[str, Any]:
        """Classify an object into multiple orthogonal categories.

        Returns a dict with boolean flags:
        - is_user_profile: User/account/auth object (has profile_key)
        - is_core_entity: Determined dynamically in _analyze_domain_model (set post-hoc)
        - primary_role: One of 'transactional', 'reference', 'supporting'

        Primary roles are mutually exclusive:
        - Transactional: medium-high record count with connections
        - Reference: low record count, used by others (inbound >> outbound)
        - Supporting: low record count, low connectivity

        Note: is_core_entity is a placeholder here; actual core entity selection
        happens in _analyze_domain_model based on top N by volume/connectivity.
        """
        record_count = self.app.counts.get(obj.key, 0)
        inbound = 0
        outbound = 0
        if obj.connections:
            inbound = len(obj.connections.inbound)
            outbound = len(obj.connections.outbound)
        total_connections = inbound + outbound

        # Check if user profile
        is_user_profile = bool(obj.profile_key)

        # Classify primary role (mutually exclusive)
        primary_role = ""
        if record_count < LARGE_TABLE_RECORDS and inbound > outbound:
            primary_role = "reference"
        elif record_count >= LARGE_TABLE_RECORDS and total_connections > 0:
            primary_role = "transactional"
        else:
            primary_role = "supporting"

        return {
            "is_user_profile": is_user_profile,
            "is_core_entity": False,  # Set post-hoc in _analyze_domain_model
            "primary_role": primary_role,
        }

    def _calculate_centrality(self, obj: KnackObject) -> float:
        """Calculate how central/important an object is (0-1 scale)."""
        if not obj.connections:
            return 0.0

        connection_count = len(obj.connections.inbound) + len(obj.connections.outbound)
        max_connections = len(self.app.objects) - 1

        # Factor in both connections and usage
        connection_score = (
            connection_count / max_connections if max_connections > 0 else 0
        )

        # Count how many views use this object
        view_usage = 0
        for scene in self.app.scenes:
            for view in scene.views:
                if view.source and view.source.object == obj.key:
                    view_usage += 1

        max_views = sum(len(scene.views) for scene in self.app.scenes)
        view_score = view_usage / max_views if max_views > 0 else 0

        # Weighted average (connections more important)
        centrality = (connection_score * 0.7) + (view_score * 0.3)

        return round(centrality, 3)

    def _analyze_domain_model(self) -> DomainModel:
        """Analyze domain model and classify objects into orthogonal categories.

        Core entity selection: Top N objects by record count OR connectivity.
        - Maximum: 20% of total objects, capped at 10
        - Minimum: Top 2 (highest volume) + Top 2 (most connected), deduplicated
        - Always exclude user profiles from this calculation

        Returns:
            - user_profiles: Objects that represent user/auth entities
            - core_entities: Top N most important by volume or connectivity
            - transactional_entities: Medium-high records with connections (primary role)
            - reference_data: Low record count, used by many (primary role)
            - supporting_entities: Low record count, low connectivity (primary role)
        """
        user_profiles: list[EntitySummary] = []
        ranked_pool = []  # everyone else, ranked for core status
        for obj in self.app.objects:
            roles = self._classify_object_roles(obj)
            summary = self._object_summary(obj, roles)
            if roles["is_user_profile"]:
                user_profiles.append(summary)
                continue
            if roles["primary_role"] == "reference":
                summary["used_by"] = self._objects_connecting_to(obj.key)
            ranked_pool.append(summary)

        _score_importance(ranked_pool)
        core_keys = _core_entity_keys(ranked_pool)

        # Core entities come out of the pool; everything else is filed under
        # its primary role, so each object appears in exactly one category.
        core_entities: list[EntitySummary] = []
        by_role: dict[str, list[EntitySummary]] = {
            "reference": [],
            "transactional": [],
            "supporting": [],
        }
        for summary in ranked_pool:
            if summary["object_key"] in core_keys:
                summary["is_core_entity"] = True
                core_entities.append(summary)
            else:
                role = summary["primary_role"]
                by_role[role if role in by_role else "supporting"].append(summary)

        core_entities.sort(key=lambda x: x.get("importance_score", 0), reverse=True)

        return {
            "user_profiles": sorted(
                user_profiles, key=lambda x: x["record_count"], reverse=True
            ),
            "core_entities": core_entities,
            "transactional_entities": sorted(
                by_role["transactional"], key=lambda x: x["record_count"], reverse=True
            ),
            "reference_data": sorted(
                by_role["reference"],
                key=lambda x: len(x.get("used_by", [])),
                reverse=True,
            ),
            "supporting_entities": sorted(
                by_role["supporting"], key=lambda x: x["record_count"], reverse=True
            ),
        }

    def _object_summary(self, obj: KnackObject, roles: dict[str, Any]) -> EntitySummary:
        """The per-object entry the domain model lists."""
        field_types: dict[str, int] = {}
        for field in obj.fields:
            field_types[field.type] = field_types.get(field.type, 0) + 1
        total_connections = (
            len(obj.connections.inbound) + len(obj.connections.outbound)
            if obj.connections
            else 0
        )
        return {
            "object_key": obj.key,
            "name": obj.name,
            "record_count": self.app.counts.get(obj.key, 0),
            "field_count": len(obj.fields),
            "centrality_score": self._calculate_centrality(obj),
            "field_types": field_types,
            "total_connections": total_connections,
            "is_core_entity": False,
            "primary_role": roles["primary_role"],
        }

    def _objects_connecting_to(self, object_key: str) -> list[str]:
        """Keys of objects with an outbound connection to this one, once per connection."""
        return [
            other.key
            for other in self.app.objects
            if other.connections
            for conn in other.connections.outbound
            if conn.object == object_key
        ]

    def _analyze_relationship_topology(self) -> RelationshipMap:
        """Analyze connection graph, clusters, and hub objects."""
        # Build connection graph
        edges: list[ConnectionEdge] = []
        for obj in self.app.objects:
            if obj.connections:
                for conn in obj.connections.outbound:
                    edges.append(
                        {
                            "from": obj.key,
                            "from_name": obj.name,
                            "to": conn.object,
                            "to_name": (
                                self.objects_by_key[conn.object].name
                                if conn.object in self.objects_by_key
                                else "Unknown"
                            ),
                            "via": conn.key,
                            "connection_name": conn.name,
                            # From the connecting object's side: many Events
                            # to one Client is has=one, belongs_to=many.
                            "type": f"{conn.belongs_to}_to_{conn.has}",
                        }
                    )

        # Calculate hub objects (high connection count)
        hub_objects: list[HubObject] = []
        for obj in self.app.objects:
            if obj.connections:
                inbound = len(obj.connections.inbound)
                outbound = len(obj.connections.outbound)
                total = inbound + outbound

                if total >= HUB_MIN_CONNECTIONS:
                    hub_objects.append(
                        {
                            "object": obj.name,
                            "object_key": obj.key,
                            "inbound_connections": inbound,
                            "outbound_connections": outbound,
                            "total_connections": total,
                            "interpretation": self._interpret_hub_role(
                                inbound, outbound
                            ),
                        }
                    )

        hub_objects.sort(key=lambda x: x["total_connections"], reverse=True)

        # Identify dependency clusters (simplified - objects with strong interconnections)
        clusters = self._identify_clusters()

        return {
            "connection_graph": {
                "nodes": [obj.key for obj in self.app.objects],
                "edges": edges,
                "total_connections": len(edges),
            },
            "hub_objects": hub_objects,
            "dependency_clusters": clusters,
        }

    def _interpret_hub_role(self, inbound: int, outbound: int) -> str:
        """Interpret what kind of hub an object is based on connection patterns."""
        total = inbound + outbound
        if total == 0:
            return "Isolated"
        if inbound > outbound * 2:
            return "Central dependency - many objects depend on this"
        if outbound > inbound * 2:
            return "Aggregator - depends on many objects"
        if total >= CORE_HUB_MIN_CONNECTIONS:
            return "Core hub - high bidirectional connectivity"
        return "Moderately connected"

    def _identify_clusters(self) -> list[DependencyCluster]:
        """Identify groups of highly interconnected objects (simplified clustering).

        Each object not yet clustered seeds a cluster of the objects it
        connects to or shares enough neighbours with.
        """
        adjacency = self._adjacency()
        clusters = []
        processed: set[str] = set()
        for obj in self.app.objects:
            if obj.key in processed:
                continue
            members = self._cluster_members(obj.key, adjacency, processed)
            if len(members) > 1:
                clusters.append(self._cluster_stats(members, adjacency))
                processed.update(members)
        return clusters

    def _adjacency(self) -> dict[str, set[str]]:
        """Each object's neighbours through inbound or outbound connections."""
        adjacency: dict[str, set[str]] = {obj.key: set() for obj in self.app.objects}
        for obj in self.app.objects:
            if obj.connections:
                for conn in [*obj.connections.outbound, *obj.connections.inbound]:
                    adjacency[obj.key].add(conn.object)
        return adjacency

    def _cluster_members(
        self, seed: str, adjacency: dict[str, set[str]], processed: set[str]
    ) -> dict[str, None]:
        """The seed plus each unclustered object it connects to or shares
        CLUSTER_MIN_SHARED_NEIGHBORS neighbours with.

        dict, not set: members stay in app object order, so the emitted
        object/object_keys lists are stable across processes.
        """
        members: dict[str, None] = {seed: None}
        seed_neighbors = adjacency[seed]
        if len(seed_neighbors) < CLUSTER_MIN_SHARED_NEIGHBORS:
            return members
        for other in self.app.objects:
            if other.key == seed or other.key in processed:
                continue
            shared = seed_neighbors & adjacency[other.key]
            if (
                len(shared) >= CLUSTER_MIN_SHARED_NEIGHBORS
                or other.key in seed_neighbors
            ):
                members[other.key] = None
        return members

    def _cluster_stats(
        self, members: dict[str, None], adjacency: dict[str, set[str]]
    ) -> DependencyCluster:
        """Names, keys, connection counts and cohesion for one cluster."""
        internal = sum(
            1 for key in members for neighbor in adjacency[key] if neighbor in members
        )
        external = sum(
            1
            for key in members
            for neighbor in adjacency[key]
            if neighbor not in members
        )
        return {
            "objects": [
                self.objects_by_key[k].name for k in members if k in self.objects_by_key
            ],
            "object_keys": list(members),
            # Each internal connection is seen from both ends.
            "internal_connections": internal // 2,
            "external_connections": external,
            "cohesion": _cohesion(internal, internal + external),
        }

    def _analyze_data_patterns(self) -> DataPatterns:
        """Detect temporal and calculation patterns."""
        # Analyze temporal objects
        temporal_objects: list[TemporalObject] = []
        for obj in self.app.objects:
            has_created = any("created" in f.type.lower() for f in obj.fields)
            has_modified = any("modified" in f.type.lower() for f in obj.fields)
            has_status = any("status" in f.name.lower() for f in obj.fields)

            if has_created or has_modified or has_status:
                lifecycle = "stateful_entity" if has_status else "timestamped"
                temporal_objects.append(
                    {
                        "object": obj.name,
                        "object_key": obj.key,
                        "has_created_date": has_created,
                        "has_modified_date": has_modified,
                        "has_status_field": has_status,
                        "lifecycle_pattern": lifecycle,
                    }
                )

        # Calculate formula complexity
        total_formula_fields = 0
        objects_with_formulas = 0
        max_depth = 0

        for obj in self.app.objects:
            has_formula = False
            for field in obj.fields:
                if field.type in [
                    "equation",
                    "concatenation",
                    "count",
                    "sum",
                    "average",
                ]:
                    total_formula_fields += 1
                    has_formula = True
            if has_formula:
                objects_with_formulas += 1

        # Simplified depth calculation (would need recursive analysis for true depth)
        if total_formula_fields > 0:
            max_depth = min(3, total_formula_fields // 5 + 1)

        return {
            "temporal_objects": temporal_objects,
            "calculation_complexity": {
                "total_formula_fields": total_formula_fields,
                "objects_with_formulas": objects_with_formulas,
                "max_formula_chain_depth": max_depth,
                "interpretation": (
                    "High formula dependencies"
                    if total_formula_fields > FORMULA_FIELDS_HIGH
                    else "Moderate formula dependencies"
                    if total_formula_fields > FORMULA_FIELDS_MODERATE
                    else "Low formula dependencies"
                ),
            },
        }

    @cached_property
    def _security_report(self) -> SecurityReport:
        return generate_security_report(self.app)

    def _scene_depths(self) -> list[int]:
        """How many pages deep each scene sits: 1 for a top-level page.

        ``parent`` is a slug. Slugs repeat (a page can sit below a namesake),
        so the walk tracks scenes, not slugs: each step takes the first scene
        with the parent's slug that is not already on the path, and a loop
        ends when none is left. No scene is ever its own ancestor. A parent
        slug that no scene has still counts as a level.
        """
        by_slug: dict[str, list[Scene]] = {}
        for scene in self.app.scenes:
            by_slug.setdefault(scene.slug, []).append(scene)

        depths = []
        for scene in self.app.scenes:
            depth = 1
            on_path = {scene.key}
            current = scene
            while current.parent:
                candidates = by_slug.get(current.parent)
                if candidates is None:
                    depth += 1  # dangling parent
                    break
                ancestor = next((c for c in candidates if c.key not in on_path), None)
                if ancestor is None:
                    break  # the chain has looped back onto itself
                on_path.add(ancestor.key)
                depth += 1
                current = ancestor
            depths.append(depth)
        return depths

    def _analyze_ui_architecture(self) -> UiArchitecture:
        """Analyze scene and view patterns."""
        # Whether a page needs a login depends on its ancestors and on login
        # views, not only on its own `authenticated` flag; the security
        # report resolves that, so both commands give the same figures.
        security = self._security_report
        view_type_counts = {}
        for scene in self.app.scenes:
            for view in scene.views:
                view_type = view.type
                view_type_counts[view_type] = view_type_counts.get(view_type, 0) + 1

        depths = self._scene_depths()
        max_depth = max(depths, default=0)
        avg_depth = sum(depths) / len(depths) if depths else 0.0

        return {
            "scene_patterns": {
                "authenticated_scenes": security.login_required_scenes,
                "public_scenes": security.public_scenes,
                "total_scenes": len(self.app.scenes),
            },
            "view_patterns": view_type_counts,
            "navigation_depth": {
                "max_depth": max_depth,
                "avg_depth": round(avg_depth, 1),
                "interpretation": (
                    "High complexity"
                    if max_depth > HIERARCHY_DEPTH_HIGH
                    else "Moderate complexity"
                    if max_depth > HIERARCHY_DEPTH_MODERATE
                    else "Simple hierarchy"
                ),
            },
        }

    def _analyze_access_patterns(self) -> AccessPatterns:
        """Analyze authentication and access control patterns."""
        # User objects are identified by having a profile_key
        user_objects = [obj.name for obj in self.app.objects if obj.profile_key]

        # Pages limited to named roles, directly or through an ancestor.
        scenes_with_roles = sum(
            1
            for scene in self._security_report.scene_analyses
            if scene.allowed_profile_count
        )

        return {
            "authentication_model": "user_based" if user_objects else "public",
            "user_objects": user_objects,
            "role_usage": {
                "scenes_with_role_restrictions": scenes_with_roles,
                "interpretation": (
                    "Role-based access control in use"
                    if scenes_with_roles > 0
                    else "No role restrictions detected"
                ),
            },
        }

    def _analyze_technical_debt(self, model: "KnackSleuth") -> TechnicalDebt:
        """Identify orphaned resources and complexity hotspots.

        Orphans come from this app as it is; bottlenecks and fan-out come
        from ``model``, the view the relationship analysis uses.
        """
        orphaned_fields = len(self.find_orphaned_fields())

        orphaned_objects = self.find_orphaned_objects()
        orphaned_objects_count = len(orphaned_objects)
        orphaned_objects_list: list[OrphanedObject] = [
            {"name": obj.name, "object_key": obj.key} for obj in orphaned_objects
        ]

        # Identify bottleneck objects
        bottlenecks: list[NamedObject] = []
        high_fanout: list[NamedObject] = []

        for obj in model.app.objects:
            if obj.connections:
                inbound = len(obj.connections.inbound)
                outbound = len(obj.connections.outbound)

                if inbound >= BOTTLENECK_MIN_INBOUND:
                    bottlenecks.append({"object": obj.name, "object_key": obj.key})
                if outbound >= HIGH_FANOUT_MIN_OUTBOUND:
                    high_fanout.append({"object": obj.name, "object_key": obj.key})

        return {
            "orphaned_fields": orphaned_fields,
            "orphaned_objects": orphaned_objects_count,
            "orphaned_objects_list": orphaned_objects_list,
            # Page-layout debt: views Knack never draws, layout slots pointing
            # at views that are not there, and rules aimed at either.
            "orphaned_views": len(self.find_orphaned_views()),
            "dangling_layout_keys": len(self.find_dangling_layout_keys()),
            "stale_view_rule_references": len(self.find_stale_view_rule_references()),
            "high_fan_out_objects": high_fanout,
            "bottleneck_objects": bottlenecks,
            "interpretation": (
                "High refactoring risk - multiple bottleneck objects"
                if len(bottlenecks) > HIGH_RISK_BOTTLENECK_COUNT
                else "Some complexity hotspots"
                if len(bottlenecks) > 0 or len(high_fanout) > 0
                else "Low technical debt"
            ),
        }

    def _analyze_extensibility(self) -> Extensibility:
        """Assess how easy it is to extend or modify the application."""
        # Calculate modularity based on clusters
        clusters = self._identify_clusters()
        total_objects = len(self.app.objects)
        objects_in_clusters = sum(len(c["object_keys"]) for c in clusters)

        modularity_score = (
            objects_in_clusters / total_objects if total_objects > 0 else 0.0
        )

        # Identify tight coupling
        tight_coupling: list[CouplingPair] = []
        for obj in self.app.objects:
            if obj.connections:
                for conn in obj.connections.outbound:
                    target = self.objects_by_key.get(conn.object)
                    if target:
                        # Check if they have many shared connections
                        obj_connections = {c.object for c in obj.connections.outbound}
                        # The old inline filter ran after the iterable was
                        # built, so a target without connections crashed.
                        target_connections = (
                            {c.object for c in target.connections.outbound}
                            if target.connections
                            else set()
                        )
                        shared = obj_connections & target_connections

                        if len(shared) >= TIGHT_COUPLING_MIN_SHARED:
                            tight_coupling.append(
                                {
                                    "obj1": obj.name,
                                    "obj1_key": obj.key,
                                    "connection_field": conn.name,  # Field name that creates the coupling
                                    "obj2": target.name,
                                    "obj2_key": target.key,
                                    "shared_connections_count": len(shared),
                                    "coupling": "high",
                                }
                            )

        # Determine architectural style
        hub_count = sum(
            1
            for obj in self.app.objects
            if obj.connections
            and (len(obj.connections.inbound) + len(obj.connections.outbound))
            >= CORE_HUB_MIN_CONNECTIONS
        )

        if hub_count > 0 and modularity_score < HUB_AND_SPOKE_MAX_MODULARITY:
            arch_style = "hub_and_spoke"
        elif modularity_score > MODULAR_MIN_MODULARITY:
            arch_style = "modular"
        else:
            arch_style = "mixed"

        # Sort by shared connections count (most coupled first)
        tight_coupling.sort(key=lambda x: x["shared_connections_count"], reverse=True)

        return {
            "modularity_score": round(modularity_score, 2),
            "tight_coupling_pairs": tight_coupling[:5],  # Top 5 most coupled
            "architectural_style": arch_style,
            "interpretation": (
                "Highly modular - easy to extend"
                if modularity_score > MODULARITY_HIGH
                else "Moderately modular - some refactoring may help"
                if modularity_score > MODULARITY_MEDIUM
                else "Low modularity - changes may have wide impact"
            ),
        }
