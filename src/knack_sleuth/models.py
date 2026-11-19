from typing import Any, ClassVar, Literal

from pydantic import BaseModel, field_validator, model_validator
from pydantic import Field as PydanticField


class _KnackModel(BaseModel):
    """Base for models of Knack's metadata, which writes null where a value
    is simply absent.

    A null in a field that has a default takes the default. A null display
    name, slug or inflection falls back to the record's key (or ""), so one unnamed view
    doesn't stop every command. Keys, types and connection targets stay
    required: without them the analyses would be wrong, not just less tidy.
    """

    _NAME_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"name", "slug", "singular", "plural"}
    )

    @model_validator(mode="before")
    @classmethod
    def _null_means_absent(cls, data: Any) -> Any:
        if not isinstance(data, dict) or None not in data.values():
            return data
        data = dict(data)
        for name, info in cls.model_fields.items():
            alias = info.alias or name
            if alias not in data or data[alias] is not None:
                continue
            if not info.is_required():
                del data[alias]
            elif name in cls._NAME_FIELDS:
                data[alias] = data.get("key") or ""
        return data


# ============================================================================
# Field Models
# ============================================================================


class FieldFormat(_KnackModel):
    """Format configuration for a field."""

    model_config = {"extra": "allow"}  # Allow additional format properties


class FieldRelationship(_KnackModel):
    """Connection relationship configuration."""

    has: str  # "one" or "many"
    object: str  # Target object key (e.g., "object_11")
    belongs_to: str  # "one" or "many"


class KnackField(_KnackModel):
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

    @field_validator("format", mode="before")
    @classmethod
    def convert_empty_format_to_none(cls, v):
        """Convert Knack's empty-string format to None.

        Knack emits `"format": ""` rather than omitting the key when a field
        has no format configuration, which fails validation against
        FieldFormat. Seen in bulk on spreadsheet-style imported objects.
        """
        if v == "":
            return None
        return v


# ============================================================================
# Object Models
# ============================================================================


class Inflections(_KnackModel):
    """Singular and plural forms of an object/field name."""

    singular: str
    plural: str


class ConnectionField(_KnackModel):
    """Metadata about the connected field."""

    name: str
    inflections: Inflections | None = None


class Connection(_KnackModel):
    """Represents a connection between objects."""

    has: str  # "one" or "many"
    key: str  # Field key for this connection
    name: str
    field: ConnectionField
    object: str  # Target object key
    belongs_to: str  # "one" or "many"

    def relationship_type(self, *, from_connected: bool = False) -> str:
        """Cardinality from the connecting object to the connected one.

        `has` is how many connected records each connecting record holds and
        `belongs_to` how many connecting records each connected record can
        belong to, so Events.Client with has=one, belongs_to=many is
        "many-to-one": many Events, one Client. Real records confirm it.
        Inbound entries carry the connecting object's values too, so an
        object listing its inbound connections passes from_connected=True.
        Unexpected values count as "many".
        """
        near, far = (
            "one" if side == "one" else "many" for side in (self.belongs_to, self.has)
        )
        if from_connected:
            near, far = far, near
        return f"{near}-to-{far}"


class Connections(_KnackModel):
    """Inbound and outbound connections for an object."""

    inbound: list[Connection] = PydanticField(default_factory=list)
    outbound: list[Connection] = PydanticField(default_factory=list)


class ObjectSort(_KnackModel):
    """Default sort configuration for an object."""

    field: str  # Field key to sort by
    order: Literal["asc", "desc"]


class KnackObject(_KnackModel):
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


class ViewColumn(_KnackModel):
    """Column configuration in a table view."""

    type: str | None = None  # "field" or "link" - can be null
    field: dict[str, str] | None = None  # {"key": "field_110"}
    header: str | None = None
    scene: str | None = None  # For link columns

    model_config = {"extra": "allow"}


class ViewLink(_KnackModel):
    """Link configuration in a menu view."""

    name: str
    type: str  # "scene"
    scene: str | None = None  # Scene slug/key

    model_config = {"extra": "allow"}


# Orphan detection walks the serialized view rather than a hand-maintained list
# of schemas, so these submodels must keep unknown keys: pydantic's default
# would drop them before the walk, and a field referenced only in a key Knack
# added later would look orphaned.


class ViewSourceCriteria(_KnackModel):
    """Filter criteria for a view's data source."""

    match: str  # "all" or "any"
    rules: list[Any] = PydanticField(default_factory=list)
    groups: list[Any] = PydanticField(default_factory=list)

    model_config = {"extra": "allow"}


class ViewSourceSort(_KnackModel):
    """Sort configuration for a view's data source."""

    field: str  # Field key
    order: Literal["asc", "desc"]

    model_config = {"extra": "allow"}


class ParentSource(_KnackModel):
    """Parent connection information for a view source."""

    object: str  # Object key
    connection: str  # Field key

    model_config = {"extra": "allow"}


class ViewSource(_KnackModel):
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

    @field_validator("criteria", mode="before")
    @classmethod
    def convert_empty_list_to_none(cls, v):
        """Convert empty list to None for criteria field."""
        if isinstance(v, list) and len(v) == 0:
            return None
        return v


class View(_KnackModel):
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


class Scene(_KnackModel):
    """Represents a scene (page) in a Knack application."""

    key: str  # Unique scene identifier (e.g., "scene_46")
    name: str
    slug: str
    type: str | None = None  # Scene type (e.g., "menu", "page") - can be null
    views: list[View] = PydanticField(default_factory=list)
    parent: str | None = None  # Parent scene key
    menu_pages: list[str] | None = (
        None  # Child scene keys (for menu scenes), can be null
    )
    authenticated: bool | None = None
    groups: list[Any] = PydanticField(default_factory=list)

    model_config = {"extra": "allow"}


# ============================================================================
# Application Models
# ============================================================================


class HomeScene(_KnackModel):
    """Reference to the application's home scene."""

    key: str  # Scene key
    slug: str


class Application(_KnackModel):
    """Represents a Knack application's metadata."""

    name: str
    slug: str
    description: str = ""
    id: str
    home_scene: HomeScene
    account: dict[str, Any] = PydanticField(
        default_factory=dict
    )  # Account info including builder slug
    objects: list[KnackObject] = PydanticField(default_factory=list)
    scenes: list[Scene] = PydanticField(default_factory=list)
    counts: dict[str, int] = PydanticField(
        default_factory=dict
    )  # Record counts per object
    settings: dict[str, Any] = PydanticField(default_factory=dict)
    design: dict[str, Any] = PydanticField(default_factory=dict)

    model_config = {"extra": "allow"}

    @field_validator("counts", mode="before")
    @classmethod
    def drop_null_counts(cls, v: Any) -> Any:
        """An object whose count is null has no count, as if it were missing."""
        if isinstance(v, dict):
            return {key: count for key, count in v.items() if count is not None}
        return v


class KnackAppMetadata(_KnackModel):
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
    # Keys of every scene above this one: its parents by slug (all scenes that
    # share a duplicate slug) and the menu the chain hangs from.
    ancestor_keys: list[str] = PydanticField(default_factory=list)
    view_names: list[str] = PydanticField(
        default_factory=list
    )  # All view names on this scene
    view_keys: list[str] = PydanticField(
        default_factory=list
    )  # All view keys on this scene


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
