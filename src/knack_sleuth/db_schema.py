"""Database schema export functionality for Knack applications.

This module provides functions to export the actual database structure described by
a Knack application into various schema formats (JSON Schema, DBML, YAML, Mermaid).
"""

import re
import unicodedata
from collections import deque
from copy import deepcopy
from typing import Any, NamedTuple

import yaml

from knack_sleuth.lookup import resolve_object
from knack_sleuth.models import Application, KnackField, KnackObject


def _should_include_field(field: KnackField, obj: KnackObject, detail: str) -> bool:
    """Determine if a field should be included based on detail level.

    Args:
        field: The field to check
        obj: The object containing the field
        detail: Detail level - "structural", "minimal", "compact", or "standard"

    Returns:
        True if the field should be included
    """
    if detail == "structural":
        # No fields - only show object/table structure
        return False

    if detail == "standard":
        return True

    # Connection fields are always included in minimal and compact levels
    if field.type == "connection":
        return True

    if detail == "minimal":
        # Only connection fields
        return False

    if detail == "compact":
        # Include identifier fields, required fields, and connection fields
        return field.key == obj.identifier or field.required

    return True


def _get_field_sql_type(field: KnackField) -> str:
    """Map Knack field types to SQL data types."""
    type_mapping = {
        "short_text": "VARCHAR(255)",
        "paragraph_text": "TEXT",
        "rich_text": "TEXT",
        "multiple_choice": "VARCHAR(255)",
        "number": "DECIMAL",
        "currency": "DECIMAL(19,4)",
        "boolean": "BOOLEAN",
        "date_time": "TIMESTAMP",
        "date": "DATE",
        "time": "TIME",
        "email": "VARCHAR(255)",
        "phone": "VARCHAR(50)",
        "address": "TEXT",
        "link": "VARCHAR(2048)",
        "image": "VARCHAR(2048)",
        "file": "VARCHAR(2048)",
        "signature": "VARCHAR(2048)",
        "name": "VARCHAR(255)",
        "auto_increment": "INTEGER",
        "rating": "INTEGER",
        "connection": "VARCHAR(50)",  # Foreign key
        "user_roles": "TEXT",
        "concatenation": "TEXT",  # Computed field
        "equation": "TEXT",  # Computed field
        "count": "INTEGER",  # Computed field
        "sum": "DECIMAL",  # Computed field
        "min": "DECIMAL",  # Computed field
        "max": "DECIMAL",  # Computed field
        "average": "DECIMAL",  # Computed field
        "timer": "INTEGER",
    }
    return type_mapping.get(field.type, "TEXT")


def _get_field_json_type(field: KnackField) -> str:
    """Map Knack field types to JSON Schema types."""
    type_mapping = {
        "short_text": "string",
        "paragraph_text": "string",
        "rich_text": "string",
        "multiple_choice": "string",
        "number": "number",
        "currency": "number",
        "boolean": "boolean",
        "date_time": "string",
        "date": "string",
        "time": "string",
        "email": "string",
        "phone": "string",
        "address": "object",
        "link": "string",
        "image": "string",
        "file": "string",
        "signature": "string",
        "name": "string",
        "auto_increment": "integer",
        "rating": "integer",
        "connection": "string",
        "user_roles": "array",
        "concatenation": "string",
        "equation": "string",
        "count": "integer",
        "sum": "number",
        "min": "number",
        "max": "number",
        "average": "number",
        "timer": "integer",
    }
    return type_mapping.get(field.type, "string")


def find_object_by_identifier(app: Application, identifier: str) -> KnackObject | None:
    """Find an object by key or name.

    Kept for backward compatibility; delegates to knack_sleuth.lookup.

    Args:
        app: The Knack application metadata
        identifier: Object key (e.g., 'object_12') or name (e.g., 'Events')

    Returns:
        The matching KnackObject, or None if not found
    """
    return resolve_object(app, identifier)


def build_subgraph(app: Application, start_object_key: str, depth: int) -> set[str]:
    """Build a subgraph of connected objects starting from a specific object.

    Uses breadth-first search to traverse connections up to the specified depth.

    Args:
        app: The Knack application metadata
        start_object_key: The key of the object to start from
        depth: Maximum depth to traverse (0 = start object only, 1 = start + direct connections, 2 = one more level, etc.)

    Returns:
        A set of object keys included in the subgraph
    """
    # Build object lookup
    objects_by_key = {obj.key: obj for obj in app.objects}

    # Initialize BFS
    subgraph = {start_object_key}
    queue = deque([(start_object_key, 0)])  # (object_key, current_depth)

    while queue:
        current_key, current_depth = queue.popleft()

        # Stop if we've reached max depth
        if current_depth >= depth:
            continue

        # Get the current object
        current_obj = objects_by_key.get(current_key)
        if not current_obj or not current_obj.connections:
            continue

        # Add all connected objects (both inbound and outbound)
        connected_keys = set()

        if current_obj.connections.outbound:
            for conn in current_obj.connections.outbound:
                connected_keys.add(conn.object)

        if current_obj.connections.inbound:
            for conn in current_obj.connections.inbound:
                connected_keys.add(conn.object)

        # Add new objects to subgraph and queue
        for key in connected_keys:
            if key not in subgraph:
                subgraph.add(key)
                queue.append((key, current_depth + 1))

    return subgraph


def filter_app_to_subgraph(app: Application, subgraph_keys: set[str]) -> Application:
    """Create a filtered Application containing only objects in the subgraph.

    Args:
        app: The original Knack application metadata
        subgraph_keys: Set of object keys to include in the subgraph

    Returns:
        A new Application instance with only the subgraph objects
    """
    # Filter objects
    filtered_objects = [obj for obj in app.objects if obj.key in subgraph_keys]

    # Create a copy of the application with filtered objects

    filtered_app = deepcopy(app)
    filtered_app.objects = filtered_objects

    # Filter connections within each object to only include connections
    # to other objects in the subgraph
    for obj in filtered_app.objects:
        if obj.connections:
            if obj.connections.outbound:
                obj.connections.outbound = [
                    conn
                    for conn in obj.connections.outbound
                    if conn.object in subgraph_keys
                ]
            if obj.connections.inbound:
                obj.connections.inbound = [
                    conn
                    for conn in obj.connections.inbound
                    if conn.object in subgraph_keys
                ]

    return filtered_app


def _build_field_json_schema(field: KnackField) -> dict[str, Any]:
    """Build JSON Schema definition for a field."""
    schema: dict[str, Any] = {
        "type": _get_field_json_type(field),
        "title": field.name,
        "x-knack-type": field.type,
        "x-knack-key": field.key,
    }

    if field.required:
        schema["x-required"] = True

    if field.unique:
        schema["x-unique"] = True

    if field.type == "email":
        schema["format"] = "email"
    elif field.type == "date":
        schema["format"] = "date"
    elif field.type == "date_time":
        schema["format"] = "date-time"
    elif field.type == "time":
        schema["format"] = "time"
    elif field.type == "link":
        schema["format"] = "uri"

    # Add relationship information for connection fields
    if field.relationship:
        schema["x-relationship"] = {
            "has": field.relationship.has,
            "object": field.relationship.object,
            "belongs_to": field.relationship.belongs_to,
        }

    # Add format information if available
    if field.format:
        schema["x-format"] = field.format.model_dump(exclude_none=True)

    return schema


def _connection_entries(
    obj: KnackObject, *, with_field_details: bool = False
) -> dict[str, Any]:
    """An object's outbound and inbound connections, for the JSON and YAML exports.

    with_field_details adds the YAML-only field_name and relationship_type,
    which reads from this object to the other end in both directions.
    """
    entries: dict[str, Any] = {}
    if not obj.connections:
        return entries
    for direction, other_end, conns in (
        ("outbound", "target_object", obj.connections.outbound),
        ("inbound", "source_object", obj.connections.inbound),
    ):
        if not conns:
            continue
        entries[direction] = []
        for conn in conns:
            entry: dict[str, Any] = {
                "key": conn.key,
                "name": conn.name,
                other_end: conn.object,
            }
            if with_field_details:
                entry["field_name"] = conn.field.name
            entry["has"] = conn.has
            entry["belongs_to"] = conn.belongs_to
            if with_field_details:
                label = _relationship(conn.has, conn.belongs_to).label
                # Knack gives an inbound entry the connecting object's
                # has/belongs_to; read it from this object instead, as the
                # outbound entries are.
                if direction == "inbound":
                    label = "-to-".join(reversed(label.split("-to-")))
                entry["relationship_type"] = label
            entries[direction].append(entry)
    return entries


def _object_json_schema(
    app: Application, obj: KnackObject, detail: str
) -> dict[str, Any]:
    obj_schema: dict[str, Any] = {
        "type": "object",
        "title": obj.name,
        "x-knack-key": obj.key,
        "properties": {},
        "x-record-count": app.counts.get(obj.key, 0),
    }
    if obj.user:
        obj_schema["x-user-object"] = True
    if obj.identifier:
        obj_schema["x-identifier-field"] = obj.identifier

    fields = [f for f in obj.fields if _should_include_field(f, obj, detail)]
    for field in fields:
        obj_schema["properties"][field.key] = _build_field_json_schema(field)
    required_fields = [field.key for field in fields if field.required]
    if required_fields:
        obj_schema["required"] = required_fields

    if obj.connections:
        obj_schema["x-connections"] = _connection_entries(obj)
    return obj_schema


def export_to_json_schema(app: Application, detail: str = "standard") -> dict[str, Any]:
    """Generate JSON Schema representing the actual database structure.

    Args:
        app: The Knack application metadata
        detail: Detail level - "structural", "minimal", "compact", or "standard"

    Returns:
        A JSON Schema document describing the database structure
    """
    schema: dict[str, Any] = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": app.name,
        "description": app.description or f"Database schema for {app.name}",
        "type": "object",
        "x-knack-app-id": app.id,
        "x-knack-slug": app.slug,
        "properties": {},
        "definitions": {},
    }
    for obj in app.objects:
        schema["definitions"][obj.key] = _object_json_schema(app, obj, detail)
        schema["properties"][obj.key] = {
            "$ref": f"#/definitions/{obj.key}",
            "type": "array",
            "items": {"$ref": f"#/definitions/{obj.key}"},
        }
    return schema


def _dbml_string(text: str) -> str:
    """A double-quoted DBML string."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{_one_line(escaped)}"'


def _one_line(text: str) -> str:
    """Text for a // comment or a string: line breaks would end it early."""
    return re.sub(r"\s*[\r\n]+\s*", " ", text)


def _dbml_field_line(field: KnackField, obj: KnackObject) -> str:
    attributes = []
    if field.required:
        attributes.append("not null")
    if field.unique:
        attributes.append("unique")

    line = f"  {field.key} {_get_field_sql_type(field)}"
    if attributes:
        line += f" [{', '.join(attributes)}]"
    identifier = ", identifier" if field.key == obj.identifier else ""
    return line + f"  // {_one_line(field.name)} ({field.type}{identifier})"


def _dbml_columns(obj: KnackObject, detail: str) -> list[str]:
    """The record ID, the fields the detail level keeps, and every outbound
    connection column, which the Refs need at any detail level."""
    outbound = obj.connections.outbound if obj.connections else []
    ref_keys = {conn.key for conn in outbound}
    lines = [_DBML_ID_COLUMN]
    lines += [
        _dbml_field_line(field, obj)
        for field in obj.fields
        if field.key in ref_keys or _should_include_field(field, obj, detail)
    ]
    field_keys = {field.key for field in obj.fields}
    lines += [
        f"  {conn.key} VARCHAR(50)  // {_one_line(conn.name)} (connection)"
        for conn in outbound
        if conn.key not in field_keys
    ]
    return lines


# Knack connection fields hold the connected records' IDs, so every table
# declares one and the Refs point at it.
_DBML_ID_COLUMN = "  id VARCHAR(50) [pk]  // Knack record ID"


def _dbml_table(app: Application, obj: KnackObject, detail: str) -> list[str]:
    lines = [f"Table {obj.key} {{", f"  // {_one_line(obj.name)}"]
    record_count = app.counts.get(obj.key, 0)
    if record_count > 0:
        lines.append(f"  // Records: {record_count}")
    if obj.user:
        lines.append("  // User Profile Object")
    lines.append("")
    lines += _dbml_columns(obj, detail)
    lines.append("")

    if obj.inflections:
        notes = (
            f"Plural: {obj.inflections.plural}, Singular: {obj.inflections.singular}"
        )
        lines.append(f"  Note: {_dbml_string(notes)}")
    lines += ["}", ""]
    return lines


def _dbml_refs(app: Application) -> list[str]:
    lines = ["// Relationships"]
    for obj in app.objects:
        if not obj.connections:
            continue
        for conn in obj.connections.outbound:
            rel_type = _relationship(conn.has, conn.belongs_to).dbml
            lines.append(
                f"Ref: {obj.key}.{conn.key} {rel_type} {conn.object}.id "
                f"// {_one_line(conn.name)}"
            )
    return lines


def export_to_dbml(app: Application, detail: str = "standard") -> str:
    """Generate DBML (Database Markup Language) schema.

    DBML is a simple, readable DSL language designed to define database schemas.
    It can be used with tools like dbdiagram.io to generate ER diagrams.

    Args:
        app: The Knack application metadata
        detail: Detail level - "structural", "minimal", "compact", or "standard"

    Returns:
        A DBML string representing the database structure
    """
    lines = [f"// Database schema for: {_one_line(app.name)}"]
    if app.description:
        lines.append(f"// Description: {_one_line(app.description)}")
    lines += [
        f"// Knack App ID: {app.id}",
        "",
        "Project knack_app {",
        '  database_type: "Knack"',
        f"  Note: {_dbml_string(app.name)}",
        "}",
        "",
    ]
    for obj in app.objects:
        lines += _dbml_table(app, obj, detail)
    lines += _dbml_refs(app)
    return "\n".join(lines)


def _yaml_field(field: KnackField) -> dict[str, Any]:
    field_data: dict[str, Any] = {
        "key": field.key,
        "name": field.name,
        "type": field.type,
        "sql_type": _get_field_sql_type(field),
        "required": field.required,
        "unique": field.unique,
    }
    if field.user:
        field_data["is_user_field"] = True
    if field.conditional:
        field_data["conditional"] = True
    if field.relationship:
        field_data["relationship"] = {
            "has": field.relationship.has,
            "object": field.relationship.object,
            "belongs_to": field.relationship.belongs_to,
        }
    if field.format:
        field_data["format"] = field.format.model_dump(exclude_none=True)
    return field_data


def _yaml_object(app: Application, obj: KnackObject, detail: str) -> dict[str, Any]:
    obj_data: dict[str, Any] = {
        "key": obj.key,
        "name": obj.name,
        "record_count": app.counts.get(obj.key, 0),
        "is_user_object": obj.user,
        "identifier_field": obj.identifier,
        "fields": [],
    }
    if obj.inflections:
        obj_data["inflections"] = {
            "singular": obj.inflections.singular,
            "plural": obj.inflections.plural,
        }
    obj_data["fields"] = [
        _yaml_field(field)
        for field in obj.fields
        if _should_include_field(field, obj, detail)
    ]
    if obj.connections:
        obj_data["connections"] = _connection_entries(obj, with_field_details=True)
    return obj_data


def export_to_yaml(app: Application, detail: str = "standard") -> str:
    """Generate YAML representation of the database structure.

    Args:
        app: The Knack application metadata
        detail: Detail level - "structural", "minimal", "compact", or "standard"

    Returns:
        A YAML string representing the database structure
    """
    schema: dict[str, Any] = {
        "application": {
            "name": app.name,
            "slug": app.slug,
            "id": app.id,
            "description": app.description,
        },
        "objects": [_yaml_object(app, obj, detail) for obj in app.objects],
    }
    return yaml.dump(schema, default_flow_style=False, sort_keys=False, indent=2)


class _Relationship(NamedTuple):
    """One has/belongs_to combination in each export's notation."""

    label: str
    dbml: str
    mermaid: str


# Read from the connecting object to the connected one. Knack's `has` is how
# many connected records each connecting record holds; `belongs_to` is how many
# connecting records each connected record can belong to. So Events.Client with
# has=one, belongs_to=many is many Events to one Client, which real records
# confirm (no Event holds two Clients; a Client is on up to four Events).
#
# Mermaid ER syntax: ||--|| exactly one on both sides; ||--o{ one to zero or
# more; }o--|| zero or more to exactly one; }o--o{ zero or more on both sides.
# DBML: `a.x > b.id` is many a to one b; `<` the reverse.
_RELATIONSHIPS = {
    ("one", "one"): _Relationship("one-to-one", "-", "||--||"),
    ("one", "many"): _Relationship("many-to-one", ">", "}o--||"),
    ("many", "one"): _Relationship("one-to-many", "<", "||--o{"),
}
# Anything else, including unexpected values, is treated as many-to-many.
_MANY_TO_MANY = _Relationship("many-to-many", "<>", "}o--o{")


def _relationship(has: str, belongs_to: str) -> _Relationship:
    return _RELATIONSHIPS.get((has, belongs_to), _MANY_TO_MANY)


def _get_mermaid_type(field: KnackField) -> str:
    """Map Knack field types to Mermaid-friendly type names."""
    type_mapping = {
        "short_text": "string",
        "paragraph_text": "text",
        "rich_text": "text",
        "multiple_choice": "string",
        "number": "decimal",
        "currency": "decimal",
        "boolean": "boolean",
        "date_time": "datetime",
        "date": "date",
        "time": "time",
        "email": "string",
        "phone": "string",
        "address": "text",
        "link": "string",
        "image": "string",
        "file": "string",
        "signature": "string",
        "name": "string",
        "auto_increment": "int",
        "rating": "int",
        "connection": "string",
        "user_roles": "string",
        "concatenation": "string",
        "equation": "string",
        "count": "int",
        "sum": "decimal",
        "min": "decimal",
        "max": "decimal",
        "average": "decimal",
        "timer": "int",
    }
    return type_mapping.get(field.type, "string")


def _sanitize_entity_name(name: str) -> str:
    """Convert object name to valid Mermaid entity name.

    Mermaid entity names should be uppercase and use dashes instead of spaces.
    Remove or replace special characters to ensure valid syntax.

    Args:
        name: The original object name

    Returns:
        A sanitized entity name suitable for Mermaid
    """

    # Convert to uppercase
    sanitized = name.upper()

    # Replace spaces, underscores, and other separators with dashes
    sanitized = re.sub(r"[\s_/]+", "-", sanitized)

    # Remove any characters that aren't alphanumeric, dash, or underscore
    sanitized = re.sub(r"[^\w\-]", "", sanitized)

    # Replace multiple consecutive dashes with single dash
    sanitized = re.sub(r"-+", "-", sanitized)

    # Remove leading/trailing dashes
    sanitized = sanitized.strip("-")

    # Ensure it doesn't start with a number
    if sanitized and sanitized[0].isdigit():
        sanitized = f"OBJ-{sanitized}"

    # Fallback if name becomes empty
    if not sanitized:
        sanitized = "OBJECT"

    return sanitized


def _sanitize_field_name(name: str) -> str:
    """Convert field name to valid camelCase identifier for Mermaid.

    Converts field names to camelCase identifiers suitable for use
    in Mermaid ER diagrams. Removes special characters and handles edge cases.

    Args:
        name: The original field name

    Returns:
        A camelCase identifier suitable for Mermaid
    """

    # Mermaid attribute names accept non-ASCII only from U+00C0 up, but Python's
    # \w keeps a few word characters below that (ª ² ³ µ º ¹ ¼ ½ ¾). NFKC folds
    # them into equivalents Mermaid accepts: "m²" -> "m2", "µ" -> "μ".
    name = unicodedata.normalize("NFKC", name)

    # Split on spaces, dashes, slashes, parentheses, and underscores
    words = re.split(r"[\s\-/()_]+", name)

    # Filter out empty strings and remove non-alphanumeric characters
    words = [re.sub(r"[^\w]", "", word) for word in words if word]

    if not words:
        return "field"

    # Convert to camelCase: first word lowercase, rest capitalized
    camel_case = words[0].lower()
    for word in words[1:]:
        if word:
            camel_case += word.capitalize()

    # Ensure it doesn't start with a number
    if camel_case and camel_case[0].isdigit():
        camel_case = f"field{camel_case.capitalize()}"

    # Fallback if name becomes empty
    if not camel_case:
        camel_case = "field"

    return camel_case


def _strip_html(text: str) -> str:
    """Strip HTML tags and clean up text for use in comments.

    Args:
        text: Text that may contain HTML tags

    Returns:
        Cleaned text without HTML tags
    """

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Decode common HTML entities
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")

    # Clean up whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _mermaid_entity_names(app: Application) -> dict[str, str]:
    """Sanitized entity name per object key; a repeated name gets its key appended."""
    entity_names: dict[str, str] = {}
    seen: set[str] = set()
    for obj in app.objects:
        sanitized = _sanitize_entity_name(obj.name)
        if sanitized in seen:
            entity_names[obj.key] = f"{sanitized}_{obj.key.upper()}"
        else:
            seen.add(sanitized)
            entity_names[obj.key] = sanitized
    return entity_names


def _mermaid_relationship_lines(
    app: Application, entity_names: dict[str, str]
) -> list[str]:
    """One line per outbound connection; a pair of objects can have several."""
    lines = []
    for obj in app.objects:
        if not obj.connections:
            continue
        for conn in obj.connections.outbound:
            notation = _relationship(conn.has, conn.belongs_to).mermaid
            source_name = entity_names[obj.key]
            target_name = entity_names.get(conn.object, conn.object)
            # A double quote would end the label early.
            label = _one_line(conn.name).replace('"', "'")
            lines.append(f'    {source_name} {notation} {target_name} : "{label}"')
    return lines


def _mermaid_field_line(field: KnackField, obj: KnackObject) -> str:
    # Mermaid allows one key constraint: PK, then FK, then UK (unique).
    constraint = ""
    if field.key == obj.identifier:
        constraint = " PK"
    elif field.type == "connection":
        constraint = " FK"
    elif field.unique:
        constraint = " UK"

    comment = ""
    description = _field_description(field)
    if description:
        # Mermaid has no escape for a double quote inside a comment.
        unquoted = description.replace('"', "'")
        comment = f' "{unquoted}"'

    field_type = _get_mermaid_type(field)
    field_name = _sanitize_field_name(field.name)
    return f"        {field_type} {field_name}{constraint}{comment}"


def _field_description(field: KnackField) -> str | None:
    """The field's description from its metadata, without HTML, if it has one."""
    meta = getattr(field, "meta", None)
    if not meta:
        return None
    meta = meta if isinstance(meta, dict) else meta.__dict__
    if meta.get("description"):
        return _strip_html(meta["description"])
    return None


def export_to_mermaid(app: Application, detail: str = "standard") -> str:
    """Generate Mermaid ER diagram syntax.

    Mermaid is a JavaScript-based diagramming tool that renders markdown-inspired
    text definitions to create diagrams. This generates an entity-relationship diagram
    that can be rendered in GitHub, GitLab, VS Code, and many other tools.

    Args:
        app: The Knack application metadata
        detail: Detail level - "structural", "minimal", "compact", or "standard"

    Returns:
        A Mermaid ER diagram string
    """
    entity_names = _mermaid_entity_names(app)

    lines = ["erDiagram", f"    %% Database schema for: {app.name}"]
    if app.description:
        lines.append(f"    %% Description: {app.description}")
    lines += [f"    %% Knack App ID: {app.id}", ""]

    relationship_lines = _mermaid_relationship_lines(app, entity_names)
    if relationship_lines:
        lines += [*relationship_lines, ""]

    for obj in app.objects:
        lines.append(f"    {entity_names[obj.key]} {{")
        lines += [
            _mermaid_field_line(field, obj)
            for field in obj.fields
            if _should_include_field(field, obj, detail)
        ]
        lines += ["    }", ""]

    return "\n".join(lines)


def export_database_schema(
    app: Application, format: str = "json", detail: str = "standard"
) -> str | dict[str, Any]:
    """Export database schema in the specified format.

    Args:
        app: The Knack application metadata
        format: Output format - "json", "dbml", "yaml", or "mermaid"
        detail: Detail level - "structural", "minimal", "compact", or "standard"
            - "structural": Only objects/tables and relationships (no attributes)
            - "minimal": Only connection fields
            - "compact": Connection fields, identifier fields, and required fields
            - "standard": All fields

    Returns:
        Schema representation in the specified format

    Raises:
        ValueError: If format or detail is not supported
    """
    valid_details = ["structural", "minimal", "compact", "standard"]
    if detail not in valid_details:
        raise ValueError(
            f"Unsupported detail level: {detail}. Use 'structural', 'minimal', 'compact', or 'standard'"
        )

    if format == "json":
        return export_to_json_schema(app, detail=detail)
    if format == "dbml":
        return export_to_dbml(app, detail=detail)
    if format == "yaml":
        return export_to_yaml(app, detail=detail)
    if format == "mermaid":
        return export_to_mermaid(app, detail=detail)
    raise ValueError(
        f"Unsupported format: {format}. Use 'json', 'dbml', 'yaml', or 'mermaid'"
    )
