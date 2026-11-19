"""Markdown renderings of impact-analysis and app-summary results."""

from collections.abc import Callable, Iterable
from typing import Any

from knack_sleuth.app_summary_report import (
    AccessPatterns,
    ApplicationSummary,
    AppSummary,
    DataPatterns,
    DomainModel,
    Extensibility,
    RelationshipMap,
    TechnicalDebt,
    UiArchitecture,
)
from knack_sleuth.impact_report import (
    CascadeImpacts,
    DirectImpacts,
    FormImpact,
    FormulaImpact,
    ImpactAnalysis,
    SceneImpact,
    ViewImpact,
)


def _section(
    heading: str,
    items: list,
    render: Callable[[Any], str | None],
    empty: str,
) -> list[str]:
    """A '### heading (n)' block with one bullet per item, or an italic note."""
    lines = [f"### {heading} ({len(items)})"]
    lines.extend(line for item in items if (line := render(item)) is not None)
    if not items:
        lines.append(f"*{empty}*")
    return lines


# --- impact-analysis ------------------------------------------------------------


def _impact_header(analysis: ImpactAnalysis) -> list[str]:
    target = analysis["target"]
    risk = analysis["risk_assessment"]
    return [
        f"# Impact Analysis: {target['name']}",
        "",
        f"**Type:** {target['type']}  ",
        f"**Key:** `{target['key']}`  ",
        f"**Description:** {target['description']}  ",
        "",
        "## Risk Assessment",
        "",
        f"- **Breaking Change Likelihood:** {risk['breaking_change_likelihood']}",
        f"- **Impact Score:** {risk['impact_score']}",
        f"- **Affected Workflows:** {', '.join(risk['affected_user_workflows']) or 'None'}",
        "",
    ]


def _direct_impacts(direct: DirectImpacts) -> list[str]:
    return [
        "## Direct Impacts",
        "",
        *_section(
            "Connections",
            direct["connections"],
            lambda c: f"- {c['description']}",
            "No connection impacts",
        ),
        "",
        *_section(
            "Views",
            direct["views"],
            lambda v: (
                f"- **{v['view_name']}** (`{v['view_key']}`) - {v['view_type']} "
                f"in scene {v['scene_name']}{_orphan_note(v)}"
            ),
            "No view impacts",
        ),
        "",
        *_section(
            "Forms",
            direct["forms"],
            lambda f: f"- **{f['view_name']}** (`{f['view_key']}`){_orphan_note(f)}",
            "No form impacts",
        ),
        "",
        *_section(
            "Formulas",
            direct["formulas"],
            _formula_line,
            "No formula impacts",
        ),
        "",
        *_section(
            "Rules",
            direct.get("rules", []),
            lambda r: f"- {r['description']}",
            "No rule, validation, task or page rule impacts",
        ),
    ]


def _orphan_note(impact: ViewImpact | FormImpact) -> str:
    return " *(on no page; not scored)*" if impact["orphaned_view"] else ""


def _formula_line(formula: FormulaImpact) -> str:
    head = f"- **{formula['field_name']}** (`{formula['field_key']}`)"
    if formula["equation"] is None:
        return f"{head}: its settings name the target"
    return f"{head}: `{formula['equation']}`"


def _cascade_impacts(
    cascade: CascadeImpacts, scenes_by_key: dict[str, SceneImpact]
) -> list[str]:
    def render_scene(scene_key: str) -> str | None:
        scene = scenes_by_key.get(scene_key)
        if not scene:
            return None
        return f"- **{scene['scene_name']}** (`{scene_key}`) - /{scene['scene_slug']}"

    return [
        "",
        "## Cascade Impacts",
        "",
        *_section(
            "Affected Fields",
            cascade["affected_fields"],
            lambda f: (
                f"- **{f['field_name']}** (`{f['field_key']}`) - {f['field_type']} "
                f"- {f['usage_count']} usages"
            ),
            "No field cascade impacts",
        ),
        "",
        *_section(
            "Affected Objects",
            cascade.get("affected_objects", []),
            lambda key: f"- `{key}`",
            "No other objects depend on it",
        ),
        "",
        *_section(
            "Affected Scenes",
            cascade["affected_scenes"],
            render_scene,
            "No scene cascade impacts",
        ),
    ]


def _builder_pages(
    scene_keys: Iterable[str],
    scenes_by_key: dict[str, SceneImpact],
    scene_url: Callable[[str], str],
) -> list[str]:
    scene_keys = sorted(set(scene_keys))
    if not scene_keys:
        return []
    lines = [
        "",
        "## Builder Pages to Review",
        "",
        f"**{len(scene_keys)} scenes affected**",
        "",
    ]
    for scene_key in scene_keys:
        name = scenes_by_key.get(scene_key, {}).get("scene_name", scene_key)
        lines.append(f"- [{name}]({scene_url(scene_key)})")
    return lines


def impact_markdown(analysis: ImpactAnalysis, scene_url: Callable[[str], str]) -> str:
    """Render an impact analysis; scene_url maps a scene key to a builder link."""
    direct = analysis["direct_impacts"]
    cascade = analysis["cascade_impacts"]
    # First entry wins, as with a linear search.
    scenes_by_key: dict[str, SceneImpact] = {}
    for scene in direct["scenes"]:
        scenes_by_key.setdefault(scene["scene_key"], scene)
    metadata = analysis["metadata"]
    return "\n".join(
        [
            *_impact_header(analysis),
            *_direct_impacts(direct),
            *_cascade_impacts(cascade, scenes_by_key),
            "",
            "## Summary",
            "",
            f"- **Total Direct Impacts:** {metadata['total_direct_impacts']}",
            f"- **Total Cascade Impacts:** {metadata['total_cascade_impacts']}",
            *_builder_pages(cascade["affected_scenes"], scenes_by_key, scene_url),
        ]
    )


# --- app-summary ----------------------------------------------------------------


def _summary_header(app_info: ApplicationSummary) -> list[str]:
    metrics = app_info["complexity_metrics"]
    return [
        f"# Application Architecture Summary: {app_info['name']}",
        "",
        f"**Application ID:** `{app_info['id']}`",
        "",
        "## Complexity Metrics",
        "",
        f"- **Objects:** {metrics['total_objects']}",
        f"- **Fields:** {metrics['total_fields']}",
        f"- **Scenes:** {metrics['total_scenes']}",
        f"- **Views:** {metrics['total_views']}",
        f"- **Records:** {metrics['total_records']:,}",
        f"- **Connection Density:** {metrics['connection_density']}",
        "",
    ]


def _domain_model(domain: DomainModel) -> list[str]:
    lines = [
        "## Domain Model",
        "",
        f"### Core Entities ({len(domain['core_entities'])})",
    ]
    lines.extend(
        f"- **{e['name']}** (`{e['object_key']}`) - "
        f"Importance: {e.get('importance_score', 0):.2f}, "
        f"Centrality: {e['centrality_score']}, Records: {e['record_count']:,}"
        for e in domain["core_entities"]
    )
    transactional = domain["transactional_entities"]
    lines += ["", f"### Transactional Entities ({len(transactional)}) - top 5 shown"]
    lines.extend(
        f"- **{e['name']}** - {e['record_count']:,} records" for e in transactional[:5]
    )
    reference = domain["reference_data"]
    lines += ["", f"### Reference Data ({len(reference)}) - top 5 shown"]
    lines.extend(
        f"- **{e['name']}** - Used by {len(e.get('used_by', []))} objects"
        for e in reference[:5]
    )
    # The two remaining buckets, so every object is counted somewhere here.
    for title, entities in (
        ("Supporting Entities", domain["supporting_entities"]),
        ("User Profiles", domain["user_profiles"]),
    ):
        lines += ["", f"### {title} ({len(entities)}) - top 5 shown"]
        lines.extend(
            f"- **{e['name']}** - {e['record_count']:,} records" for e in entities[:5]
        )
    return lines


def _relationships(relationships: RelationshipMap) -> list[str]:
    hubs = relationships["hub_objects"]
    clusters = relationships["dependency_clusters"]
    lines = [
        "",
        "## Relationship Topology",
        "",
        f"**Total Connections:** {relationships['connection_graph']['total_connections']}",
        "",
        f"### Hub Objects ({len(hubs)}) - top 5 shown",
    ]
    for hub in hubs[:5]:
        lines.append(
            f"- **{hub['object']}** - {hub['total_connections']} connections "
            f"({hub['inbound_connections']} in, {hub['outbound_connections']} out)"
        )
        lines.append(f"  - _{hub['interpretation']}_")
    lines += ["", f"### Dependency Clusters ({len(clusters)})"]
    lines.extend(
        f"- {', '.join(c['objects'])} ({c['cohesion']} cohesion)" for c in clusters[:3]
    )
    return lines


def _patterns_and_ui(patterns: DataPatterns, ui: UiArchitecture) -> list[str]:
    calc = patterns["calculation_complexity"]
    nav = ui["navigation_depth"]
    return [
        "",
        "## Data Patterns",
        "",
        "### Calculation Complexity",
        f"- Formula fields: {calc['total_formula_fields']}",
        f"- Objects with formulas: {calc['objects_with_formulas']}",
        f"- Max chain depth: {calc['max_formula_chain_depth']}",
        f"- Assessment: {calc['interpretation']}",
        "",
        "## UI Architecture",
        "",
        f"- Authenticated scenes: {ui['scene_patterns']['authenticated_scenes']}",
        f"- Public scenes: {ui['scene_patterns']['public_scenes']}",
        f"- Navigation depth: {nav['max_depth']} (max), {nav['avg_depth']} (avg)",
        f"- Complexity: {nav['interpretation']}",
        "",
        "### View Types",
        *(
            f"- {view_type}: {count}"
            for view_type, count in sorted(
                ui["view_patterns"].items(), key=lambda x: x[1], reverse=True
            )
        ),
    ]


def _access_debt_extensibility(
    access: AccessPatterns, debt: TechnicalDebt, ext: Extensibility
) -> list[str]:
    user_objects = (
        ", ".join(access["user_objects"]) if access["user_objects"] else "None"
    )
    return [
        "",
        "## Access Patterns",
        "",
        f"- Authentication model: {access['authentication_model']}",
        f"- User objects: {user_objects}",
        f"- Role-restricted scenes: {access['role_usage']['scenes_with_role_restrictions']}",
        "",
        "## Technical Debt",
        "",
        f"- Orphaned fields: {debt['orphaned_fields']}",
        f"- Orphaned objects: {debt['orphaned_objects']}",
        f"- Orphaned views: {debt['orphaned_views']}",
        f"- Dangling layout keys: {debt['dangling_layout_keys']}",
        f"- Stale view rule references: {debt['stale_view_rule_references']}",
        f"- Bottleneck objects: {len(debt['bottleneck_objects'])}",
        f"- High fan-out objects: {len(debt['high_fan_out_objects'])}",
        f"- Assessment: {debt['interpretation']}",
        "",
        "## Extensibility",
        "",
        f"- Modularity score: {ext['modularity_score']}",
        f"- Architectural style: {ext['architectural_style']}",
        f"- Assessment: {ext['interpretation']}",
        f"- Tight coupling pairs: {len(ext['tight_coupling_pairs'])}",
    ]


def app_summary_markdown(summary: AppSummary) -> str:
    return "\n".join(
        [
            *_summary_header(summary["application"]),
            *_domain_model(summary["domain_model"]),
            *_relationships(summary["relationship_map"]),
            *_patterns_and_ui(summary["data_patterns"], summary["ui_architecture"]),
            *_access_debt_extensibility(
                summary["access_patterns"],
                summary["technical_debt_indicators"],
                summary["extensibility_assessment"],
            ),
        ]
    )
