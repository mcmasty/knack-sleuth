"""Database schema export functionality for Knack applications.

This module provides functions to export the actual database structure described by
a Knack application into various schema formats (JSON Schema, DBML, YAML, Mermaid).
"""

from typing import Any

import yaml

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
        if field.key == obj.identifier:
            return True
        if field.required:
            return True
        return False

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

    # Build schema for each object (table)
    for obj in app.objects:
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

        # Add fields based on detail level
        required_fields = []
        for field in obj.fields:
            if _should_include_field(field, obj, detail):
                obj_schema["properties"][field.key] = _build_field_json_schema(field)
                if field.required:
                    required_fields.append(field.key)

        if required_fields:
            obj_schema["required"] = required_fields

        # Add connection information
        if obj.connections:
            connections_info: dict[str, Any] = {}

            if obj.connections.outbound:
                connections_info["outbound"] = [
                    {
                        "key": conn.key,
                        "name": conn.name,
                        "target_object": conn.object,
                        "has": conn.has,
                        "belongs_to": conn.belongs_to,
                    }
                    for conn in obj.connections.outbound
                ]

            if obj.connections.inbound:
                connections_info["inbound"] = [
                    {
                        "key": conn.key,
                        "name": conn.name,
                        "source_object": conn.object,
                        "has": conn.has,
                        "belongs_to": conn.belongs_to,
                    }
                    for conn in obj.connections.inbound
                ]

            obj_schema["x-connections"] = connections_info

        schema["definitions"][obj.key] = obj_schema
        schema["properties"][obj.key] = {
            "$ref": f"#/definitions/{obj.key}",
            "type": "array",
            "items": {"$ref": f"#/definitions/{obj.key}"},
        }

    return schema


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
    # Build object index for looking up identifiers
    objects_by_key = {obj.key: obj for obj in app.objects}

    lines = []
    lines.append(f"// Database schema for: {app.name}")
    if app.description:
        lines.append(f"// Description: {app.description}")
    lines.append(f"// Knack App ID: {app.id}")
    lines.append("")

    # Project metadata
    lines.append("Project knack_app {")
    lines.append('  database_type: "Knack"')
    lines.append(f'  Note: "{app.name}"')
    lines.append("}")
    lines.append("")

    # Define tables (objects)
    for obj in app.objects:
        # Table name and metadata
        table_name = obj.key
        lines.append(f"Table {table_name} {{")
        lines.append(f'  // {obj.name}')

        record_count = app.counts.get(obj.key, 0)
        if record_count > 0:
            lines.append(f"  // Records: {record_count}")

        if obj.user:
            lines.append("  // User Profile Object")

        lines.append("")

        # Add fields based on detail level
        for field in obj.fields:
            if _should_include_field(field, obj, detail):
                field_line = f"  {field.key} {_get_field_sql_type(field)}"

                attributes = []
                if field.required:
                    attributes.append("not null")
                if field.unique:
                    attributes.append("unique")
                if field.key == obj.identifier:
                    attributes.append("pk")

                if attributes:
                    field_line += f" [{', '.join(attributes)}]"

                field_line += f"  // {field.name} ({field.type})"
                lines.append(field_line)

        lines.append("")

        # Add note with additional metadata
        notes = []
        if obj.inflections:
            notes.append(
                f"Plural: {obj.inflections.plural}, Singular: {obj.inflections.singular}"
            )

        if notes:
            lines.append(f'  Note: "{"; ".join(notes)}"')

        lines.append("}")
        lines.append("")

    # Define relationships (connections)
    lines.append("// Relationships")
    for obj in app.objects:
        if not obj.connections or not obj.connections.outbound:
            continue

        for conn in obj.connections.outbound:
            # Determine relationship type
            if conn.has == "many" and conn.belongs_to == "one":
                # Many-to-one
                rel_type = ">"
            elif conn.has == "one" and conn.belongs_to == "many":
                # One-to-many
                rel_type = "<"
            elif conn.has == "one" and conn.belongs_to == "one":
                # One-to-one
                rel_type = "-"
            else:  # many-to-many
                rel_type = "<>"

            # Get target object's identifier field
            target_obj = objects_by_key.get(conn.object)
            target_field = target_obj.identifier if target_obj and target_obj.identifier else conn.key

            lines.append(
                f"Ref: {obj.key}.{conn.key} {rel_type} {conn.object}.{target_field} "
                f'// {conn.name}'
            )

    return "\n".join(lines)


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
        "objects": [],
    }

    for obj in app.objects:
        obj_data: dict[str, Any] = {
            "key": obj.key,
            "name": obj.name,
            "record_count": app.counts.get(obj.key, 0),
            "is_user_object": obj.user,
            "identifier_field": obj.identifier,
            "fields": [],
        }

        # Add inflections if available
        if obj.inflections:
            obj_data["inflections"] = {
                "singular": obj.inflections.singular,
                "plural": obj.inflections.plural,
            }

        # Add fields based on detail level
        for field in obj.fields:
            if _should_include_field(field, obj, detail):
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

                obj_data["fields"].append(field_data)

        # Add connections
        if obj.connections:
            connections: dict[str, Any] = {}

            if obj.connections.outbound:
                connections["outbound"] = [
                    {
                        "key": conn.key,
                        "name": conn.name,
                        "target_object": conn.object,
                        "field_name": conn.field.name,
                        "has": conn.has,
                        "belongs_to": conn.belongs_to,
                        "relationship_type": _get_relationship_type(
                            conn.has, conn.belongs_to
                        ),
                    }
                    for conn in obj.connections.outbound
                ]

            if obj.connections.inbound:
                connections["inbound"] = [
                    {
                        "key": conn.key,
                        "name": conn.name,
                        "source_object": conn.object,
                        "field_name": conn.field.name,
                        "has": conn.has,
                        "belongs_to": conn.belongs_to,
                        "relationship_type": _get_relationship_type(
                            conn.has, conn.belongs_to
                        ),
                    }
                    for conn in obj.connections.inbound
                ]

            obj_data["connections"] = connections

        schema["objects"].append(obj_data)

    return yaml.dump(schema, default_flow_style=False, sort_keys=False, indent=2)


def _get_relationship_type(has: str, belongs_to: str) -> str:
    """Determine the relationship type from has/belongs_to values."""
    if has == "one" and belongs_to == "one":
        return "one-to-one"
    elif has == "one" and belongs_to == "many":
        return "one-to-many"
    elif has == "many" and belongs_to == "one":
        return "many-to-one"
    else:  # many-to-many
        return "many-to-many"


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


def _get_mermaid_relationship(has: str, belongs_to: str) -> str:
    """Convert has/belongs_to to Mermaid relationship notation.

    Mermaid ER syntax:
    - ||--|| : one-to-one (exactly one)
    - ||--o{ : one-to-many (zero or more)
    - }o--|| : many-to-one (zero or more to exactly one)
    - }o--o{ : many-to-many (zero or more on both sides)
    """
    if has == "one" and belongs_to == "one":
        return "||--||"
    elif has == "one" and belongs_to == "many":
        return "||--o{"
    elif has == "many" and belongs_to == "one":
        return "}o--||"
    else:  # many-to-many
        return "}o--o{"


def _sanitize_entity_name(name: str) -> str:
    """Convert object name to valid Mermaid entity name.

    Mermaid entity names should be uppercase and use underscores instead of spaces.
    Remove or replace special characters to ensure valid syntax.

    Args:
        name: The original object name

    Returns:
        A sanitized entity name suitable for Mermaid
    """
    import re

    # Convert to uppercase
    sanitized = name.upper()

    # Replace spaces, dashes, and other separators with underscores
    sanitized = re.sub(r'[\s\-/]+', '_', sanitized)

    # Remove any characters that aren't alphanumeric or underscore
    sanitized = re.sub(r'[^\w]', '', sanitized)

    # Ensure it doesn't start with a number
    if sanitized and sanitized[0].isdigit():
        sanitized = f"OBJ_{sanitized}"

    # Fallback if name becomes empty
    if not sanitized:
        sanitized = "OBJECT"

    return sanitized


def _sanitize_field_name(name: str) -> str:
    """Convert field name to valid Mermaid field name or quoted string.

    If the field name contains special characters or spaces, it will be quoted.
    Otherwise, convert to a valid identifier.

    Args:
        name: The original field name

    Returns:
        A sanitized field name suitable for Mermaid (may be quoted)
    """
    import re

    # Check if the name needs quoting (contains spaces or special chars)
    if re.search(r'[\s\-/]', name):
        # Quote the name and escape any internal quotes
        return f'"{name.replace(chr(34), chr(92) + chr(34))}"'

    # Remove any characters that aren't alphanumeric or underscore
    sanitized = re.sub(r'[^\w]', '', name)

    # Ensure it doesn't start with a number
    if sanitized and sanitized[0].isdigit():
        sanitized = f"field_{sanitized}"

    # Fallback if name becomes empty
    if not sanitized:
        sanitized = "field"

    return sanitized


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
    # Build a mapping from object keys to sanitized entity names
    # Handle duplicate names by appending the key
    entity_names: dict[str, str] = {}
    name_counts: dict[str, int] = {}

    for obj in app.objects:
        sanitized = _sanitize_entity_name(obj.name)

        # Handle duplicate names
        if sanitized in name_counts:
            name_counts[sanitized] += 1
            entity_names[obj.key] = f"{sanitized}_{obj.key.upper()}"
        else:
            name_counts[sanitized] = 1
            entity_names[obj.key] = sanitized

    lines = []
    lines.append("erDiagram")
    lines.append(f"    %% Database schema for: {app.name}")
    if app.description:
        lines.append(f"    %% Description: {app.description}")
    lines.append(f"    %% Knack App ID: {app.id}")
    lines.append("")

    # First pass: Define all relationships
    relationships_added = set()
    for obj in app.objects:
        if not obj.connections or not obj.connections.outbound:
            continue

        for conn in obj.connections.outbound:
            # Create a unique key to avoid duplicate relationships
            rel_key = tuple(sorted([obj.key, conn.object]))
            if rel_key in relationships_added:
                continue

            relationships_added.add(rel_key)

            # Get the relationship notation
            rel_notation = _get_mermaid_relationship(conn.has, conn.belongs_to)

            # Get entity names for source and target
            source_name = entity_names[obj.key]
            target_name = entity_names.get(conn.object, conn.object)

            # Format: SOURCE_TABLE NOTATION TARGET_TABLE : "relationship_name"
            lines.append(f'    {source_name} {rel_notation} {target_name} : "{conn.name}"')

    if relationships_added:
        lines.append("")

    # Second pass: Define all entities (tables) with their fields
    for obj in app.objects:
        # Start entity definition with readable name and key as comment
        entity_name = entity_names[obj.key]
        lines.append(f"    {entity_name} {{")

        # Add fields based on detail level
        for field in obj.fields:
            if _should_include_field(field, obj, detail):
                field_type = _get_mermaid_type(field)
                field_name = _sanitize_field_name(field.name)

                # Determine primary constraint (Mermaid supports one key constraint)
                # Priority: PK > FK > UK (unique)
                constraint = ""
                if field.key == obj.identifier:
                    constraint = " PK"
                elif field.type == "connection":
                    constraint = " FK"
                elif field.unique:
                    constraint = " UK"

                # Build the attribute line: type name constraints
                lines.append(f"        {field_type} {field_name}{constraint}")

        lines.append("    }")
        lines.append("")

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
        raise ValueError(f"Unsupported detail level: {detail}. Use 'structural', 'minimal', 'compact', or 'standard'")

    if format == "json":
        return export_to_json_schema(app, detail=detail)
    elif format == "dbml":
        return export_to_dbml(app, detail=detail)
    elif format == "yaml":
        return export_to_yaml(app, detail=detail)
    elif format == "mermaid":
        return export_to_mermaid(app, detail=detail)
    else:
        raise ValueError(f"Unsupported format: {format}. Use 'json', 'dbml', 'yaml', or 'mermaid'")
