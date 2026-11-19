"""find-orphans: fields, objects and views that are defined but never reached."""

import json
from dataclasses import dataclass
from typing import Annotated

import typer
from rich.markup import escape
from rich.style import Style
from rich.table import Table
from rich.text import Text

from knack_sleuth.config import Settings
from knack_sleuth.core import builder_url
from knack_sleuth.models import Application
from knack_sleuth.sleuth import KnackSleuth

from ._common import cli, console, load_app_metadata, validate_output_format
from ._options import AppId, MetadataFile, Refresh, RichOrJson


@dataclass
class _Orphans:
    all_fields: list  # (object, field) pairs, system fields included
    fields: list  # the pairs to report, sorted by object then field name
    objects: list
    views: list
    dangling_keys: list
    stale_rules: list

    @property
    def hidden_system_count(self) -> int:
        return len(self.all_fields) - len(self.fields)


def _collect(sleuth: KnackSleuth, include_system: bool) -> _Orphans:
    with console.status("[cyan]Analyzing field and object usages..."):
        all_fields = sleuth.find_orphaned_fields()
        return _Orphans(
            all_fields=all_fields,
            fields=sorted(
                (
                    (o, f)
                    for o, f in all_fields
                    if include_system or not f.isSystemField
                ),
                key=lambda pair: (pair[0].name.lower(), pair[1].name.lower()),
            ),
            objects=sorted(
                sleuth.find_orphaned_objects(), key=lambda o: o.name.lower()
            ),
            views=sleuth.find_orphaned_views(),
            dangling_keys=sleuth.find_dangling_layout_keys(),
            stale_rules=sleuth.find_stale_view_rule_references(),
        )


def _field_notes(obj, field) -> list[str]:
    notes = []
    if obj.identifier == field.key:
        notes.append("identifier")
    if field.isSystemField:
        notes.append("system")
    if field.required:
        notes.append("required")
    return notes


def _view_url(app: Application, orphan) -> str:
    return builder_url(
        app,
        orphan.scene.key,
        view_key=orphan.view.key,
        view_type=orphan.view.type,
        next_gen=Settings().knack_next_gen_builder,
    )


def _payload(orphans: _Orphans, app: Application) -> dict:
    fields = [
        {
            "object_key": obj.key,
            "object_name": obj.name,
            "field_key": field.key,
            "field_name": field.name,
            "type": field.type,
            "notes": _field_notes(obj, field),
        }
        for obj, field in orphans.fields
    ]
    objects = [
        {
            "key": obj.key,
            "name": obj.name,
            "field_count": len(obj.fields),
            "rows": app.counts.get(obj.key, 0),
        }
        for obj in orphans.objects
    ]
    views = [
        {
            "scene_key": orphan.scene.key,
            "scene_name": orphan.scene.name,
            "view_key": orphan.view.key,
            "view_name": orphan.view.name,
            "view_type": orphan.view.type,
            "builder_url": _view_url(app, orphan),
        }
        for orphan in orphans.views
    ]
    dangling = [
        {
            "scene_key": item.scene.key,
            "scene_name": item.scene.name,
            "view_key": item.view_key,
            "moved_to": item.moved_to,
            "cause": "moved" if item.moved_to else "deleted",
        }
        for item in orphans.dangling_keys
    ]
    stale = [
        {
            "scene_key": item.scene.key,
            "scene_name": item.scene.name,
            "rule_path": item.rule_path,
            "view_key": item.view_key,
            "reason": item.reason,
        }
        for item in orphans.stale_rules
    ]
    return {
        "orphaned_fields": fields,
        "orphaned_objects": objects,
        "orphaned_views": views,
        "dangling_layout_keys": dangling,
        "stale_view_rule_references": stale,
        "totals": {
            "orphaned_fields": len(fields),
            "orphaned_fields_including_hidden": len(orphans.all_fields),
            "orphaned_objects": len(objects),
            "hidden_system_fields": orphans.hidden_system_count,
            "orphaned_views": len(views),
            "dangling_layout_keys": len(dangling),
            "stale_view_rule_references": len(stale),
        },
    }


def _print_fields(orphans: _Orphans, app_name: str) -> None:
    console.print()
    if orphans.fields:
        table = Table(
            title=f"[bold cyan]{escape(app_name)}[/bold cyan] - Orphaned Fields"
        )
        table.add_column("Object", style="bold cyan")
        table.add_column("Field", style="yellow")
        table.add_column("Key", style="dim")
        table.add_column("Type", style="magenta")
        table.add_column("Notes", style="dim")
        for obj, field in orphans.fields:
            table.add_row(
                escape(obj.name),
                escape(field.name),
                field.key,
                escape(field.type),
                ", ".join(_field_notes(obj, field)),
            )
        console.print(table)
    else:
        console.print("[green]✓[/green] No orphaned fields found")

    if orphans.hidden_system_count:
        console.print(
            f"[dim]({orphans.hidden_system_count} orphaned system fields hidden — "
            f"use --include-system to show them)[/dim]"
        )


def _print_objects(orphans: _Orphans, app: Application) -> None:
    console.print()
    if not orphans.objects:
        console.print("[green]✓[/green] No orphaned objects found")
        return
    console.print(f"[bold cyan]Orphaned Objects:[/bold cyan] {len(orphans.objects)}")
    for obj in orphans.objects:
        row_count = app.counts.get(obj.key, 0)
        console.print(
            f"  [yellow]•[/yellow] [bold cyan]{escape(obj.name)}[/bold cyan] ({obj.key}) - "
            f"{len(obj.fields)} fields, {row_count:,} rows"
        )


def _print_views(orphans: _Orphans, app: Application) -> None:
    console.print()
    if not orphans.views:
        console.print("[green]✓[/green] No orphaned views found")
        return
    table = Table(title=f"[bold cyan]{escape(app.name)}[/bold cyan] - Orphaned Views")
    table.add_column("Scene", style="bold cyan")
    table.add_column("View", style="yellow")
    table.add_column("Key", style="dim")
    table.add_column("Type", style="magenta")
    table.add_column("Builder", style="dim")
    for orphan in orphans.views:
        table.add_row(
            escape(orphan.scene.name),
            escape(orphan.view.name),
            orphan.view.key,
            escape(orphan.view.type),
            # A Text, not [link=...] markup: a "[" in the URL would break the tag.
            Text("open", style=Style(link=_view_url(app, orphan))),
        )
    console.print(table)
    console.print(
        "[dim]These views are defined but left out of the page layout, so they "
        "never render. There is no API to delete them — open the builder link "
        "and remove the view there.[/dim]"
    )


def _print_layout_defects(orphans: _Orphans) -> None:
    if orphans.dangling_keys:
        console.print()
        console.print(
            f"[bold cyan]Dangling Layout Keys:[/bold cyan] {len(orphans.dangling_keys)}"
        )
        for item in orphans.dangling_keys:
            where = (
                f"now on {escape(item.moved_to)}"
                if item.moved_to
                else "view no longer exists"
            )
            console.print(
                f"  [yellow]•[/yellow] [bold cyan]{escape(item.scene.name)}[/bold cyan] "
                f"({item.scene.key}) references {escape(item.view_key)} — {where}"
            )

    if orphans.stale_rules:
        console.print()
        console.print(
            f"[bold cyan]Stale View Rule References:[/bold cyan] {len(orphans.stale_rules)}"
        )
        for item in orphans.stale_rules:
            console.print(
                f"  [yellow]•[/yellow] [bold cyan]{escape(item.scene.name)}[/bold cyan] "
                f"({item.scene.key}) {escape(item.rule_path)} → {escape(item.view_key)} "
                f"[dim]({escape(item.reason)})[/dim]"
            )


def _print_totals(orphans: _Orphans) -> None:
    hidden = orphans.hidden_system_count
    console.print()
    console.print(
        # Count what the table above actually showed; hidden system fields are
        # called out separately so the two numbers never silently disagree.
        f"[dim]Total: {len(orphans.fields)} orphaned fields"
        + (f" (+{hidden} hidden system)" if hidden else "")
        + f" | {len(orphans.objects)} orphaned objects"
        + f" | {len(orphans.views)} orphaned views[/dim]"
    )
    console.print(
        "[dim]Review before deleting: identifier/system fields can be orphans by design[/dim]"
    )
    console.print()


@cli.command(name="find-orphans")
def find_orphans(
    file_path: MetadataFile = None,
    app_id: AppId = None,
    refresh: Refresh = False,
    include_system: Annotated[
        bool,
        typer.Option(
            "--include-system",
            help="Include Knack system fields in the orphaned fields list",
        ),
    ] = False,
    output_format: RichOrJson = "rich",
):
    """
    List orphaned fields, objects, and views — defined but never reached.

    An orphaned field has no usages in views, columns, sorts, formulas, or
    connections. An orphaned object has no connections and no views displaying
    it (user profile objects are excluded — they are referenced through Knack's
    auth system).

    An orphaned view is defined on a scene but left out of that scene's page
    layout, so Knack never draws it. Login views are excluded (they render from
    the scene chrome), as are scenes with no layout at all (Knack leaves
    `groups` empty on the child pages it generates for Edit/Details links).
    Each orphan gets a builder deep link — the view is not on the canvas, so
    there is nothing to click without one, and Knack's API cannot delete views.

    Two related defects are reported alongside: dangling layout keys (a layout
    slot naming a view that is not on the scene, either moved or deleted) and
    stale view rule references (a rule targeting an orphaned or missing view).

    A reference that lives only in an orphaned view no longer counts as a
    usage, so it cannot keep a dead field or object looking alive. The
    reference is still listed by search-field, tagged `orphaned_view`.


    app-summary's technical debt section counts every orphan, including
    hidden system fields; this command lists the actionable ones. Use
    --format json for both counts.


    Note: identifier fields and system fields can legitimately show up here —
    review before deleting anything.


    Examples:

        knack-sleuth find-orphans my_app.json

        knack-sleuth find-orphans --app-id YOUR_APP_ID

        knack-sleuth find-orphans my_app.json --include-system
    """
    validate_output_format(output_format)
    app_export = load_app_metadata(file_path, app_id, refresh)
    app = app_export.application
    orphans = _collect(KnackSleuth(app_export), include_system)

    if output_format == "json":
        typer.echo(json.dumps(_payload(orphans, app), indent=2))
        return

    _print_fields(orphans, app.name)
    _print_objects(orphans, app)
    _print_views(orphans, app)
    _print_layout_defects(orphans)
    _print_totals(orphans)
