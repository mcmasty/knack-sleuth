"""The shape of the report ``KnackSleuth.generate_impact_analysis`` returns.

TypedDicts: plain dicts at run time (the report is dumped straight to JSON),
with their keys and value types visible to the type checker.
"""

from typing import Any, NotRequired, TypedDict


class ImpactTarget(TypedDict):
    key: str
    type: str  # "object" or "field"
    name: str | None
    description: str | None


class ConnectionImpact(TypedDict):
    type: str
    description: str
    # An object's impact names the other end as source_object; a field's
    # names it as target_object.
    source_object: NotRequired[Any]
    connection_field: NotRequired[Any]
    target_object: NotRequired[Any]


class ViewImpact(TypedDict):
    view_key: Any
    view_name: Any
    view_type: Any
    scene_key: Any
    scene_name: Any
    # On a view no page shows: listed, but not counted in the score.
    orphaned_view: bool


class SceneImpact(TypedDict):
    scene_key: str
    scene_name: str
    scene_slug: str


class FormulaImpact(TypedDict):
    """A computed field that depends on the target."""

    field_key: Any
    field_name: Any
    object_key: Any
    equation: Any  # None for a sum, count or similar field


class FormImpact(TypedDict):
    view_key: Any
    view_name: Any
    scene_key: Any
    orphaned_view: bool


class RuleImpact(TypedDict):
    """A rule, validation, task or page rule that names the target."""

    type: str
    description: str
    object_key: Any
    scene_key: Any
    reference_path: Any


class DirectImpacts(TypedDict):
    connections: list[ConnectionImpact]
    views: list[ViewImpact]
    scenes: list[SceneImpact]
    formulas: list[FormulaImpact]
    forms: list[FormImpact]
    rules: list[RuleImpact]


class FieldUsage(TypedDict):
    type: str
    context: str


class AffectedField(TypedDict):
    """One field of the target object, and where it is used."""

    field_key: str
    field_name: str
    field_type: str
    usage_count: int
    usages: list[FieldUsage]


class CascadeImpacts(TypedDict):
    affected_fields: list[AffectedField]
    affected_objects: list[str]
    affected_scenes: list[str]


class RiskAssessment(TypedDict):
    breaking_change_likelihood: str  # none, low, medium, high (unknown on error)
    impact_score: int
    affected_user_workflows: list[str]


class ImpactTotals(TypedDict):
    total_direct_impacts: int
    total_cascade_impacts: int


class ImpactAnalysis(TypedDict):
    target: ImpactTarget
    direct_impacts: DirectImpacts
    cascade_impacts: CascadeImpacts
    risk_assessment: RiskAssessment
    metadata: ImpactTotals
    # Set when the target cannot be analysed: an unknown key, or a target
    # type that is neither object nor field. Every list is then empty.
    error: NotRequired[str]
