"""Schema exports: export-schema, export-db-schema, export-schema-subgraph."""

import json
import re
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.markup import escape

from knack_sleuth.db_schema import (
    build_subgraph,
    export_database_schema,
    filter_app_to_subgraph,
    find_object_by_identifier,
)
from knack_sleuth.models import KnackAppMetadata

from ._common import (
    cli,
    console,
    err_console,
    exit_on_error,
    fail,
    file_size_kb,
    load_app_metadata,
    validate_choice,
)
from ._options import (
    Refresh,
    SchemaAppId,
    SchemaDetail,
    SchemaFile,
    SchemaFormat,
    SchemaOutput,
)

# export-schema-subgraph warns past this; deeper usually means most of the app.
RECOMMENDED_MAX_SUBGRAPH_DEPTH = 2

SCHEMA_FORMATS = ("json", "dbml", "yaml", "mermaid")
SCHEMA_DETAILS = ("structural", "minimal", "compact", "standard")
_EXTENSIONS = {"json": "json", "dbml": "dbml", "yaml": "yaml", "mermaid": "mmd"}
_MERMAID_TIP = (
    "Tip: This Mermaid diagram can be rendered in GitHub/GitLab markdown, "
    "VS Code, or at https://mermaid.live"
)
_DB_TIPS = {
    "dbml": "Tip: Upload this DBML file to https://dbdiagram.io to visualize the database ER diagram",
    "json": "Tip: This JSON Schema describes the actual database structure with all relationships",
    "mermaid": _MERMAID_TIP,
    "yaml": "Tip: This YAML file provides a human-readable database structure overview",
}
_SUBGRAPH_TIPS = {
    "dbml": "Tip: Upload this DBML file to https://dbdiagram.io to visualize the subgraph ER diagram",
    "json": "Tip: This JSON Schema describes the subgraph database structure with all relationships",
    "mermaid": _MERMAID_TIP,
    "yaml": "Tip: This YAML file provides a human-readable subgraph structure overview",
}


# --- export-schema ------------------------------------------------------------


@cli.command(name="export-schema")
def export_schema(
    output_file: Annotated[
        Path | None,
        typer.Argument(help="Output file path (default: knack_metadata_schema.json)"),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(
            "--mode", help="Schema generation mode: validation or serialization"
        ),
    ] = "validation",
):
    """
    Export Knack's internal metadata schema (how an application looks to Knack itself).

    This generates a JSON schema document that describes the structure of Knack's
    internal application metadata format - the raw metadata structure that Knack uses
    internally. This is NOT your application's database schema (use export-db-schema
    for that). Useful for:

    This generates a JSON schema document that describes the structure
    of Knack application metadata.


    Useful for:

    - API documentation

    - Validation in other tools

    - IDE autocomplete for metadata JSON files

    - Integration with schema-aware editors


    Modes:

    - validation: Schema optimized for validating incoming data (default)

    - serialization: Schema optimized for serialized output


    Examples:

        knack-sleuth export-schema                           # Uses default filename

        knack-sleuth export-schema my_schema.json            # Custom filename

        knack-sleuth export-schema --mode serialization      # Serialization mode
    """
    output_file = output_file or Path("knack_metadata_schema.json")
    if mode not in ("validation", "serialization"):
        fail(f"Unknown mode '{mode}'. Use 'validation' or 'serialization'.")

    with exit_on_error("Failed to generate or save schema: "):
        schema = KnackAppMetadata.model_json_schema(mode=mode)
        with output_file.open("w") as f:
            json.dump(schema, f, indent=2)

    console.print()
    console.print(
        f"[green]✓[/green] JSON schema exported to [bold]{escape(str(output_file))}[/bold]"
    )
    console.print(f"[dim]  Mode: {mode}[/dim]")
    console.print(f"[dim]  File size: {file_size_kb(output_file)}[/dim]")
    console.print()
    console.print(
        "[dim]Use this schema for API documentation, validation, or IDE integration[/dim]"
    )
    console.print()


# --- shared by export-db-schema and export-schema-subgraph ----------------------


def _validate_schema_options(format: str, detail: str) -> None:
    validate_choice(format, SCHEMA_FORMATS)
    validate_choice(detail, SCHEMA_DETAILS, "detail level")


def _load(file_path: Path | None, app_id: str | None, refresh: bool):
    """Load the app, announcing it; the loader handles cache messaging + errors."""
    console.print("[dim]Loading application metadata...[/dim]")
    app = load_app_metadata(file_path, app_id, refresh).application
    console.print(
        f"[green]✓[/green] Loaded: [bold]{escape(app.name)}[/bold] ({len(app.objects)} objects)"
    )
    return app


def _generate_and_write(app, format: str, detail: str, output_file: Path) -> None:
    console.print(f"[dim]Generating {format.upper()} schema ({detail} detail)...[/dim]")
    with exit_on_error():
        schema: Any = export_database_schema(app, format=format, detail=detail)
        with output_file.open("w") as f:
            if isinstance(schema, str):
                f.write(schema)
            else:
                json.dump(schema, f, indent=2)


def _print_export_details(details: list[str], tip: str) -> None:
    for line in details:
        console.print(f"[dim]  {line}[/dim]")
    console.print()
    console.print(f"[dim]{tip}[/dim]")
    console.print()


# --- export-db-schema -----------------------------------------------------------


@cli.command(name="export-db-schema")
def export_db_schema(
    file_path: SchemaFile = None,
    output_file: SchemaOutput = None,
    format: SchemaFormat = "json",
    detail: SchemaDetail = "standard",
    app_id: SchemaAppId = None,
    refresh: Refresh = False,
):
    """
    Export your application's database schema (how your app looks to you).

    This generates a user-facing schema representation of your database structure,
    similar to what you see in the Knack builder. It analyzes objects (tables),
    fields (columns), and connections (relationships) to construct an ER diagram
    or schema document. This is NOT Knack's internal metadata format (use
    export-schema for that).


    Supported formats:

    - json: JSON Schema format with full relationship metadata

    - dbml: Database Markup Language for ER diagram generation (dbdiagram.io)

    - yaml: Human-readable YAML representation

    - mermaid: Mermaid ER diagram syntax (GitHub, GitLab, VS Code compatible)


    Detail levels:

    - structural: Objects/tables and relationships only (no attributes)

    - minimal: Objects and connections only (high-level structure)

    - compact: Key fields (identifier, required, connections)

    - standard: All fields with complete details (default)


    Examples:

        # Export from file to JSON Schema
        knack-sleuth export-db-schema app_export.json

        # Export to DBML for ER diagram with minimal detail
        knack-sleuth export-db-schema app_export.json --format dbml --detail minimal -o schema.dbml

        # Export to Mermaid ER diagram
        knack-sleuth export-db-schema app_export.json --format mermaid -o schema.mmd

        # Export compact view to YAML
        knack-sleuth export-db-schema app_export.json --format yaml --detail compact

        # Export to YAML
        knack-sleuth export-db-schema app_export.json --format yaml -o schema.yaml

        # Load from Knack API and export (no API key needed for public metadata)
        knack-sleuth export-db-schema --app-id YOUR_APP_ID -f dbml
    """
    _validate_schema_options(format, detail)
    output_file = output_file or Path(f"knack_db_schema.{_EXTENSIONS[format]}")

    app = _load(file_path, app_id, refresh)
    console.print()
    _generate_and_write(app, format, detail, output_file)

    console.print(
        f"[green]✓[/green] Database schema exported to [bold]{escape(str(output_file))}[/bold]"
    )
    _print_export_details(
        [
            f"Format: {format.upper()}",
            f"Detail: {detail}",
            f"Objects: {len(app.objects)}",
            f"File size: {file_size_kb(output_file)}",
        ],
        _DB_TIPS[format],
    )


# --- export-schema-subgraph -----------------------------------------------------


def _subgraph_filename(object_identifier: str, format: str) -> Path:
    """Default output name, with the object name reduced to a safe slug."""
    slug = object_identifier.lower().replace(" ", "-").replace("_", "-")
    slug = re.sub(r"[^\w\-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return Path(f"knack_subgraph_{slug}.{_EXTENSIONS[format]}")


def _clamp_depth(depth: int) -> int:
    if depth > RECOMMENDED_MAX_SUBGRAPH_DEPTH:
        err_console.print(
            f"[yellow]Warning:[/yellow] Depth {depth} is not recommended. "
            "For larger depths, consider using [cyan]export-db-schema[/cyan] to export the full schema instead."
        )
        console.print()
        console.print(
            f"Proceeding with depth={RECOMMENDED_MAX_SUBGRAPH_DEPTH} (maximum recommended)..."
        )
        return RECOMMENDED_MAX_SUBGRAPH_DEPTH
    if depth < 0:
        fail("Depth must be >= 0")
    return depth


@cli.command(name="export-schema-subgraph")
def export_schema_subgraph(
    file_path: SchemaFile = None,
    *,
    object: Annotated[
        str,
        typer.Option(
            "--object",
            help="Starting object (key or name, e.g., 'Events' or 'object_12')",
        ),
    ],
    depth: Annotated[
        int,
        typer.Option(
            "--depth",
            help="Traversal depth (0=object only, 1=direct connections, 2=one level deeper)",
        ),
    ] = 1,
    output_file: SchemaOutput = None,
    format: SchemaFormat = "json",
    detail: SchemaDetail = "standard",
    app_id: SchemaAppId = None,
    refresh: Refresh = False,
):
    """
    Export a subgraph of the database schema starting from a specific object.

    This generates a schema representation of a subset of the database, starting
    from a specified object and including all objects connected to it up to a
    specified depth.


    Depth levels:

    - depth=0: Starting object only (no connections)

    - depth=1: Starting object + all directly connected objects (default)

    - depth=2: Above + connections of those directly connected objects

    - depth>2: Not recommended - use export-db-schema for full schema


    Supported formats:

    - json: JSON Schema format with full relationship metadata

    - dbml: Database Markup Language for ER diagram generation (dbdiagram.io)

    - yaml: Human-readable YAML representation

    - mermaid: Mermaid ER diagram syntax (GitHub, GitLab, VS Code compatible)


    Detail levels:

    - structural: Objects/tables and relationships only (no attributes)

    - minimal: Objects and connections only (high-level structure)

    - compact: Key fields (identifier, required, connections)

    - standard: All fields with complete details (default)


    Examples:

        # Export Events and direct connections to YAML
        knack-sleuth export-schema-subgraph --object Events -f yaml -o events.yaml

        # Export Events subgraph with depth 2 to Mermaid
        knack-sleuth export-schema-subgraph --object Events --depth 2 -f mermaid

        # Export from API using object key
        knack-sleuth export-schema-subgraph --app-id YOUR_APP_ID --object object_12 -f dbml

        # Export with minimal detail level
        knack-sleuth export-schema-subgraph app.json --object Events --detail minimal -f yaml
    """
    depth = _clamp_depth(depth)
    _validate_schema_options(format, detail)
    output_file = output_file or _subgraph_filename(object, format)

    app = _load(file_path, app_id, refresh)

    start = find_object_by_identifier(app, object)
    if not start:
        fail(f"Object '{object}' not found. Please specify a valid object key or name.")
    console.print(
        f"[green]✓[/green] Starting object: [bold]{escape(start.name)}[/bold] ({start.key})"
    )

    console.print(f"[dim]Building subgraph with depth {depth}...[/dim]")
    with exit_on_error():
        subgraph_keys = build_subgraph(app, start.key, depth)
    console.print(
        f"[green]✓[/green] Subgraph contains [bold]{len(subgraph_keys)}[/bold] objects"
    )

    objects_by_key = {obj.key: obj for obj in app.objects}
    console.print("\n[cyan]Objects in subgraph:[/cyan]")
    for key in sorted(subgraph_keys):
        obj = objects_by_key.get(key)
        if obj:
            console.print(f"  • {escape(obj.name)} ({key})")
    console.print()

    with exit_on_error():
        filtered_app = filter_app_to_subgraph(app, subgraph_keys)
    _generate_and_write(filtered_app, format, detail, output_file)

    console.print(
        f"[green]✓[/green] Schema subgraph exported to [bold]{escape(str(output_file))}[/bold]"
    )
    _print_export_details(
        [
            f"Format: {format.upper()}",
            f"Detail: {detail}",
            f"Starting object: {escape(start.name)} ({start.key})",
            f"Depth: {depth}",
            f"Objects: {len(subgraph_keys)}",
            f"File size: {file_size_kb(output_file)}",
        ],
        _SUBGRAPH_TIPS[format],
    )
