"""Object and field exploration: list-objects, search-object, search-field,
show-coupling."""

import json
from dataclasses import asdict
from typing import Annotated, Any

import typer
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from knack_sleuth.lookup import resolve_fields, suggest_field_names
from knack_sleuth.models import KnackObject
from knack_sleuth.sleuth import KnackSleuth

from ._common import (
    cli,
    console,
    err_console,
    exit_ambiguous_field,
    load_app_metadata,
    print_builder_pages,
    print_suggestions,
    print_usages,
    resolve_object_or_exit,
    scene_keys_of,
    validate_output_format,
)
from ._options import AppId, MetadataFile, Refresh, RichOrJson

# --- list-objects -------------------------------------------------------------


def _object_entry(obj: KnackObject, counts: dict[str, int]) -> dict[str, Any]:
    ca = len(obj.connections.inbound) if obj.connections else 0
    ce = len(obj.connections.outbound) if obj.connections else 0
    total = ca + ce
    return {
        "key": obj.key,
        "name": obj.name,
        "rows": counts.get(obj.key, 0),
        "fields": len(obj.fields),
        "ca": ca,
        "ce": ce,
        "total_connections": total,
        "instability": round(ce / total, 2) if total else None,
    }


def _connection_count(objects: list[KnackObject]) -> int:
    """How many connections the app has, each counted once.

    A connection is one connection field. It is listed as outbound on the
    object that owns the field and as inbound on the other, under the same
    field key, so adding Ca to Ce counts it twice. Counting keys rather than
    one side also keeps a connection that only one object records.
    """
    return len(
        {
            conn.key
            for obj in objects
            if obj.connections
            for conn in (*obj.connections.inbound, *obj.connections.outbound)
        }
    )


def _print_objects_table(app_name: str, entries: list[dict], totals: dict) -> None:
    table = Table(title=f"[bold cyan]{escape(app_name)}[/bold cyan] - Objects")
    table.add_column("Key", style="dim")
    table.add_column("Name", style="bold cyan")
    table.add_column("Rows", justify="right", style="magenta")
    table.add_column("Fields", justify="right", style="yellow")
    table.add_column("Ca", justify="right", style="blue")  # Afferent (inbound)
    table.add_column("Ce", justify="right", style="red")  # Efferent (outbound)
    table.add_column("Total", justify="right", style="green")
    table.add_column("I", justify="right", style="cyan")  # Instability: Ce / (Ca + Ce)

    for entry in entries:
        table.add_row(
            # Text cells are printed as they are. Escaped markup is not quite
            # that: Rich doubles a trailing backslash it has no tag after.
            Text(entry["key"]),
            Text(entry["name"]),
            f"{entry['rows']:,}",
            str(entry["fields"]),
            str(entry["ca"]),
            str(entry["ce"]),
            str(entry["total_connections"]),
            f"{entry['instability']:.2f}" if entry["instability"] is not None else "-",
        )

    console.print()
    console.print(table)
    console.print()
    console.print(
        f"[dim]Total: {totals['objects']} objects | "
        f"{totals['rows']:,} rows | "
        f"{totals['fields']} fields | "
        f"Ca: {totals['ca']} | Ce: {totals['ce']} | "
        f"{totals['connections']} connections[/dim]"
    )
    console.print()


@cli.command(name="list-objects")
def list_objects(
    file_path: MetadataFile = None,
    app_id: AppId = None,
    refresh: Refresh = False,
    sort_by_rows: Annotated[
        bool,
        typer.Option(
            "--sort-by-rows",
            help="Sort by row count (largest first) instead of by name",
        ),
    ] = False,
    output_format: RichOrJson = "rich",
):
    """
    List all objects in a Knack application with field and connection counts.


    Shows a table with:

    - Object key and name

    - Number of rows (records)

    - Number of fields

    - Ca (Afferent coupling): Number of inbound connections (other objects depend on this)

    - Ce (Efferent coupling): Number of outbound connections (this object depends on others)

    - Total connections (Ca + Ce)

    - I (Instability): Ce / (Ca + Ce), from 0 (stable, depended-upon) to 1 (unstable, dependent)


    You can either:

    1. Provide a local JSON file: knack-sleuth list-objects path/to/file.json

    2. Fetch from API: knack-sleuth list-objects --app-id YOUR_APP_ID

    3. Use environment variables: KNACK_APP_ID (no API key needed - metadata is public)


    When fetching from API, data is automatically cached locally and reused for 24 hours.
    Use --refresh to force fetching fresh data from the API.
    """
    validate_output_format(output_format)
    app = load_app_metadata(file_path, app_id, refresh).application

    if sort_by_rows:
        # Largest first, then by name as tiebreaker
        objects = sorted(
            app.objects, key=lambda o: (-app.counts.get(o.key, 0), o.name.lower())
        )
    else:
        objects = sorted(app.objects, key=lambda o: o.name.lower())

    entries = [_object_entry(obj, app.counts) for obj in objects]
    totals = {
        "objects": len(entries),
        "rows": sum(e["rows"] for e in entries),
        "fields": sum(e["fields"] for e in entries),
        "ca": sum(e["ca"] for e in entries),
        "ce": sum(e["ce"] for e in entries),
        "connections": _connection_count(app.objects),
    }

    if output_format == "json":
        payload = {"application": app.name, "objects": entries, "totals": totals}
        typer.echo(json.dumps(payload, indent=2))
        return

    _print_objects_table(app.name, entries, totals)


# --- search-object ------------------------------------------------------------


def _field_usages_payload(sleuth: KnackSleuth, field_usage_map: dict) -> dict:
    payload = {}
    for field_key, usages in field_usage_map.items():
        _, field_info = sleuth.get_field_info(field_key)
        payload[field_key] = {
            "name": field_info.name if field_info else None,
            "type": field_info.type if field_info else None,
            "usages": [asdict(u) for u in usages],
        }
    return payload


def _print_field_usages(sleuth: KnackSleuth, field_usage_map: dict) -> None:
    if not field_usage_map:
        console.print("\n[dim]No field usages found[/dim]")
        return
    console.print(
        f"\n[bold cyan]Field-level usages:[/bold cyan] {len(field_usage_map)} fields with usages"
    )
    for field_key, usages in field_usage_map.items():
        _, field_info = sleuth.get_field_info(field_key)
        if field_info:
            console.print(
                f"\n  [bold cyan]{escape(field_info.name)}[/bold cyan] ({escape(field_key)}) - {escape(field_info.type)} - {len(usages)} usages"
            )
            print_usages(usages, "    ")


@cli.command(name="search-object")
def search_object(
    object_identifier: Annotated[
        str,
        typer.Argument(help="Object key (e.g., 'object_12') or name to search for"),
    ],
    file_path: MetadataFile = None,
    app_id: AppId = None,
    refresh: Refresh = False,
    show_fields: Annotated[
        bool, typer.Option("--show-fields/--no-fields", help="Show field-level usages")
    ] = True,
    output_format: RichOrJson = "rich",
):
    """
    Search for all usages of an object in a Knack application.

    This will find where the object is used in connections, views, and other places.
    By default, it also cascades to show usages of all fields in the object.


    You can either:

    1. Provide a local JSON file: knack-sleuth search-object object_12 path/to/file.json

    2. Fetch from API: knack-sleuth search-object object_12 --app-id YOUR_APP_ID

    3. Use environment variables: KNACK_APP_ID (no API key needed - metadata is public)


    When fetching from API, data is automatically cached locally and reused for 24 hours.
    Use --refresh to force fetching fresh data from the API.
    """
    validate_output_format(output_format)
    app_export = load_app_metadata(file_path, app_id, refresh)
    sleuth = KnackSleuth(app_export)
    target = resolve_object_or_exit(app_export, object_identifier)

    results = sleuth.search_object(target.key)
    object_usages = results.get("object_usages", [])
    field_usage_map = (
        {k: v for k, v in results.items() if k.startswith("field_")}
        if show_fields
        else {}
    )

    scenes_to_review = scene_keys_of(object_usages)
    for usages in field_usage_map.values():
        scenes_to_review |= scene_keys_of(usages)

    if output_format == "json":
        payload = {
            "object": {
                "key": target.key,
                "name": target.name,
                "field_count": len(target.fields),
            },
            "object_usages": [asdict(u) for u in object_usages],
            "field_usages": _field_usages_payload(sleuth, field_usage_map),
            "scenes_to_review": sorted(scenes_to_review),
        }
        typer.echo(json.dumps(payload, indent=2))
        return

    console.print(
        Panel(
            f"[bold cyan]{escape(target.name)}[/bold cyan] ({escape(target.key)})",
            title="Object Search Results",
            subtitle=f"{len(target.fields)} fields",
        )
    )

    console.print(f"\n[bold cyan]Object-level usages:[/bold cyan] {len(object_usages)}")
    if object_usages:
        print_usages(object_usages)
    else:
        console.print("  [dim]No direct object usages found[/dim]")

    if show_fields:
        _print_field_usages(sleuth, field_usage_map)

    print_builder_pages(app_export, scenes_to_review)
    console.print()


# --- search-field -------------------------------------------------------------


@cli.command(name="search-field")
def search_field(
    field_identifier: Annotated[
        str,
        typer.Argument(help="Field key (e.g., 'field_116') or name to search for"),
    ],
    file_path: MetadataFile = None,
    app_id: AppId = None,
    refresh: Refresh = False,
    output_format: RichOrJson = "rich",
):
    """
    Search for all usages of a single field in a Knack application.

    This finds where the field is used in views, columns, sorts, formulas,
    connections, and other places — without cascading through the whole
    parent object like search-object does.


    Field names are not unique across objects. If a name matches multiple
    fields, all candidates are listed so you can re-run with the field key.


    You can either:

    1. Provide a local JSON file: knack-sleuth search-field field_116 path/to/file.json

    2. Fetch from API: knack-sleuth search-field field_116 --app-id YOUR_APP_ID

    3. Use environment variables: KNACK_APP_ID (no API key needed - metadata is public)


    Examples:

        knack-sleuth search-field field_116 my_app.json

        knack-sleuth search-field "Organization ID" --app-id YOUR_APP_ID
    """
    validate_output_format(output_format)
    app_export = load_app_metadata(file_path, app_id, refresh)

    matches = resolve_fields(app_export.application, field_identifier)
    if not matches:
        err_console.print(
            f"[red]Error:[/red] Field '{escape(field_identifier)}' not found in application"
        )
        print_suggestions(suggest_field_names(app_export.application, field_identifier))
        raise typer.Exit(1)
    if len(matches) > 1:
        exit_ambiguous_field(field_identifier, matches)

    target_object, target_field = matches[0]
    usages = KnackSleuth(app_export).search_field(target_field.key)
    scenes_to_review = scene_keys_of(usages)

    if output_format == "json":
        payload = {
            "field": {
                "key": target_field.key,
                "name": target_field.name,
                "type": target_field.type,
                "object_key": target_object.key,
                "object_name": target_object.name,
            },
            "usages": [asdict(u) for u in usages],
            "scenes_to_review": sorted(scenes_to_review),
        }
        typer.echo(json.dumps(payload, indent=2))
        return

    console.print(
        Panel(
            f"[bold cyan]{escape(target_object.name)} → {escape(target_field.name)}[/bold cyan] ({escape(target_field.key)})",
            title="Field Search Results",
            subtitle=f"type: {escape(target_field.type)}",
        )
    )

    console.print(f"\n[bold cyan]Usages:[/bold cyan] {len(usages)}")
    if usages:
        print_usages(usages)
    else:
        console.print("  [dim]No usages found — this field may be an orphan[/dim]")

    print_builder_pages(app_export, scenes_to_review)
    console.print()


# --- show-coupling ------------------------------------------------------------

# (heading, "has some" suffix, "has some" explanation, "has none" explanation, arrow)
_AFFERENT = (
    "Afferent Coupling (Ca)",
    "objects depend on this",
    "Objects that have connections pointing TO this object",
    "No objects depend on this object",
    "←",
)
_EFFERENT = (
    "Efferent Coupling (Ce)",
    "objects this depends on",
    "Objects that this object connects TO",
    "This object does not depend on other objects",
    "→",
)


def _print_coupling_side(connections: list, objects_by_key: dict, side: tuple) -> None:
    heading, suffix, explain, explain_none, arrow = side
    inbound = side is _AFFERENT
    if not connections:
        console.print(f"\n[bold cyan]{heading}:[/bold cyan] 0 objects")
        console.print(f"[dim]{explain_none}[/dim]")
        return

    console.print(f"\n[bold cyan]{heading}:[/bold cyan] {len(connections)} {suffix}")
    console.print(f"[dim]{explain}; cardinality reads from this object[/dim]\n")
    for conn in sorted(
        connections,
        key=lambda c: getattr(objects_by_key.get(c.object), "name", ""),
    ):
        related = objects_by_key.get(conn.object)
        if related:
            relationship = conn.relationship_type(from_connected=inbound)
            console.print(
                f"  [yellow]{arrow}[/yellow] [bold cyan]{escape(related.name)}[/bold cyan] ({escape(conn.object)})\n"
                f"     via [dim]{escape(conn.name)}[/dim] ({escape(conn.key)}) \\[{relationship}]"
            )


def _connection_payload(conn, objects_by_key: dict, *, inbound: bool) -> dict:
    related = objects_by_key.get(conn.object)
    return {
        "object_key": conn.object,
        "object_name": related.name if related else None,
        "connection_key": conn.key,
        "connection_name": conn.name,
        "has": conn.has,
        "belongs_to": conn.belongs_to,
        # From this object to object_key, as in the rich output.
        "relationship_type": conn.relationship_type(from_connected=inbound),
    }


@cli.command(name="show-coupling")
def show_coupling(
    object_identifier: Annotated[
        str,
        typer.Argument(help="Object key (e.g., 'object_12') or name to search for"),
    ],
    file_path: MetadataFile = None,
    app_id: AppId = None,
    refresh: Refresh = False,
    output_format: RichOrJson = "rich",
):
    """
    Show coupling relationships for a specific object.


    Displays:

    - Afferent Coupling (Ca): Objects that depend on this object (inbound connections)

    - Efferent Coupling (Ce): Objects this object depends on (outbound connections)


    This provides a focused view of an object's dependencies from its perspective.


    Note: The Knack metadata endpoint is public and does not require an API key.
    """
    validate_output_format(output_format)
    app_export = load_app_metadata(file_path, app_id, refresh)
    target = resolve_object_or_exit(app_export, object_identifier)

    inbound = (target.connections.inbound if target.connections else None) or []
    outbound = (target.connections.outbound if target.connections else None) or []
    ca, ce = len(inbound), len(outbound)
    objects_by_key = {obj.key: obj for obj in app_export.application.objects}

    if output_format == "json":
        payload = {
            "object": {"key": target.key, "name": target.name},
            "ca": ca,
            "ce": ce,
            "instability": round(ce / (ca + ce), 2) if (ca + ce) else None,
            "inbound": [
                _connection_payload(c, objects_by_key, inbound=True) for c in inbound
            ],
            "outbound": [
                _connection_payload(c, objects_by_key, inbound=False) for c in outbound
            ],
        }
        typer.echo(json.dumps(payload, indent=2))
        return

    instability = f"{ce / (ca + ce):.2f}" if (ca + ce) else "-"
    console.print()
    console.print(
        Panel(
            f"[bold cyan]{escape(target.name)}[/bold cyan] ({escape(target.key)})",
            title="Object Coupling",
            subtitle=f"Ca: {ca} | Ce: {ce} | I: {instability}",
        )
    )
    _print_coupling_side(inbound, objects_by_key, _AFFERENT)
    _print_coupling_side(outbound, objects_by_key, _EFFERENT)
    console.print()
