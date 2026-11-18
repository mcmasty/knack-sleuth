"""Metadata snapshots: download-metadata and diff."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel

from knack_sleuth.diff import diff_applications, diff_to_markdown

from ._common import (
    cli,
    console,
    emit,
    exit_on_error,
    fail,
    file_size_kb,
    load_app_metadata,
    load_by_app_id,
    require_app_id,
    validate_choice,
)
from ._options import AppId, Refresh

# --- download-metadata --------------------------------------------------------


def _print_saved(output_file: Path, data: dict) -> None:
    application = data.get("application", {})
    console.print()
    console.print(f"[green]✓[/green] Metadata saved to [bold]{output_file}[/bold]")
    console.print(f"[dim]  File size: {file_size_kb(output_file)}[/dim]")
    console.print(f"[dim]  App: {application.get('name', 'Unknown')}[/dim]")
    console.print(
        f"[dim]  Objects: {len(application.get('objects', []))} | "
        f"Scenes: {len(application.get('scenes', []))}[/dim]"
    )
    console.print()


@cli.command(name="download-metadata")
def download_metadata(
    output_file: Annotated[
        Path | None,
        typer.Argument(help="Output file path (default: {APP_ID}_metadata.json)"),
    ] = None,
    app_id: AppId = None,
    refresh: Refresh = False,
):
    """
    Download and save Knack application metadata to a local file.


    This is useful for:

    - Creating a backup of your app structure

    - Working offline with the metadata

    - Sharing app structure with others

    - Version control / tracking changes over time


    The file will be saved as formatted JSON (indented) for easy reading.


    Examples:

        knack-sleuth download-metadata                    # Uses default filename

        knack-sleuth download-metadata my_backup.json     # Custom filename

        knack-sleuth download-metadata --refresh          # Force fresh download
    """
    final_app_id = require_app_id(app_id)
    output_file = output_file or Path(f"{final_app_id}_metadata.json")

    # Same cache-then-API path as every other command, so a download also
    # refreshes the cache. The raw dict is saved as-is, without validation.
    data = load_by_app_id(final_app_id, refresh, dict)

    with exit_on_error("Failed to save file: "):
        with output_file.open("w") as f:
            json.dump(data, f, indent=2)
        _print_saved(output_file, data)


# --- diff ---------------------------------------------------------------------

DIFF_FORMATS = ("rich", "json", "markdown")


def _render_changes(entry: dict) -> str:
    changes = "; ".join(
        f"{attr}: {c['old']!r} → {c['new']!r}" for attr, c in entry["changes"].items()
    )
    return f"{entry['name']} ({entry['key']}) — {changes}"


def _render_object(e: dict) -> str:
    return (
        f"[bold cyan]{e['name']}[/bold cyan] ({e['key']}) — {e['field_count']} fields"
    )


def _render_field(e: dict) -> str:
    return f"{e['object_name']} → [bold cyan]{e['name']}[/bold cyan] ({e['key']}, {e['type']})"


def _render_scene(e: dict) -> str:
    return f"[bold cyan]{e['name']}[/bold cyan] ({e['key']}, /{e['slug']}) — {e['view_count']} views"


def _render_view(e: dict) -> str:
    return f"{e['scene_name']} → [bold cyan]{e['name']}[/bold cyan] ({e['key']}, {e['type']})"


def _render_rename(e: dict) -> str:
    return f"{e['key']}: {e['old_name']} → {e['new_name']}"


_ADDED, _REMOVED, _CHANGED = ("+", "green"), ("-", "red"), ("~", "yellow")

# (title, section, kind, renderer, style), in print order
_DIFF_SECTIONS: list[tuple[str, str, str, Callable[[dict], str], tuple[str, str]]] = [
    ("Objects Added", "objects", "added", _render_object, _ADDED),
    ("Objects Removed", "objects", "removed", _render_object, _REMOVED),
    ("Objects Renamed", "objects", "renamed", _render_rename, _CHANGED),
    ("Fields Added", "fields", "added", _render_field, _ADDED),
    ("Fields Removed", "fields", "removed", _render_field, _REMOVED),
    (
        "Fields Changed",
        "fields",
        "changed",
        lambda e: f"{e['object_name']} → {_render_changes(e)}",
        _CHANGED,
    ),
    ("Scenes Added", "scenes", "added", _render_scene, _ADDED),
    ("Scenes Removed", "scenes", "removed", _render_scene, _REMOVED),
    ("Scenes Renamed", "scenes", "renamed", _render_rename, _CHANGED),
    ("Views Added", "views", "added", _render_view, _ADDED),
    ("Views Removed", "views", "removed", _render_view, _REMOVED),
    (
        "Views Changed",
        "views",
        "changed",
        lambda e: f"{e['scene_name']} → {_render_changes(e)}",
        _CHANGED,
    ),
]


def _print_diff_rich(diff_result: dict, old_file: Path, new_file: Path | None) -> None:
    """Render a diff result to the console with Rich formatting."""
    summary = diff_result["summary"]
    new_label = new_file.name if new_file else "live API"

    console.print()
    console.print(
        Panel(
            f"[bold cyan]{old_file.name}[/bold cyan] → [bold cyan]{new_label}[/bold cyan]",
            title="Metadata Diff",
            subtitle=f"{summary['new_app_name']}",
        )
    )

    old_c, new_c = summary["old_counts"], summary["new_counts"]
    console.print(
        f"[dim]Objects: {old_c['objects']} → {new_c['objects']} | "
        f"Fields: {old_c['fields']} → {new_c['fields']} | "
        f"Scenes: {old_c['scenes']} → {new_c['scenes']} | "
        f"Views: {old_c['views']} → {new_c['views']}[/dim]"
    )

    if not diff_result["has_changes"]:
        console.print("\n[green]✓[/green] No structural changes detected")
        console.print()
        return

    if summary["old_app_name"] != summary["new_app_name"]:
        console.print(
            f"\n[yellow]~[/yellow] Application renamed: "
            f"{summary['old_app_name']} → {summary['new_app_name']}"
        )

    for title, section, kind, render, (marker, color) in _DIFF_SECTIONS:
        entries = diff_result[section][kind]
        if not entries:
            continue
        console.print(f"\n[bold cyan]{title}:[/bold cyan] {len(entries)}")
        for entry in entries:
            console.print(f"  [{color}]{marker}[/{color}] {render(entry)}")

    console.print()


@cli.command(name="diff")
def diff(
    old_file: Annotated[
        Path, typer.Argument(help="Older metadata snapshot (JSON file)")
    ],
    new_file: Annotated[
        Path | None,
        typer.Argument(
            help="Newer metadata snapshot (JSON file). Omit to compare against the live API "
            "(requires --app-id or KNACK_APP_ID)",
        ),
    ] = None,
    app_id: Annotated[
        str | None,
        typer.Option(
            "--app-id",
            help="Knack application ID for live comparison (can also use KNACK_APP_ID env var)",
        ),
    ] = None,
    refresh: Annotated[
        bool,
        typer.Option(
            "--refresh",
            help="Force refresh cached API data (only applies to live comparison)",
        ),
    ] = False,
    output_format: Annotated[
        str, typer.Option("--format", help="Output format: rich, json, or markdown")
    ] = "rich",
    output_file: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Save output to file (requires --format json or markdown)",
        ),
    ] = None,
    exit_code: Annotated[
        bool,
        typer.Option(
            "--exit-code",
            help="Exit with code 1 if differences were found (like git diff)",
        ),
    ] = False,
):
    """
    Compare two metadata snapshots and report structural changes.

    Entities are matched by their stable Knack keys, so a rename shows up as a
    rename — not as a removal plus an addition. Detects:


    - Objects: added, removed, renamed

    - Fields: added, removed, changed (name, type, required, unique, connection relationship)

    - Scenes: added, removed, renamed

    - Views: added, removed, changed (name, type)


    Noise rules: fields of an added/removed object (and views of an
    added/removed scene) are not repeated in the field/view sections — the
    object/scene entry covers them. Record counts are data, not structure,
    and are excluded.


    Examples:

        # Compare two snapshots
        knack-sleuth diff backup_january.json backup_june.json

        # Compare a snapshot against the live app
        knack-sleuth diff backup_january.json --app-id YOUR_APP_ID

        # Machine-readable output, exit 1 when something changed (CI-friendly)
        knack-sleuth diff old.json new.json --format json --exit-code

        # Markdown change report
        knack-sleuth diff old.json new.json --format markdown -o changes.md
    """
    validate_choice(output_format, DIFF_FORMATS)
    if output_file and output_format == "rich":
        fail("--output requires --format json or markdown")

    # Load both sides (file vs file, or file vs API when new_file is omitted)
    old_export = load_app_metadata(old_file, None, False)
    new_export = (
        load_app_metadata(new_file, None, False)
        if new_file
        else load_app_metadata(None, app_id, refresh)
    )

    diff_result = diff_applications(old_export.application, new_export.application)

    if output_format == "rich":
        _print_diff_rich(diff_result, old_file, new_file)
    elif output_format == "json":
        emit(json.dumps(diff_result, indent=2), output_file, "Diff")
    else:
        emit(diff_to_markdown(diff_result), output_file, "Diff")

    if exit_code and diff_result["has_changes"]:
        raise typer.Exit(1)
