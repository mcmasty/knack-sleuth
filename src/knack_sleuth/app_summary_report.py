"""The shape of the report ``KnackSleuth.generate_app_summary`` returns.

TypedDicts: plain dicts at run time (the report is dumped straight to JSON),
with their keys and value types visible to the type checker.
"""

from typing import NotRequired, TypedDict


class ComplexityMetrics(TypedDict):
    total_objects: int
    total_fields: int
    total_scenes: int
    total_views: int
    total_records: int
    connection_density: float


class ApplicationSummary(TypedDict):
    name: str
    id: str
    complexity_metrics: ComplexityMetrics


class EntitySummary(TypedDict):
    """One object in the domain model."""

    object_key: str
    name: str
    record_count: int
    field_count: int
    centrality_score: float
    field_types: dict[str, int]
    total_connections: int
    is_core_entity: bool
    primary_role: str
    # Names of the objects that use this one as reference data.
    used_by: NotRequired[list[str]]
    # Set on the non-user objects, which are ranked against each other.
    importance_score: NotRequired[float]


class DomainModel(TypedDict):
    user_profiles: list[EntitySummary]
    core_entities: list[EntitySummary]
    transactional_entities: list[EntitySummary]
    reference_data: list[EntitySummary]
    # Everything else: low record count and low connectivity.
    supporting_entities: list[EntitySummary]


# "from" is a Python keyword, so this one cannot use the class syntax.
ConnectionEdge = TypedDict(
    "ConnectionEdge",
    {
        "from": str,
        "from_name": str,
        "to": str,
        "to_name": str,
        "via": str,
        "connection_name": str,
        "type": str,
    },
)


class ConnectionGraph(TypedDict):
    nodes: list[str]
    edges: list[ConnectionEdge]
    total_connections: int


class HubObject(TypedDict):
    object: str
    object_key: str
    inbound_connections: int
    outbound_connections: int
    total_connections: int
    interpretation: str


class DependencyCluster(TypedDict):
    objects: list[str]
    object_keys: list[str]
    internal_connections: int
    external_connections: int
    cohesion: str


class RelationshipMap(TypedDict):
    connection_graph: ConnectionGraph
    hub_objects: list[HubObject]
    dependency_clusters: list[DependencyCluster]


class TemporalObject(TypedDict):
    object: str
    object_key: str
    has_created_date: bool
    has_modified_date: bool
    has_status_field: bool
    lifecycle_pattern: str


class CalculationComplexity(TypedDict):
    total_formula_fields: int
    objects_with_formulas: int
    max_formula_chain_depth: int
    interpretation: str


class DataPatterns(TypedDict):
    temporal_objects: list[TemporalObject]
    calculation_complexity: CalculationComplexity


class ScenePatterns(TypedDict):
    authenticated_scenes: int
    public_scenes: int
    total_scenes: int


class NavigationDepth(TypedDict):
    max_depth: int
    avg_depth: float
    interpretation: str


class UiArchitecture(TypedDict):
    scene_patterns: ScenePatterns
    view_patterns: dict[str, int]  # view type -> how many
    navigation_depth: NavigationDepth


class RoleUsage(TypedDict):
    scenes_with_role_restrictions: int
    interpretation: str


class AccessPatterns(TypedDict):
    authentication_model: str
    user_objects: list[str]
    role_usage: RoleUsage


class NamedObject(TypedDict):
    object: str
    object_key: str


class OrphanedObject(TypedDict):
    name: str
    object_key: str


class TechnicalDebt(TypedDict):
    orphaned_fields: int
    orphaned_objects: int
    orphaned_objects_list: list[OrphanedObject]
    orphaned_views: int
    dangling_layout_keys: int
    stale_view_rule_references: int
    high_fan_out_objects: list[NamedObject]
    bottleneck_objects: list[NamedObject]
    interpretation: str


class CouplingPair(TypedDict):
    obj1: str
    obj1_key: str
    connection_field: str
    obj2: str
    obj2_key: str
    shared_connections_count: int
    coupling: str


class Extensibility(TypedDict):
    modularity_score: float
    tight_coupling_pairs: list[CouplingPair]
    architectural_style: str
    interpretation: str


class AppSummary(TypedDict):
    application: ApplicationSummary
    domain_model: DomainModel
    relationship_map: RelationshipMap
    data_patterns: DataPatterns
    ui_architecture: UiArchitecture
    access_patterns: AccessPatterns
    technical_debt_indicators: TechnicalDebt
    extensibility_assessment: Extensibility
