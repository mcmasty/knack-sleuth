from typing import Any, Literal

from pydantic import BaseModel, field_validator
from pydantic import Field as PydanticField


# ============================================================================
# Field Models
# ============================================================================


class FieldFormat(BaseModel):
    """Format configuration for a field."""

    model_config = {"extra": "allow"}  # Allow additional format properties


class FieldRelationship(BaseModel):
    """Connection relationship configuration."""

    has: str  # "one" or "many"
    object: str  # Target object key (e.g., "object_11")
    belongs_to: str  # "one" or "many"


class KnackField(BaseModel):
    """Represents a field in a Knack object."""

    key: str  # Unique field identifier (e.g., "field_4")
    name: str
    type: str  # Field type (e.g., "name", "email", "connection", "concatenation")
    required: bool = False
    unique: bool = False
    user: bool = False
    conditional: bool = False
    rules: list[Any] = PydanticField(default_factory=list)
    validation: list[Any] = PydanticField(default_factory=list)
    isSystemField: bool = PydanticField(default=False, alias="isSystemField")
    code: str = ""
    format: FieldFormat | None = None
    relationship: FieldRelationship | None = None  # For connection fields
    immutable: bool | None = None

    model_config = {"populate_by_name": True, "extra": "allow"}


# ============================================================================
# Object Models
# ============================================================================


class Inflections(BaseModel):
    """Singular and plural forms of an object/field name."""

    singular: str
    plural: str


class ConnectionField(BaseModel):
    """Metadata about the connected field."""

    name: str
    inflections: Inflections | None = None


class Connection(BaseModel):
    """Represents a connection between objects."""

    has: str  # "one" or "many"
    key: str  # Field key for this connection
    name: str
    field: ConnectionField
    object: str  # Target object key
    belongs_to: str  # "one" or "many"


class Connections(BaseModel):
    """Inbound and outbound connections for an object."""

    inbound: list[Connection] = PydanticField(default_factory=list)
    outbound: list[Connection] = PydanticField(default_factory=list)


class ObjectSort(BaseModel):
    """Default sort configuration for an object."""

    field: str  # Field key to sort by
    order: Literal["asc", "desc"]


class KnackObject(BaseModel):
    """Represents a data object (table) in Knack."""

    key: str  # Unique object identifier (e.g., "object_2")
    name: str
    inflections: Inflections | None = None
    connections: Connections | None = None
    fields: list[KnackField] = PydanticField(default_factory=list)
    sort: ObjectSort | None = None
    user: bool = False
    status: str | None = None
    type: str | None = None  # e.g., "UserObject"
    identifier: str | None = None  # Key of the field used as identifier
    profile_key: str | None = None
    tasks: list[Any] = PydanticField(default_factory=list)

    model_config = {"extra": "allow"}


# ============================================================================
# View Models
# ============================================================================


class ViewColumn(BaseModel):
    """Column configuration in a table view."""

    type: str | None = None  # "field" or "link" - can be null
    field: dict[str, str] | None = None  # {"key": "field_110"}
    header: str | None = None
    scene: str | None = None  # For link columns

    model_config = {"extra": "allow"}


class ViewLink(BaseModel):
    """Link configuration in a menu view."""

    name: str
    type: str  # "scene"
    scene: str | None = None  # Scene slug/key

    model_config = {"extra": "allow"}


class ViewSourceCriteria(BaseModel):
    """Filter criteria for a view's data source."""

    match: str  # "all" or "any"
    rules: list[Any] = PydanticField(default_factory=list)
    groups: list[Any] = PydanticField(default_factory=list)


class ViewSourceSort(BaseModel):
    """Sort configuration for a view's data source."""

    field: str  # Field key
    order: Literal["asc", "desc"]


class ParentSource(BaseModel):
    """Parent connection information for a view source."""

    object: str  # Object key
    connection: str  # Field key


class ViewSource(BaseModel):
    """Data source configuration for a view."""

    object: str  # Object key that this view displays
    sort: list[ViewSourceSort] | None = None
    limit: int | str | None = None  # Can be int, empty string, or null
    criteria: ViewSourceCriteria | None = None
    parent_source: ParentSource | None = None
    connection_key: str | None = None
    relationship_type: str | None = None  # "foreign"
    authenticated_user: bool | None = None

    model_config = {"extra": "allow"}
    
    @field_validator('criteria', mode='before')
    @classmethod
    def convert_empty_list_to_none(cls, v):
        """Convert empty list to None for criteria field."""
        if isinstance(v, list) and len(v) == 0:
            return None
        return v


class View(BaseModel):
    """Represents a view in a Knack scene."""

    key: str  # Unique view identifier (e.g., "view_4")
    name: str
    type: str  # View type (e.g., "menu", "table", "form", "details")
    title: str | None = None
    source: ViewSource | None = None  # Data source (for data views)
    columns: list[ViewColumn] = PydanticField(default_factory=list)  # For table views
    links: list[ViewLink] = PydanticField(default_factory=list)  # For menu views
    inputs: list[Any] = PydanticField(default_factory=list)  # For form views

    model_config = {"extra": "allow"}


# ============================================================================
# Scene Models
# ============================================================================


class Scene(BaseModel):
    """Represents a scene (page) in a Knack application."""

    key: str  # Unique scene identifier (e.g., "scene_46")
    name: str
    slug: str
    type: str | None = None  # Scene type (e.g., "menu", "page") - can be null
    views: list[View] = PydanticField(default_factory=list)
    parent: str | None = None  # Parent scene key
    menu_pages: list[str] | None = None  # Child scene keys (for menu scenes), can be null
    authenticated: bool = False
    groups: list[Any] = PydanticField(default_factory=list)

    model_config = {"extra": "allow"}


# ============================================================================
# Application Models
# ============================================================================


class HomeScene(BaseModel):
    """Reference to the application's home scene."""

    key: str  # Scene key
    slug: str


class Application(BaseModel):
    """Represents a Knack application's metadata."""

    name: str
    slug: str
    description: str = ""
    id: str
    home_scene: HomeScene
    account: dict[str, Any] = PydanticField(default_factory=dict)  # Account info including builder slug
    objects: list[KnackObject] = PydanticField(default_factory=list)
    scenes: list[Scene] = PydanticField(default_factory=list)
    counts: dict[str, int] = PydanticField(default_factory=dict)  # Record counts per object
    settings: dict[str, Any] = PydanticField(default_factory=dict)
    design: dict[str, Any] = PydanticField(default_factory=dict)

    model_config = {"extra": "allow"}


class KnackAppMetadata(BaseModel):
    """Root model for a Knack application export JSON."""

    application: Application


# ============================================================================
# Security Analysis Models
# ============================================================================


class SceneSecurity(BaseModel):
    """Security analysis for a single scene."""

    root_nav: str  # Top-level navigation (Menu name, Login Page name, "Utility Page", or "Direct")
    scene_name: str
    nav_level: str  # "Menu", "Top-Level", or "Child"
    allowed_profile_count: int
    allowed_profiles: list[str]  # List of profile names that have access
    page_nav: str  # Full navigation path (e.g., "Menu > Parent > Child")
    scene_key: str
    scene_slug: str
    scene_type: str
    security_concern: str  # Description of issues or "OK"
    requires_login: bool  # Whether login is actually required (considering inheritance)
    inherits_security: bool  # Whether security is inherited from parent
    child_count: int | None = None  # Only populated in summary mode
    view_names: list[str] = PydanticField(default_factory=list)  # All view names on this scene
    view_keys: list[str] = PydanticField(default_factory=list)  # All view keys on this scene


class SecurityReport(BaseModel):
    """Complete security analysis report for an application."""

    app_name: str
    total_scenes: int
    public_scenes: int
    login_required_scenes: int
    unrestricted_authenticated_scenes: int
    scenes_with_parents: int
    scenes_inheriting_security: int
    menu_scenes: int
    utility_pages: int
    total_profiles: int
    profiles: dict[str, str]  # profile_key -> profile_name
    profile_access_counts: dict[str, int]  # profile_name -> scene_count
    scene_analyses: list[SceneSecurity]
