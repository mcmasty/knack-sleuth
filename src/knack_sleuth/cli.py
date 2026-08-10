from dataclasses import asdict
from importlib import resources
from pathlib import Path
from typing import Optional
import json
import re

import httpx

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from knack_sleuth import __version__
from knack_sleuth.models import KnackAppMetadata, KnackObject
from knack_sleuth.sleuth import KnackSleuth
from knack_sleuth.config import Settings, KNACK_BUILDER_BASE_URL, KNACK_NG_BUILDER_BASE_URL
from knack_sleuth.core import (
    load_app_metadata as core_load_metadata,
    find_valid_cache,
    fetch_metadata_from_api,
    get_cache_dir,
    write_cache,
)
from knack_sleuth.lookup import (
    resolve_object,
    resolve_fields,
    suggest_object_names,
    suggest_field_names,
)

cli = typer.Typer()
console = Console()
err_console = Console(stderr=True)  # status + error output; keeps stdout clean for data

cache_app = typer.Typer(help="Inspect and manage the local metadata cache.")
cli.add_typer(cache_app, name="cache")


def _cache_files(app_id: Optional[str] = None) -> list[Path]:
    """All cache files (optionally for one app), newest first."""
    pattern = f"{app_id}_app_metadata_*.json" if app_id else "*_app_metadata_*.json"
    return sorted(get_cache_dir().glob(pattern), reverse=True)


@cache_app.command("dir")
def cache_dir():
    """Print the cache directory path."""
    typer.echo(str(get_cache_dir()))


@cache_app.command("list")
def cache_list(
    app_id: Optional[str] = typer.Option(
        None, "--app-id", help="Only show cache files for this application ID"
    ),
):
    """List cached metadata files with age, size, and freshness."""
    from datetime import datetime, timedelta

    files = _cache_files(app_id)
    if not files:
        console.print(f"[dim]No cache files in {get_cache_dir()}[/dim]")
        return

    ttl = timedelta(hours=Settings().knack_cache_ttl_hours)

    table = Table(title=f"Metadata Cache — {get_cache_dir()}")
    table.add_column("File", style="bold cyan")
    table.add_column("App ID", style="dim")
    table.add_column("Age", justify="right", style="magenta")
    table.add_column("Size", justify="right", style="yellow")
    table.add_column("Status", style="green")

    for path in files:
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        age_hours = age.total_seconds() / 3600
        file_app_id = path.name.split("_app_metadata_")[0]
        status = "fresh" if age < ttl else "[red]stale[/red]"
        table.add_row(
            path.name,
            file_app_id,
            f"{age_hours:.1f}h",
            f"{path.stat().st_size / 1024:.1f} KB",
            status,
        )

    console.print()
    console.print(table)
    console.print(
        f"[dim]{len(files)} files | TTL: {ttl.total_seconds() / 3600:.0f}h "
        f"(set KNACK_CACHE_TTL_HOURS to change)[/dim]"
    )
    console.print()


@cache_app.command("clear")
def cache_clear(
    app_id: Optional[str] = typer.Option(
        None, "--app-id", help="Only delete cache files for this application ID"
    ),
):
    """Delete cached metadata files (all apps, or one with --app-id)."""
    files = _cache_files(app_id)
    if not files:
        console.print(f"[dim]No cache files to delete in {get_cache_dir()}[/dim]")
        return

    freed = 0
    for path in files:
        freed += path.stat().st_size
        path.unlink()

    scope = f"for app {app_id}" if app_id else "from cache"
    console.print(
        f"[green]✓[/green] Deleted {len(files)} cache files {scope} "
        f"({freed / 1024:.1f} KB freed)"
    )


def version_callback(value: bool):
    """Display version and exit."""
    if value:
        console.print(f"knack-sleuth version {__version__}")
        raise typer.Exit()


SKILL_VERSION_PATTERN = re.compile(
    r"^<!-- knack-sleuth-version: ([^ ]+) -->$",
    re.MULTILINE,
)


def _release_tuple(version: str) -> tuple[int, ...] | None:
    """Parse a simple numeric release for drift comparisons."""
    parts = version.split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _without_skill_version_stamp(content: str) -> str:
    """Normalize content so the current pre-stamp skill is not called stale.

    The stamp sits between the frontmatter and the body, so dropping just the
    comment leaves the blank line that followed it; collapse that gap too, and
    normalize both sides of a comparison with this so they line up.
    """
    stripped = SKILL_VERSION_PATTERN.sub("", content)
    return re.sub(r"\n{3,}", "\n\n", stripped).lstrip("\n")


def _skill_drift_warning(
    target_file: Path,
    packaged_content: str,
    running_version: str = __version__,
) -> str | None:
    """Return an actionable warning when an installed skill is stale."""
    if not target_file.is_file():
        return None

    try:
        installed_content = target_file.read_text()
    except OSError:
        return None

    match = SKILL_VERSION_PATTERN.search(installed_content)
    if not match:
        if _without_skill_version_stamp(
            installed_content
        ) == _without_skill_version_stamp(packaged_content):
            return None
        return (
            "Installed knack-explorer skill predates version tracking and differs "
            "from this release; run 'knack-sleuth install-skill --force' to update it."
        )

    installed_version = match.group(1)
    installed_release = _release_tuple(installed_version)
    running_release = _release_tuple(running_version)
    if installed_version == running_version:
        return None
    if installed_release and running_release and installed_release >= running_release:
        return None
    return (
        f"Installed knack-explorer skill is from {installed_version}; running "
        f"knack-sleuth is {running_version}. Run 'knack-sleuth install-skill "
        "--force' to update it."
    )


def _warn_if_installed_skill_is_stale() -> None:
    """Warn on stderr without disrupting command output or execution."""
    try:
        packaged_content = (
            resources.files("knack_sleuth").joinpath("data/SKILL.md").read_text()
        )
    except (OSError, TypeError):
        return

    target_file = Path.home() / ".claude" / "skills" / "knack-explorer" / "SKILL.md"
    warning = _skill_drift_warning(target_file, packaged_content)
    if warning:
        err_console.print(f"[yellow]Warning:[/yellow] {warning}")


def load_app_metadata(
    file_path: Optional[Path],
    app_id: Optional[str],
    refresh: bool = False,
) -> KnackAppMetadata:
    """
    CLI wrapper for loading Knack application metadata.

    Adds user-friendly console output and error handling on top of the core
    cache primitives. For library usage, import from knack_sleuth.core instead.

    Note: The Knack metadata endpoint is public and does not require an API key.
    """
    settings = Settings()

    try:
        # File source: load directly, no caching involved.
        if file_path:
            return core_load_metadata(file_path=file_path)

        final_app_id = app_id or settings.knack_app_id
        if not final_app_id:
            raise ValueError(
                "App ID is required. Provide via --app-id or KNACK_APP_ID environment variable."
            )

        # Reuse a fresh cache file unless a refresh was explicitly requested.
        if not refresh:
            cached = find_valid_cache(final_app_id)
            if cached:
                cache_path, cache_age_hours = cached
                try:
                    with cache_path.open() as f:
                        data = json.load(f)
                    err_console.print(
                        f"[dim]Using cached data from {cache_path.name} "
                        f"(age: {cache_age_hours:.1f}h)[/dim]"
                    )
                    return KnackAppMetadata(**data)
                except Exception:
                    # Corrupt/unreadable cache: fall through to a fresh API fetch.
                    err_console.print(
                        f"[yellow]Warning:[/yellow] Failed to read cache "
                        f"{cache_path.name}; fetching fresh data..."
                    )

        if refresh:
            err_console.print("[cyan]Forcing refresh from API...[/cyan]")

        with err_console.status("[cyan]Fetching metadata from Knack API..."):
            data = fetch_metadata_from_api(final_app_id)

        cache_path = write_cache(final_app_id, data)
        err_console.print(f"[dim]Cached metadata to {cache_path.name}[/dim]")
        return KnackAppMetadata(**data)

    except FileNotFoundError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except ValueError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        # Handle httpx errors and other exceptions
        if isinstance(e, httpx.HTTPStatusError):
            err_console.print(f"[red]Error:[/red] HTTP {e.response.status_code}: {e.response.text}")
        elif isinstance(e, httpx.RequestError):
            err_console.print(f"[red]Error:[/red] Failed to connect to Knack API: {e}")
        else:
            err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


def _validate_output_format(output_format: str) -> None:
    """Exit with an error unless the format is rich or json."""
    if output_format not in ("rich", "json"):
        err_console.print(
            f"[red]Error:[/red] Invalid format '{output_format}'. Use rich or json."
        )
        raise typer.Exit(1)


def resolve_object_or_exit(app_export: KnackAppMetadata, identifier: str) -> KnackObject:
    """Resolve an object by key or name, or exit with suggestions."""
    obj = resolve_object(app_export.application, identifier)
    if obj:
        return obj

    err_console.print(f"[red]Error:[/red] Object '{identifier}' not found in application")
    suggestions = suggest_object_names(app_export.application, identifier)
    if suggestions:
        console.print(f"Did you mean: [cyan]{'[/cyan], [cyan]'.join(suggestions)}[/cyan]?")
    raise typer.Exit(1)


def print_builder_pages(app_export: KnackAppMetadata, scenes_to_review: set) -> None:
    """Print clickable Knack builder URLs for a set of scene keys."""
    if not scenes_to_review:
        return

    settings = Settings()
    # Use account slug for builder URLs (not application slug)
    account_slug = app_export.application.account.get('slug', app_export.application.slug)
    base_url = (
        KNACK_NG_BUILDER_BASE_URL if settings.knack_next_gen_builder
        else KNACK_BUILDER_BASE_URL
    )

    console.print(f"\n[bold cyan]Builder Pages to Review:[/bold cyan] {len(scenes_to_review)} scenes")
    console.print()
    for scene_key in sorted(scenes_to_review):
        url = f"{base_url}/{account_slug}/portal/pages/{scene_key}"
        console.print(f"  [link={url}]{url}[/link]")
    console.print()
    console.print("[dim]Tip: Set KNACK_NEXT_GEN_BUILDER=true to use Next-Gen builder URLs[/dim]")


@cli.callback()
def main(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit",
        callback=version_callback,
        is_eager=True,
    ),
):
    """KnackSleuth - Investigate your Knack.app's metadata."""
    if ctx.invoked_subcommand != "install-skill":
        _warn_if_installed_skill_is_stale()


@cli.command(name="list-objects")
def list_objects(
    file_path: Optional[Path] = typer.Argument(
        None, help="Path to Knack application metadata JSON file (optional if using --app-id)"
    ),
    app_id: Optional[str] = typer.Option(
        None, "--app-id", help="Knack application ID (can also use KNACK_APP_ID env var)"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force refresh cached API data (ignore cache)"
    ),
    sort_by_rows: bool = typer.Option(
        False, "--sort-by-rows", help="Sort by row count (largest first) instead of by name"
    ),
    output_format: str = typer.Option(
        "rich", "--format", help="Output format: rich or json"
    ),
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
    _validate_output_format(output_format)

    # Load metadata
    app_export = load_app_metadata(file_path, app_id, refresh)

    # Collect rows and calculate totals
    entries = []
    total_rows = 0
    total_fields = 0
    total_afferent = 0
    total_efferent = 0
    total_connections = 0
    
    # Sort objects based on flag
    if sort_by_rows:
        # Sort by row count (descending), then by name as tiebreaker
        sorted_objects = sorted(
            app_export.application.objects,
            key=lambda o: (-app_export.application.counts.get(o.key, 0), o.name.lower())
        )
    else:
        # Sort by name (default)
        sorted_objects = sorted(app_export.application.objects, key=lambda o: o.name.lower())
    
    for obj in sorted_objects:
        # Get row count from counts dict
        row_count = app_export.application.counts.get(obj.key, 0)
        total_rows += row_count
        
        # Count fields
        field_count = len(obj.fields)
        total_fields += field_count
        
        # Count connections separately
        afferent_count = 0  # Ca: inbound (other objects depend on this)
        efferent_count = 0  # Ce: outbound (this object depends on others)
        if obj.connections:
            afferent_count = len(obj.connections.inbound)
            efferent_count = len(obj.connections.outbound)
        
        connection_count = afferent_count + efferent_count
        total_afferent += afferent_count
        total_efferent += efferent_count
        total_connections += connection_count

        entries.append(
            {
                "key": obj.key,
                "name": obj.name,
                "rows": row_count,
                "fields": field_count,
                "ca": afferent_count,
                "ce": efferent_count,
                "total_connections": connection_count,
                "instability": (
                    round(efferent_count / connection_count, 2)
                    if connection_count
                    else None
                ),
            }
        )

    if output_format == "json":
        payload = {
            "application": app_export.application.name,
            "objects": entries,
            "totals": {
                "objects": len(entries),
                "rows": total_rows,
                "fields": total_fields,
                "ca": total_afferent,
                "ce": total_efferent,
                "connections": total_connections,
            },
        }
        typer.echo(json.dumps(payload, indent=2))
        return

    # Create table
    table = Table(title=f"[bold cyan]{app_export.application.name}[/bold cyan] - Objects")
    table.add_column("Key", style="dim")
    table.add_column("Name", style="bold cyan")
    table.add_column("Rows", justify="right", style="magenta")
    table.add_column("Fields", justify="right", style="yellow")
    table.add_column("Ca", justify="right", style="blue")  # Afferent (inbound)
    table.add_column("Ce", justify="right", style="red")   # Efferent (outbound)
    table.add_column("Total", justify="right", style="green")
    table.add_column("I", justify="right", style="cyan")   # Instability: Ce / (Ca + Ce)

    for entry in entries:
        table.add_row(
            entry["key"],
            entry["name"],
            f"{entry['rows']:,}",  # Format with comma separators
            str(entry["fields"]),
            str(entry["ca"]),
            str(entry["ce"]),
            str(entry["total_connections"]),
            f"{entry['instability']:.2f}" if entry["instability"] is not None else "-",
        )

    # Display table
    console.print()
    console.print(table)
    console.print()
    console.print(
        f"[dim]Total: {len(app_export.application.objects)} objects | "
        f"{total_rows:,} rows | "
        f"{total_fields} fields | "
        f"Ca: {total_afferent} | Ce: {total_efferent} | "
        f"{total_connections} connections[/dim]"
    )
    console.print()


@cli.command(name="search-object")
def search_object(
    object_identifier: str = typer.Argument(
        ..., help="Object key (e.g., 'object_12') or name to search for"
    ),
    file_path: Optional[Path] = typer.Argument(
        None, help="Path to Knack application metadata JSON file (optional if using --app-id)"
    ),
    app_id: Optional[str] = typer.Option(
        None, "--app-id", help="Knack application ID (can also use KNACK_APP_ID env var)"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force refresh cached API data (ignore cache)"
    ),
    show_fields: bool = typer.Option(
        True, "--show-fields/--no-fields", help="Show field-level usages"
    ),
    output_format: str = typer.Option(
        "rich", "--format", help="Output format: rich or json"
    ),
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
    _validate_output_format(output_format)

    # Load metadata
    app_export = load_app_metadata(file_path, app_id, refresh)

    # Create search engine
    sleuth = KnackSleuth(app_export)

    # Find the object (supports both key and name lookup)
    target_object = resolve_object_or_exit(app_export, object_identifier)
    object_identifier = target_object.key

    # Perform search
    results = sleuth.search_object(object_identifier)
    object_usages = results.get("object_usages", [])
    field_usage_map = {k: v for k, v in results.items() if k.startswith("field_")}

    # Collect unique scenes from all usages (for builder links)
    scenes_to_review = set()
    for usage in object_usages:
        if 'scene_key' in usage.details:
            scenes_to_review.add(usage.details['scene_key'])
    if show_fields:
        for usages in field_usage_map.values():
            for usage in usages:
                if 'scene_key' in usage.details:
                    scenes_to_review.add(usage.details['scene_key'])

    if output_format == "json":
        field_usages_payload = {}
        if show_fields:
            for field_key, usages in field_usage_map.items():
                _, field_info = sleuth.get_field_info(field_key)
                field_usages_payload[field_key] = {
                    "name": field_info.name if field_info else None,
                    "type": field_info.type if field_info else None,
                    "usages": [asdict(u) for u in usages],
                }
        payload = {
            "object": {
                "key": target_object.key,
                "name": target_object.name,
                "field_count": len(target_object.fields),
            },
            "object_usages": [asdict(u) for u in object_usages],
            "field_usages": field_usages_payload,
            "scenes_to_review": sorted(scenes_to_review),
        }
        typer.echo(json.dumps(payload, indent=2))
        return

    # Display results
    console.print(
        Panel(
            f"[bold cyan]{target_object.name}[/bold cyan] ({object_identifier})",
            title="Object Search Results",
            subtitle=f"{len(target_object.fields)} fields",
        )
    )

    # Show object-level usages
    console.print(f"\n[bold cyan]Object-level usages:[/bold cyan] {len(object_usages)}")

    if object_usages:
        for usage in object_usages:
            console.print(f"  [yellow]•[/yellow] \\[{usage.location_type}] {usage.context}")
    else:
        console.print("  [dim]No direct object usages found[/dim]")

    # Show field-level usages
    if show_fields:
        field_results = field_usage_map
        if field_results:
            console.print(
                f"\n[bold cyan]Field-level usages:[/bold cyan] {len(field_results)} fields with usages"
            )

            for field_key, usages in field_results.items():
                obj_info, field_info = sleuth.get_field_info(field_key)
                if field_info:
                    console.print(
                        f"\n  [bold cyan]{field_info.name}[/bold cyan] ({field_key}) - {field_info.type} - {len(usages)} usages"
                    )
                    for usage in usages:
                        console.print(f"    [yellow]•[/yellow] \\[{usage.location_type}] {usage.context}")
        else:
            console.print("\n[dim]No field usages found[/dim]")

    print_builder_pages(app_export, scenes_to_review)

    console.print()


@cli.command(name="search-field")
def search_field(
    field_identifier: str = typer.Argument(
        ..., help="Field key (e.g., 'field_116') or name to search for"
    ),
    file_path: Optional[Path] = typer.Argument(
        None, help="Path to Knack application metadata JSON file (optional if using --app-id)"
    ),
    app_id: Optional[str] = typer.Option(
        None, "--app-id", help="Knack application ID (can also use KNACK_APP_ID env var)"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force refresh cached API data (ignore cache)"
    ),
    output_format: str = typer.Option(
        "rich", "--format", help="Output format: rich or json"
    ),
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
    _validate_output_format(output_format)

    # Load metadata
    app_export = load_app_metadata(file_path, app_id, refresh)

    # Resolve the field (key or name)
    matches = resolve_fields(app_export.application, field_identifier)

    if not matches:
        err_console.print(
            f"[red]Error:[/red] Field '{field_identifier}' not found in application"
        )
        suggestions = suggest_field_names(app_export.application, field_identifier)
        if suggestions:
            console.print(f"Did you mean: [cyan]{'[/cyan], [cyan]'.join(suggestions)}[/cyan]?")
        raise typer.Exit(1)

    if len(matches) > 1:
        console.print(
            f"[yellow]Ambiguous:[/yellow] field name '{field_identifier}' matches "
            f"{len(matches)} fields:"
        )
        for obj, field in matches:
            console.print(f"  {field.key} — {obj.name} → {field.name} ({field.type})")
        console.print("\nRe-run with the field key to disambiguate.")
        raise typer.Exit(1)

    target_object, target_field = matches[0]

    # Perform search
    sleuth = KnackSleuth(app_export)
    usages = sleuth.search_field(target_field.key)
    scenes_to_review = {
        usage.details['scene_key'] for usage in usages if 'scene_key' in usage.details
    }

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

    # Display results
    console.print(
        Panel(
            f"[bold cyan]{target_object.name} → {target_field.name}[/bold cyan] ({target_field.key})",
            title="Field Search Results",
            subtitle=f"type: {target_field.type}",
        )
    )

    console.print(f"\n[bold cyan]Usages:[/bold cyan] {len(usages)}")
    if usages:
        for usage in usages:
            console.print(f"  [yellow]•[/yellow] \\[{usage.location_type}] {usage.context}")
    else:
        console.print("  [dim]No usages found — this field may be an orphan[/dim]")

    # Builder Pages to Review
    print_builder_pages(app_export, scenes_to_review)

    console.print()


@cli.command(name="show-coupling")
def show_coupling(
    object_identifier: str = typer.Argument(
        ..., help="Object key (e.g., 'object_12') or name to search for"
    ),
    file_path: Optional[Path] = typer.Argument(
        None, help="Path to Knack application metadata JSON file (optional if using --app-id)"
    ),
    app_id: Optional[str] = typer.Option(
        None, "--app-id", help="Knack application ID (can also use KNACK_APP_ID env var)"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force refresh cached API data (ignore cache)"
    ),
    output_format: str = typer.Option(
        "rich", "--format", help="Output format: rich or json"
    ),
):
    """
    Show coupling relationships for a specific object.


    Displays:

    - Afferent Coupling (Ca): Objects that depend on this object (inbound connections)

    - Efferent Coupling (Ce): Objects this object depends on (outbound connections)


    This provides a focused view of an object's dependencies from its perspective.


    Note: The Knack metadata endpoint is public and does not require an API key.
    """
    _validate_output_format(output_format)

    # Load metadata
    app_export = load_app_metadata(file_path, app_id, refresh)

    # Find the object (supports both key and name lookup)
    target_object = resolve_object_or_exit(app_export, object_identifier)
    object_identifier = target_object.key

    ca = len(target_object.connections.inbound) if target_object.connections else 0
    ce = len(target_object.connections.outbound) if target_object.connections else 0
    instability = f"{ce / (ca + ce):.2f}" if (ca + ce) else "-"

    # Build object lookup for names
    objects_by_key = {obj.key: obj for obj in app_export.application.objects}

    if output_format == "json":
        inbound = target_object.connections.inbound if target_object.connections else []
        outbound = target_object.connections.outbound if target_object.connections else []
        inbound = inbound or []
        outbound = outbound or []

        def _conn_payload(conn):
            related = objects_by_key.get(conn.object)
            return {
                "object_key": conn.object,
                "object_name": related.name if related else None,
                "connection_key": conn.key,
                "connection_name": conn.name,
                "has": conn.has,
                "belongs_to": conn.belongs_to,
            }

        payload = {
            "object": {"key": target_object.key, "name": target_object.name},
            "ca": ca,
            "ce": ce,
            "instability": round(ce / (ca + ce), 2) if (ca + ce) else None,
            "inbound": [_conn_payload(c) for c in inbound],
            "outbound": [_conn_payload(c) for c in outbound],
        }
        typer.echo(json.dumps(payload, indent=2))
        return

    # Display header
    console.print()
    console.print(
        Panel(
            f"[bold cyan]{target_object.name}[/bold cyan] ({object_identifier})",
            title="Object Coupling",
            subtitle=f"Ca: {ca} | Ce: {ce} | I: {instability}",
        )
    )

    # Afferent Coupling (Ca) - Inbound connections
    if target_object.connections and target_object.connections.inbound:
        console.print(f"\n[bold cyan]Afferent Coupling (Ca):[/bold cyan] {len(target_object.connections.inbound)} objects depend on this")
        console.print("[dim]Objects that have connections pointing TO this object[/dim]\n")
        
        for conn in sorted(target_object.connections.inbound, key=lambda c: getattr(objects_by_key.get(c.object), "name", "")):
            source_obj = objects_by_key.get(conn.object)
            if source_obj:
                relationship = f"{conn.has} → {conn.belongs_to}"
                console.print(
                    f"  [yellow]←[/yellow] [bold cyan]{source_obj.name}[/bold cyan] ({conn.object})\n"
                    f"     via [dim]{conn.name}[/dim] ({conn.key}) [{relationship}]"
                )
    else:
        console.print("\n[bold cyan]Afferent Coupling (Ca):[/bold cyan] 0 objects")
        console.print("[dim]No objects depend on this object[/dim]")
    
    # Efferent Coupling (Ce) - Outbound connections
    if target_object.connections and target_object.connections.outbound:
        console.print(f"\n[bold cyan]Efferent Coupling (Ce):[/bold cyan] {len(target_object.connections.outbound)} objects this depends on")
        console.print("[dim]Objects that this object connects TO[/dim]\n")
        
        for conn in sorted(target_object.connections.outbound, key=lambda c: getattr(objects_by_key.get(c.object), "name", "")):
            target_obj = objects_by_key.get(conn.object)
            if target_obj:
                relationship = f"{conn.has} → {conn.belongs_to}"
                console.print(
                    f"  [yellow]→[/yellow] [bold cyan]{target_obj.name}[/bold cyan] ({conn.object})\n"
                    f"     via [dim]{conn.name}[/dim] ({conn.key}) [{relationship}]"
                )
    else:
        console.print("\n[bold cyan]Efferent Coupling (Ce):[/bold cyan] 0 objects")
        console.print("[dim]This object does not depend on other objects[/dim]")

    console.print()


@cli.command(name="find-orphans")
def find_orphans(
    file_path: Optional[Path] = typer.Argument(
        None, help="Path to Knack application metadata JSON file (optional if using --app-id)"
    ),
    app_id: Optional[str] = typer.Option(
        None, "--app-id", help="Knack application ID (can also use KNACK_APP_ID env var)"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force refresh cached API data (ignore cache)"
    ),
    include_system: bool = typer.Option(
        False, "--include-system", help="Include Knack system fields in the orphaned fields list"
    ),
    output_format: str = typer.Option(
        "rich", "--format", help="Output format: rich or json"
    ),
):
    """
    List orphaned fields and objects — defined but not used anywhere.

    An orphaned field has no usages in views, columns, sorts, formulas, or
    connections. An orphaned object has no connections and no views displaying
    it (user profile objects are excluded — they are referenced through Knack's
    auth system).


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
    _validate_output_format(output_format)

    # Load metadata
    app_export = load_app_metadata(file_path, app_id, refresh)

    sleuth = KnackSleuth(app_export)

    with console.status("[cyan]Analyzing field and object usages..."):
        orphaned_fields = sleuth.find_orphaned_fields()
        orphaned_objects = sleuth.find_orphaned_objects()

    # Optionally hide system fields (they are rarely actionable)
    hidden_system_count = 0
    if not include_system:
        visible_fields = [(o, f) for o, f in orphaned_fields if not f.isSystemField]
        hidden_system_count = len(orphaned_fields) - len(visible_fields)
    else:
        visible_fields = orphaned_fields

    if output_format == "json":
        def _field_notes(obj, field):
            notes = []
            if obj.identifier == field.key:
                notes.append("identifier")
            if field.isSystemField:
                notes.append("system")
            if field.required:
                notes.append("required")
            return notes

        fields_payload = [
            {
                "object_key": obj.key,
                "object_name": obj.name,
                "field_key": field.key,
                "field_name": field.name,
                "type": field.type,
                "notes": _field_notes(obj, field),
            }
            for obj, field in sorted(
                visible_fields, key=lambda pair: (pair[0].name.lower(), pair[1].name.lower())
            )
        ]
        objects_payload = [
            {
                "key": obj.key,
                "name": obj.name,
                "field_count": len(obj.fields),
                "rows": app_export.application.counts.get(obj.key, 0),
            }
            for obj in sorted(orphaned_objects, key=lambda o: o.name.lower())
        ]
        payload = {
            "orphaned_fields": fields_payload,
            "orphaned_objects": objects_payload,
            "totals": {
                "orphaned_fields": len(fields_payload),
                "orphaned_fields_including_hidden": len(orphaned_fields),
                "orphaned_objects": len(orphaned_objects),
                "hidden_system_fields": hidden_system_count,
            },
        }
        typer.echo(json.dumps(payload, indent=2))
        return

    # Orphaned fields table
    console.print()
    if visible_fields:
        table = Table(
            title=f"[bold cyan]{app_export.application.name}[/bold cyan] - Orphaned Fields"
        )
        table.add_column("Object", style="bold cyan")
        table.add_column("Field", style="yellow")
        table.add_column("Key", style="dim")
        table.add_column("Type", style="magenta")
        table.add_column("Notes", style="dim")

        for obj, field in sorted(
            visible_fields, key=lambda pair: (pair[0].name.lower(), pair[1].name.lower())
        ):
            notes = []
            if obj.identifier == field.key:
                notes.append("identifier")
            if field.isSystemField:
                notes.append("system")
            if field.required:
                notes.append("required")
            table.add_row(obj.name, field.name, field.key, field.type, ", ".join(notes))

        console.print(table)
    else:
        console.print("[green]✓[/green] No orphaned fields found")

    if hidden_system_count:
        console.print(
            f"[dim]({hidden_system_count} orphaned system fields hidden — "
            f"use --include-system to show them)[/dim]"
        )

    # Orphaned objects
    console.print()
    if orphaned_objects:
        console.print(f"[bold cyan]Orphaned Objects:[/bold cyan] {len(orphaned_objects)}")
        for obj in sorted(orphaned_objects, key=lambda o: o.name.lower()):
            row_count = app_export.application.counts.get(obj.key, 0)
            console.print(
                f"  [yellow]•[/yellow] [bold cyan]{obj.name}[/bold cyan] ({obj.key}) - "
                f"{len(obj.fields)} fields, {row_count:,} rows"
            )
    else:
        console.print("[green]✓[/green] No orphaned objects found")

    # Summary
    console.print()
    console.print(
        # Count what the table above actually showed; hidden system fields are
        # called out separately so the two numbers never silently disagree.
        f"[dim]Total: {len(visible_fields)} orphaned fields"
        + (
            f" (+{hidden_system_count} hidden system)" if hidden_system_count else ""
        )
        + f" | {len(orphaned_objects)} orphaned objects[/dim]"
    )
    console.print(
        "[dim]Review before deleting: identifier/system fields can be orphans by design[/dim]"
    )
    console.print()


@cli.command(name="download-metadata")
def download_metadata(
    output_file: Optional[Path] = typer.Argument(
        None, help="Output file path (default: {APP_ID}_metadata.json)"
    ),
    app_id: Optional[str] = typer.Option(
        None, "--app-id", help="Knack application ID (can also use KNACK_APP_ID env var)"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force refresh cached API data (ignore cache)"
    ),
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
    settings = Settings()
    
    # Get credentials
    final_app_id = app_id or settings.knack_app_id
    
    if not final_app_id:
        err_console.print(
            "[red]Error:[/red] App ID is required. Provide via --app-id or KNACK_APP_ID environment variable."
        )
        raise typer.Exit(1)
    
    # Determine output filename
    if not output_file:
        output_file = Path(f"{final_app_id}_metadata.json")
    
    # Reuse a fresh cache file when available, otherwise fetch from the API.
    data = None

    if not refresh:
        cached = find_valid_cache(final_app_id)
        if cached:
            cache_path, cache_age_hours = cached
            try:
                with cache_path.open() as f:
                    data = json.load(f)
                err_console.print(
                    f"[dim]Using cached data from {cache_path.name} "
                    f"(age: {cache_age_hours:.1f}h)[/dim]"
                )
            except Exception as e:
                err_console.print(
                    f"[yellow]Warning:[/yellow] Failed to load cache: {e}. Fetching from API..."
                )
                data = None  # Force API fetch

    if data is None:
        # Fetch from the public Knack metadata endpoint (no API key required).
        try:
            if refresh:
                err_console.print("[cyan]Forcing refresh from API...[/cyan]")

            with err_console.status("[cyan]Fetching metadata from Knack API..."):
                data = fetch_metadata_from_api(final_app_id)

        except httpx.HTTPStatusError as e:
            err_console.print(f"[red]Error:[/red] HTTP {e.response.status_code}: {e.response.text}")
            raise typer.Exit(1)
        except httpx.RequestError as e:
            err_console.print(f"[red]Error:[/red] Failed to connect to Knack API: {e}")
            raise typer.Exit(1)
        except Exception as e:
            err_console.print(f"[red]Error:[/red] Failed to fetch metadata: {e}")
            raise typer.Exit(1)
    
    # Save to output file
    try:
        with output_file.open('w') as f:
            json.dump(data, f, indent=2)
        
        file_size = output_file.stat().st_size
        file_size_kb = file_size / 1024
        
        console.print()
        console.print(f"[green]✓[/green] Metadata saved to [bold]{output_file}[/bold]")
        console.print(f"[dim]  File size: {file_size_kb:.1f} KB[/dim]")
        
        # Show app info
        app_name = data.get('application', {}).get('name', 'Unknown')
        object_count = len(data.get('application', {}).get('objects', []))
        scene_count = len(data.get('application', {}).get('scenes', []))
        
        console.print(f"[dim]  App: {app_name}[/dim]")
        console.print(f"[dim]  Objects: {object_count} | Scenes: {scene_count}[/dim]")
        console.print()
        
    except Exception as e:
        err_console.print(f"[red]Error:[/red] Failed to save file: {e}")
        raise typer.Exit(1)


@cli.command(name="diff")
def diff(
    old_file: Path = typer.Argument(
        ..., help="Older metadata snapshot (JSON file)"
    ),
    new_file: Optional[Path] = typer.Argument(
        None,
        help="Newer metadata snapshot (JSON file). Omit to compare against the live API "
        "(requires --app-id or KNACK_APP_ID)",
    ),
    app_id: Optional[str] = typer.Option(
        None, "--app-id", help="Knack application ID for live comparison (can also use KNACK_APP_ID env var)"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force refresh cached API data (only applies to live comparison)"
    ),
    output_format: str = typer.Option(
        "rich", "--format", help="Output format: rich, json, or markdown"
    ),
    output_file: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Save output to file (requires --format json or markdown)"
    ),
    exit_code: bool = typer.Option(
        False, "--exit-code", help="Exit with code 1 if differences were found (like git diff)"
    ),
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
    from knack_sleuth.diff import diff_applications, diff_to_markdown

    valid_formats = ["rich", "json", "markdown"]
    if output_format not in valid_formats:
        err_console.print(
            f"[red]Error:[/red] Invalid format '{output_format}'. "
            f"Use one of: {', '.join(valid_formats)}"
        )
        raise typer.Exit(1)

    if output_file and output_format == "rich":
        err_console.print(
            "[red]Error:[/red] --output requires --format json or markdown"
        )
        raise typer.Exit(1)

    # Load both sides (file vs file, or file vs API when new_file is omitted)
    old_export = load_app_metadata(old_file, None, False)
    if new_file:
        new_export = load_app_metadata(new_file, None, False)
    else:
        new_export = load_app_metadata(None, app_id, refresh)

    diff_result = diff_applications(old_export.application, new_export.application)

    if output_format == "json":
        content = json.dumps(diff_result, indent=2)
    elif output_format == "markdown":
        content = diff_to_markdown(diff_result)
    else:
        _print_diff_rich(diff_result, old_file, new_file)
        content = None

    if content is not None:
        if output_file:
            try:
                with output_file.open('w') as f:
                    f.write(content)
                console.print(f"[green]✓[/green] Diff saved to [bold]{output_file}[/bold]")
            except Exception as e:
                err_console.print(f"[red]Error:[/red] Failed to save file: {e}")
                raise typer.Exit(1)
        else:
            typer.echo(content)

    if exit_code and diff_result["has_changes"]:
        raise typer.Exit(1)


def _print_diff_rich(
    diff_result: dict, old_file: Path, new_file: Optional[Path]
) -> None:
    """Render a diff result to the console with Rich formatting."""
    summary = diff_result["summary"]
    old_label = old_file.name
    new_label = new_file.name if new_file else "live API"

    console.print()
    console.print(
        Panel(
            f"[bold cyan]{old_label}[/bold cyan] → [bold cyan]{new_label}[/bold cyan]",
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

    def print_section(title: str, entries: list, render, marker: str, color: str) -> None:
        if not entries:
            return
        console.print(f"\n[bold cyan]{title}:[/bold cyan] {len(entries)}")
        for entry in entries:
            console.print(f"  [{color}]{marker}[/{color}] {render(entry)}")

    def render_changes(entry: dict) -> str:
        changes = "; ".join(
            f"{attr}: {c['old']!r} → {c['new']!r}" for attr, c in entry["changes"].items()
        )
        return f"{entry['name']} ({entry['key']}) — {changes}"

    print_section(
        "Objects Added", diff_result["objects"]["added"],
        lambda e: f"[bold cyan]{e['name']}[/bold cyan] ({e['key']}) — {e['field_count']} fields",
        "+", "green",
    )
    print_section(
        "Objects Removed", diff_result["objects"]["removed"],
        lambda e: f"[bold cyan]{e['name']}[/bold cyan] ({e['key']}) — {e['field_count']} fields",
        "-", "red",
    )
    print_section(
        "Objects Renamed", diff_result["objects"]["renamed"],
        lambda e: f"{e['key']}: {e['old_name']} → {e['new_name']}",
        "~", "yellow",
    )
    print_section(
        "Fields Added", diff_result["fields"]["added"],
        lambda e: f"{e['object_name']} → [bold cyan]{e['name']}[/bold cyan] ({e['key']}, {e['type']})",
        "+", "green",
    )
    print_section(
        "Fields Removed", diff_result["fields"]["removed"],
        lambda e: f"{e['object_name']} → [bold cyan]{e['name']}[/bold cyan] ({e['key']}, {e['type']})",
        "-", "red",
    )
    print_section(
        "Fields Changed", diff_result["fields"]["changed"],
        lambda e: f"{e['object_name']} → {render_changes(e)}",
        "~", "yellow",
    )
    print_section(
        "Scenes Added", diff_result["scenes"]["added"],
        lambda e: f"[bold cyan]{e['name']}[/bold cyan] ({e['key']}, /{e['slug']}) — {e['view_count']} views",
        "+", "green",
    )
    print_section(
        "Scenes Removed", diff_result["scenes"]["removed"],
        lambda e: f"[bold cyan]{e['name']}[/bold cyan] ({e['key']}, /{e['slug']}) — {e['view_count']} views",
        "-", "red",
    )
    print_section(
        "Scenes Renamed", diff_result["scenes"]["renamed"],
        lambda e: f"{e['key']}: {e['old_name']} → {e['new_name']}",
        "~", "yellow",
    )
    print_section(
        "Views Added", diff_result["views"]["added"],
        lambda e: f"{e['scene_name']} → [bold cyan]{e['name']}[/bold cyan] ({e['key']}, {e['type']})",
        "+", "green",
    )
    print_section(
        "Views Removed", diff_result["views"]["removed"],
        lambda e: f"{e['scene_name']} → [bold cyan]{e['name']}[/bold cyan] ({e['key']}, {e['type']})",
        "-", "red",
    )
    print_section(
        "Views Changed", diff_result["views"]["changed"],
        lambda e: f"{e['scene_name']} → {render_changes(e)}",
        "~", "yellow",
    )

    console.print()


@cli.command(name="export-schema")
def export_schema(
    output_file: Optional[Path] = typer.Argument(
        None, help="Output file path (default: knack_metadata_schema.json)"
    ),
    mode: str = typer.Option(
        "validation", "--mode", help="Schema generation mode: validation or serialization"
    ),
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
    # Set default output path
    if not output_file:
        output_file = Path("knack_metadata_schema.json")
    
    # Generate schema based on mode
    try:
        if mode == "validation":
            schema = KnackAppMetadata.model_json_schema(mode="validation")
        elif mode == "serialization":
            schema = KnackAppMetadata.model_json_schema(mode="serialization")
        else:
            err_console.print(f"[red]Error:[/red] Unknown mode '{mode}'. Use 'validation' or 'serialization'.")
            raise typer.Exit(1)
        
        # Save schema to file
        with output_file.open('w') as f:
            json.dump(schema, f, indent=2)
        
        file_size = output_file.stat().st_size
        file_size_kb = file_size / 1024
        
        console.print()
        console.print(f"[green]✓[/green] JSON schema exported to [bold]{output_file}[/bold]")
        console.print(f"[dim]  Mode: {mode}[/dim]")
        console.print(f"[dim]  File size: {file_size_kb:.1f} KB[/dim]")
        console.print()
        console.print("[dim]Use this schema for API documentation, validation, or IDE integration[/dim]")
        console.print()
        
    except Exception as e:
        err_console.print(f"[red]Error:[/red] Failed to generate or save schema: {e}")
        raise typer.Exit(1)


@cli.command(name="export-db-schema")
def export_db_schema(
    file_path: Optional[Path] = typer.Argument(
        None, help="Path to Knack app export JSON file"
    ),
    output_file: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output file path"
    ),
    format: str = typer.Option(
        "json", "--format", "-f", help="Output format: json, dbml, yaml, or mermaid"
    ),
    detail: str = typer.Option(
        "standard", "--detail", "-d", help="Detail level: structural, minimal, compact, or standard"
    ),
    app_id: Optional[str] = typer.Option(
        None, "--app-id", help="Knack app ID (alternative to file)"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force refresh cached API data (ignore cache)"
    ),
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
    from knack_sleuth.db_schema import export_database_schema

    # Validate format
    valid_formats = ["json", "dbml", "yaml", "mermaid"]
    if format not in valid_formats:
        err_console.print(
            f"[red]Error:[/red] Invalid format '{format}'. "
            f"Use one of: {', '.join(valid_formats)}"
        )
        raise typer.Exit(1)

    # Validate detail level
    valid_details = ["structural", "minimal", "compact", "standard"]
    if detail not in valid_details:
        err_console.print(
            f"[red]Error:[/red] Invalid detail level '{detail}'. "
            f"Use one of: {', '.join(valid_details)}"
        )
        raise typer.Exit(1)

    # Set default output file based on format
    if not output_file:
        extension_map = {"json": "json", "dbml": "dbml", "yaml": "yaml", "mermaid": "mmd"}
        output_file = Path(f"knack_db_schema.{extension_map[format]}")

    # Load app metadata (the CLI wrapper handles cache messaging + error reporting)
    console.print("[dim]Loading application metadata...[/dim]")
    app_metadata = load_app_metadata(file_path, app_id, refresh)
    app = app_metadata.application

    console.print(
        f"[green]✓[/green] Loaded: [bold]{app.name}[/bold] "
        f"({len(app.objects)} objects)"
    )
    console.print()

    try:
        # Generate schema
        console.print(f"[dim]Generating {format.upper()} schema ({detail} detail)...[/dim]")
        schema = export_database_schema(app, format=format, detail=detail)

        # Save to file
        with output_file.open("w") as f:
            if format == "json":
                json.dump(schema, f, indent=2)
            else:
                f.write(schema)

        file_size = output_file.stat().st_size
        file_size_kb = file_size / 1024

        console.print(
            f"[green]✓[/green] Database schema exported to [bold]{output_file}[/bold]"
        )
        console.print(f"[dim]  Format: {format.upper()}[/dim]")
        console.print(f"[dim]  Detail: {detail}[/dim]")
        console.print(f"[dim]  Objects: {len(app.objects)}[/dim]")
        console.print(f"[dim]  File size: {file_size_kb:.1f} KB[/dim]")
        console.print()

        # Format-specific tips
        if format == "dbml":
            console.print(
                "[dim]Tip: Upload this DBML file to https://dbdiagram.io to "
                "visualize the database ER diagram[/dim]"
            )
        elif format == "json":
            console.print(
                "[dim]Tip: This JSON Schema describes the actual database structure "
                "with all relationships[/dim]"
            )
        elif format == "mermaid":
            console.print(
                "[dim]Tip: This Mermaid diagram can be rendered in GitHub/GitLab markdown, "
                "VS Code, or at https://mermaid.live[/dim]"
            )
        elif format == "yaml":
            console.print(
                "[dim]Tip: This YAML file provides a human-readable database structure "
                "overview[/dim]"
            )
        console.print()

    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@cli.command(name="export-schema-subgraph")
def export_schema_subgraph(
    file_path: Optional[Path] = typer.Argument(
        None, help="Path to Knack app export JSON file"
    ),
    object: str = typer.Option(
        ..., "--object", help="Starting object (key or name, e.g., 'Events' or 'object_12')"
    ),
    depth: int = typer.Option(
        1, "--depth", help="Traversal depth (0=object only, 1=direct connections, 2=one level deeper)"
    ),
    output_file: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output file path"
    ),
    format: str = typer.Option(
        "json", "--format", "-f", help="Output format: json, dbml, yaml, or mermaid"
    ),
    detail: str = typer.Option(
        "standard", "--detail", "-d", help="Detail level: structural, minimal, compact, or standard"
    ),
    app_id: Optional[str] = typer.Option(
        None, "--app-id", help="Knack app ID (alternative to file)"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force refresh cached API data (ignore cache)"
    ),
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
    from knack_sleuth.db_schema import (
        export_database_schema,
        find_object_by_identifier,
        build_subgraph,
        filter_app_to_subgraph,
    )

    # Validate depth
    if depth > 2:
        err_console.print(
            f"[yellow]Warning:[/yellow] Depth {depth} is not recommended. "
            "For depth > 2, consider using [cyan]export-db-schema[/cyan] to export the full schema instead."
        )
        console.print()
        console.print("Proceeding with depth=2 (maximum recommended)...")
        depth = 2

    if depth < 0:
        err_console.print("[red]Error:[/red] Depth must be >= 0")
        raise typer.Exit(1)

    # Validate format
    valid_formats = ["json", "dbml", "yaml", "mermaid"]
    if format not in valid_formats:
        err_console.print(
            f"[red]Error:[/red] Invalid format '{format}'. "
            f"Use one of: {', '.join(valid_formats)}"
        )
        raise typer.Exit(1)

    # Validate detail level
    valid_details = ["structural", "minimal", "compact", "standard"]
    if detail not in valid_details:
        err_console.print(
            f"[red]Error:[/red] Invalid detail level '{detail}'. "
            f"Use one of: {', '.join(valid_details)}"
        )
        raise typer.Exit(1)

    # Set default output file based on format
    if not output_file:
        extension_map = {"json": "json", "dbml": "dbml", "yaml": "yaml", "mermaid": "mmd"}
        # Sanitize object name for filename: replace spaces and special chars with dashes
        sanitized_name = object.lower().replace(" ", "-").replace("_", "-")
        # Remove any other problematic characters
        import re
        sanitized_name = re.sub(r'[^\w\-]', '', sanitized_name)
        # Remove consecutive dashes
        sanitized_name = re.sub(r'-+', '-', sanitized_name).strip('-')
        output_file = Path(f"knack_subgraph_{sanitized_name}.{extension_map[format]}")

    # Load app metadata (the CLI wrapper handles cache messaging + error reporting)
    console.print("[dim]Loading application metadata...[/dim]")
    app_metadata = load_app_metadata(file_path, app_id, refresh)
    app = app_metadata.application

    console.print(
        f"[green]✓[/green] Loaded: [bold]{app.name}[/bold] "
        f"({len(app.objects)} objects)"
    )

    try:
        # Find the starting object
        start_object = find_object_by_identifier(app, object)
        if not start_object:
            err_console.print(
                f"[red]Error:[/red] Object '{object}' not found. "
                "Please specify a valid object key or name."
            )
            raise typer.Exit(1)

        console.print(
            f"[green]✓[/green] Starting object: [bold]{start_object.name}[/bold] ({start_object.key})"
        )

        # Build subgraph
        console.print(f"[dim]Building subgraph with depth {depth}...[/dim]")
        subgraph_keys = build_subgraph(app, start_object.key, depth)

        console.print(
            f"[green]✓[/green] Subgraph contains [bold]{len(subgraph_keys)}[/bold] objects"
        )

        # List the objects in the subgraph
        objects_by_key = {obj.key: obj for obj in app.objects}
        console.print("\n[cyan]Objects in subgraph:[/cyan]")
        for key in sorted(subgraph_keys):
            obj = objects_by_key.get(key)
            if obj:
                console.print(f"  • {obj.name} ({key})")
        console.print()

        # Filter application to subgraph
        filtered_app = filter_app_to_subgraph(app, subgraph_keys)

        # Generate schema
        console.print(f"[dim]Generating {format.upper()} schema ({detail} detail)...[/dim]")
        schema = export_database_schema(filtered_app, format=format, detail=detail)

        # Save to file
        with output_file.open("w") as f:
            if format == "json":
                json.dump(schema, f, indent=2)
            else:
                f.write(schema)

        file_size = output_file.stat().st_size
        file_size_kb = file_size / 1024

        console.print(
            f"[green]✓[/green] Schema subgraph exported to [bold]{output_file}[/bold]"
        )
        console.print(f"[dim]  Format: {format.upper()}[/dim]")
        console.print(f"[dim]  Detail: {detail}[/dim]")
        console.print(f"[dim]  Starting object: {start_object.name} ({start_object.key})[/dim]")
        console.print(f"[dim]  Depth: {depth}[/dim]")
        console.print(f"[dim]  Objects: {len(subgraph_keys)}[/dim]")
        console.print(f"[dim]  File size: {file_size_kb:.1f} KB[/dim]")
        console.print()

        # Format-specific tips
        if format == "dbml":
            console.print(
                "[dim]Tip: Upload this DBML file to https://dbdiagram.io to "
                "visualize the subgraph ER diagram[/dim]"
            )
        elif format == "json":
            console.print(
                "[dim]Tip: This JSON Schema describes the subgraph database structure "
                "with all relationships[/dim]"
            )
        elif format == "mermaid":
            console.print(
                "[dim]Tip: This Mermaid diagram can be rendered in GitHub/GitLab markdown, "
                "VS Code, or at https://mermaid.live[/dim]"
            )
        elif format == "yaml":
            console.print(
                "[dim]Tip: This YAML file provides a human-readable subgraph structure "
                "overview[/dim]"
            )
        console.print()

    except typer.Exit:
        # Let intentional exits (e.g. object not found) propagate unchanged.
        raise
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@cli.command(name="impact-analysis")
def impact_analysis(
    target_identifier: str = typer.Argument(
        ..., help="Object or field key/name to analyze (e.g., 'object_12' or 'field_116')"
    ),
    file_path: Optional[Path] = typer.Argument(
        None, help="Path to Knack application metadata JSON file (optional if using --app-id)"
    ),
    app_id: Optional[str] = typer.Option(
        None, "--app-id", help="Knack application ID (can also use KNACK_APP_ID env var)"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force refresh cached API data (ignore cache)"
    ),
    output_format: str = typer.Option(
        "json", "--format", help="Output format: json, yaml, or markdown"
    ),
    output_file: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Save output to file instead of stdout"
    ),
):
    """
    [EXPERIMENTAL] Generate a comprehensive impact analysis for human and AI/agent consumption.

    This command analyzes how changing a specific object or field would impact
    your Knack application, providing structured output suitable for:


    Use cases:

    - AI agents planning database changes

    - Human-readable markdown reports (--format markdown)

    - Impact assessment documentation

    - Change risk analysis

    - Migration planning


    The output includes:

    - Direct impacts (connections, views, forms, formulas)

    - Cascade impacts (affected fields, scenes)

    - Risk assessment (likelihood, impact score)

    - Affected user workflows


    Output formats:

    - JSON: Structured for AI/agent processing

    - Markdown: Human-friendly documentation (--format markdown)

    - YAML: Alternative structured format


    Examples:

        knack-sleuth impact-analysis object_12 --format json

        knack-sleuth impact-analysis field_116 --app-id YOUR_APP_ID --output impact.json

        knack-sleuth impact-analysis "Organization" my_app.json --format markdown
    """
    # Load metadata
    app_export = load_app_metadata(file_path, app_id, refresh)

    # Create search engine
    sleuth = KnackSleuth(app_export)

    # Find the target (supports both key and name lookup)
    target_key = None
    target_type = "auto"

    if target_identifier.lower().startswith("object_"):
        # Direct object key
        target_key = target_identifier
        target_type = "object"
    elif target_identifier.lower().startswith("field_"):
        # Direct field key
        target_key = target_identifier
        target_type = "field"
    else:
        # Search by name - try object first, then field
        matched_object = resolve_object(app_export.application, target_identifier)
        if matched_object:
            target_key = matched_object.key
            target_type = "object"
        else:
            field_matches = resolve_fields(app_export.application, target_identifier)
            if len(field_matches) > 1:
                console.print(
                    f"[yellow]Ambiguous:[/yellow] field name '{target_identifier}' "
                    f"matches {len(field_matches)} fields:"
                )
                for match_obj, match_field in field_matches:
                    console.print(
                        f"  {match_field.key} — {match_obj.name} → {match_field.name} ({match_field.type})"
                    )
                console.print("\nRe-run with the field key to disambiguate.")
                raise typer.Exit(1)
            if field_matches:
                target_key = field_matches[0][1].key
                target_type = "field"

    if not target_key:
        err_console.print(
            f"[red]Error:[/red] Could not find object or field '{target_identifier}'"
        )
        suggestions = suggest_object_names(
            app_export.application, target_identifier
        ) or suggest_field_names(app_export.application, target_identifier)
        if suggestions:
            console.print(f"Did you mean: [cyan]{'[/cyan], [cyan]'.join(suggestions)}[/cyan]?")
        raise typer.Exit(1)

    # Generate analysis
    analysis = sleuth.generate_impact_analysis(target_key, target_type)

    if "error" in analysis:
        err_console.print(f"[red]Error:[/red] {analysis['error']}")
        raise typer.Exit(1)

    # Format output
    if output_format == "json":
        output_content = json.dumps(analysis, indent=2)
    elif output_format == "yaml":
        import yaml

        output_content = yaml.dump(analysis, default_flow_style=False, sort_keys=False)
    elif output_format == "markdown":
        # Collect unique scenes for builder URLs
        settings = Settings()
        account_slug = app_export.application.account.get('slug', app_export.application.slug)
        scenes_to_review = set(analysis['cascade_impacts']['affected_scenes'])
        
        # Generate markdown summary
        md_lines = [
            f"# Impact Analysis: {analysis['target']['name']}",
            "",
            f"**Type:** {analysis['target']['type']}  ",
            f"**Key:** `{analysis['target']['key']}`  ",
            f"**Description:** {analysis['target']['description']}  ",
            "",
            "## Risk Assessment",
            "",
            f"- **Breaking Change Likelihood:** {analysis['risk_assessment']['breaking_change_likelihood']}",
            f"- **Impact Score:** {analysis['risk_assessment']['impact_score']}",
            f"- **Affected Workflows:** {', '.join(analysis['risk_assessment']['affected_user_workflows']) or 'None'}",
            "",
            "## Direct Impacts",
            "",
            f"### Connections ({len(analysis['direct_impacts']['connections'])})",
        ]

        for conn in analysis['direct_impacts']['connections']:
            md_lines.append(f"- {conn['description']}")
        if not analysis['direct_impacts']['connections']:
            md_lines.append("*No connection impacts*")

        md_lines.append("")
        md_lines.append(f"### Views ({len(analysis['direct_impacts']['views'])})")
        for view in analysis['direct_impacts']['views']:
            md_lines.append(
                f"- **{view['view_name']}** (`{view['view_key']}`) - {view['view_type']} in scene {view['scene_name']}"
            )
        if not analysis['direct_impacts']['views']:
            md_lines.append("*No view impacts*")

        md_lines.append("")
        md_lines.append(f"### Forms ({len(analysis['direct_impacts']['forms'])})")
        for form in analysis['direct_impacts']['forms']:
            md_lines.append(f"- **{form['view_name']}** (`{form['view_key']}`)")
        if not analysis['direct_impacts']['forms']:
            md_lines.append("*No form impacts*")

        md_lines.append("")
        md_lines.append(f"### Formulas ({len(analysis['direct_impacts']['formulas'])})")
        for formula in analysis['direct_impacts']['formulas']:
            md_lines.append(f"- **{formula['field_name']}** (`{formula['field_key']}`): `{formula.get('equation', 'N/A')}`")
        if not analysis['direct_impacts']['formulas']:
            md_lines.append("*No formula impacts*")

        md_lines.extend([
            "",
            "## Cascade Impacts",
            "",
            f"### Affected Fields ({len(analysis['cascade_impacts']['affected_fields'])})",
        ])

        for field in analysis['cascade_impacts']['affected_fields']:
            md_lines.append(
                f"- **{field['field_name']}** (`{field['field_key']}`) - {field['field_type']} - {field['usage_count']} usages"
            )
        if not analysis['cascade_impacts']['affected_fields']:
            md_lines.append("*No field cascade impacts*")

        md_lines.extend([
            "",
            f"### Affected Scenes ({len(analysis['cascade_impacts']['affected_scenes'])})",
        ])
        for scene_key in analysis['cascade_impacts']['affected_scenes']:
            scene_info = next(
                (s for s in analysis['direct_impacts']['scenes'] if s['scene_key'] == scene_key),
                None
            )
            if scene_info:
                md_lines.append(f"- **{scene_info['scene_name']}** (`{scene_key}`) - /{scene_info['scene_slug']}")
        if not analysis['cascade_impacts']['affected_scenes']:
            md_lines.append("*No scene cascade impacts*")

        md_lines.extend([
            "",
            "## Summary",
            "",
            f"- **Total Direct Impacts:** {analysis['metadata']['total_direct_impacts']}",
            f"- **Total Cascade Impacts:** {analysis['metadata']['total_cascade_impacts']}",
        ])
        
        # Add Builder Pages to Review section
        if scenes_to_review:
            md_lines.extend([
                "",
                "## Builder Pages to Review",
                "",
                f"**{len(scenes_to_review)} scenes affected**",
                "",
            ])
            
            # Build URLs based on builder version
            if settings.knack_next_gen_builder:
                # Next-Gen builder
                for scene_key in sorted(scenes_to_review):
                    url = f"{KNACK_NG_BUILDER_BASE_URL}/{account_slug}/portal/pages/{scene_key}"
                    scene_name = next(
                        (s['scene_name'] for s in analysis['direct_impacts']['scenes'] if s['scene_key'] == scene_key),
                        scene_key
                    )
                    md_lines.append(f"- [{scene_name}]({url})")
            else:
                # Classic builder
                for scene_key in sorted(scenes_to_review):
                    url = f"{KNACK_BUILDER_BASE_URL}/{account_slug}/portal/pages/{scene_key}"
                    scene_name = next(
                        (s['scene_name'] for s in analysis['direct_impacts']['scenes'] if s['scene_key'] == scene_key),
                        scene_key
                    )
                    md_lines.append(f"- [{scene_name}]({url})")

        output_content = "\n".join(md_lines)
    else:
        err_console.print(f"[red]Error:[/red] Unknown format '{output_format}'")
        raise typer.Exit(1)

    # Output to file or stdout
    if output_file:
        try:
            with output_file.open('w') as f:
                f.write(output_content)
            console.print(f"[green]✓[/green] Analysis saved to [bold]{output_file}[/bold]")
        except Exception as e:
            err_console.print(f"[red]Error:[/red] Failed to save file: {e}")
            raise typer.Exit(1)
    else:
        typer.echo(output_content)


@cli.command(name="app-summary")
def app_summary(
    file_path: Optional[Path] = typer.Argument(
        None, help="Path to Knack application metadata JSON file (optional if using --app-id)"
    ),
    app_id: Optional[str] = typer.Option(
        None, "--app-id", help="Knack application ID (can also use KNACK_APP_ID env var)"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force refresh cached API data (ignore cache)"
    ),
    output_format: str = typer.Option(
        "json", "--format", help="Output format: json, yaml, or markdown"
    ),
    output_file: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Save output to file instead of stdout"
    ),
):
    """
    [EXPERIMENTAL] Generate a comprehensive architectural summary for human and AI/agent consumption.

    This command provides universal context for ANY architectural discussion,
    including domain model, relationships, patterns, and extensibility.


    Perfect for:

    - Understanding overall app architecture

    - Planning major refactorings

    - AI-assisted architecture discussions

    - Human-readable documentation (--format markdown)

    - Complexity assessment


    The output includes:

    - Domain model classification (user profiles, core, transactional, reference objects)

    - Relationship topology (connections, clusters, hubs)

    - Data patterns (temporal, calculations)

    - UI architecture (scenes, views, navigation)

    - Access patterns (authentication, roles)

    - Technical debt indicators (orphaned resources, bottlenecks)

    - Extensibility assessment (modularity, coupling)


    Output formats:

    - JSON: Structured for AI/agent processing (default)

    - Markdown: Human-friendly documentation (--format markdown)

    - YAML: Alternative structured format


    Examples:

        knack-sleuth app-summary my_app.json

        knack-sleuth app-summary --app-id YOUR_APP_ID --format markdown

        knack-sleuth app-summary --app-id YOUR_APP_ID --output summary.json
    """
    # Load metadata
    app_export = load_app_metadata(file_path, app_id, refresh)

    # Create search engine and generate summary
    sleuth = KnackSleuth(app_export)
    
    with console.status("[cyan]Analyzing application architecture..."):
        summary = sleuth.generate_app_summary()

    # Format output
    if output_format == "json":
        output_content = json.dumps(summary, indent=2)
    elif output_format == "yaml":
        import yaml

        output_content = yaml.dump(summary, default_flow_style=False, sort_keys=False)
    elif output_format == "markdown":
        # Generate markdown summary
        app_info = summary["application"]
        metrics = app_info["complexity_metrics"]
        domain = summary["domain_model"]
        relationships = summary["relationship_map"]
        patterns = summary["data_patterns"]
        ui = summary["ui_architecture"]
        access = summary["access_patterns"]
        debt = summary["technical_debt_indicators"]
        extensibility = summary["extensibility_assessment"]

        md_lines = [
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
            "## Domain Model",
            "",
            f"### Core Entities ({len(domain['core_entities'])})",
        ]

        for entity in domain["core_entities"]:
            md_lines.append(
                f"- **{entity['name']}** (`{entity['object_key']}`) - "
                f"Importance: {entity.get('importance_score', 0):.2f}, Centrality: {entity['centrality_score']}, Records: {entity['record_count']:,}"
            )

        md_lines.extend([
            "",
            f"### Transactional Entities ({len(domain['transactional_entities'])}) - top 5 shown",
        ])
        for entity in domain["transactional_entities"][:5]:
            md_lines.append(f"- **{entity['name']}** - {entity['record_count']:,} records")

        md_lines.extend([
            "",
            f"### Reference Data ({len(domain['reference_data'])}) - top 5 shown",
        ])
        for entity in domain["reference_data"][:5]:
            md_lines.append(
                f"- **{entity['name']}** - Used by {len(entity.get('used_by', []))} objects"
            )

        md_lines.extend([
            "",
            "## Relationship Topology",
            "",
            f"**Total Connections:** {relationships['connection_graph']['total_connections']}",
            "",
            f"### Hub Objects ({len(relationships['hub_objects'])}) - top 5 shown",
        ])

        for hub in relationships["hub_objects"][:5]:
            md_lines.append(
                f"- **{hub['object']}** - {hub['total_connections']} connections "
                f"({hub['inbound_connections']} in, {hub['outbound_connections']} out)"
            )
            md_lines.append(f"  - _{hub['interpretation']}_")

        md_lines.extend([
            "",
            f"### Dependency Clusters ({len(relationships['dependency_clusters'])})",
        ])
        for cluster in relationships["dependency_clusters"][:3]:
            md_lines.append(
                f"- {', '.join(cluster['objects'])} ({cluster['cohesion']} cohesion)"
            )

        md_lines.extend([
            "",
            "## Data Patterns",
            "",
            "### Calculation Complexity",
            f"- Formula fields: {patterns['calculation_complexity']['total_formula_fields']}",
            f"- Objects with formulas: {patterns['calculation_complexity']['objects_with_formulas']}",
            f"- Max chain depth: {patterns['calculation_complexity']['max_formula_chain_depth']}",
            f"- Assessment: {patterns['calculation_complexity']['interpretation']}",
            "",
            "## UI Architecture",
            "",
            f"- Authenticated scenes: {ui['scene_patterns']['authenticated_scenes']}",
            f"- Public scenes: {ui['scene_patterns']['public_scenes']}",
            f"- Navigation depth: {ui['navigation_depth']['max_depth']} (max), {ui['navigation_depth']['avg_depth']} (avg)",
            f"- Complexity: {ui['navigation_depth']['interpretation']}",
            "",
            "### View Types",
        ])

        for view_type, count in sorted(
            ui["view_patterns"].items(), key=lambda x: x[1], reverse=True
        ):
            md_lines.append(f"- {view_type}: {count}")

        md_lines.extend([
            "",
            "## Access Patterns",
            "",
            f"- Authentication model: {access['authentication_model']}",
            f"- User objects: {', '.join(access['user_objects']) if access['user_objects'] else 'None'}",
            f"- Role-restricted scenes: {access['role_usage']['scenes_with_role_restrictions']}",
            "",
            "## Technical Debt",
            "",
            f"- Orphaned fields: {debt['orphaned_fields']}",
            f"- Orphaned objects: {debt['orphaned_objects']}",
            f"- Bottleneck objects: {len(debt['bottleneck_objects'])}",
            f"- High fan-out objects: {len(debt['high_fan_out_objects'])}",
            f"- Assessment: {debt['interpretation']}",
            "",
            "## Extensibility",
            "",
            f"- Modularity score: {extensibility['modularity_score']}",
            f"- Architectural style: {extensibility['architectural_style']}",
            f"- Assessment: {extensibility['interpretation']}",
            f"- Tight coupling pairs: {len(extensibility['tight_coupling_pairs'])}",
        ])

        output_content = "\n".join(md_lines)
    else:
        err_console.print(f"[red]Error:[/red] Unknown format '{output_format}'")
        raise typer.Exit(1)

    # Output to file or stdout
    if output_file:
        try:
            with output_file.open('w') as f:
                f.write(output_content)
            console.print(f"[green]✓[/green] Summary saved to [bold]{output_file}[/bold]")
        except Exception as e:
            err_console.print(f"[red]Error:[/red] Failed to save file: {e}")
            raise typer.Exit(1)
    else:
        typer.echo(output_content)


@cli.command(name="role-access-review")
def role_access_review(
    file_path: Optional[Path] = typer.Argument(
        None, help="Path to Knack application metadata JSON file (optional if using --app-id)"
    ),
    app_id: Optional[str] = typer.Option(
        None, "--app-id", help="Knack application ID (can also use KNACK_APP_ID env var)"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force refresh cached API data (ignore cache)"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output CSV file path (default: role_access_review.csv in current directory)"
    ),
    summary_only: bool = typer.Option(
        False, "--summary-only", help="Show only top-level and login pages with child counts (exclude individual child pages)"
    ),
):
    """
    Generate a role access review showing which user profiles can access which scenes.
    
    This command analyzes:

    - Scene navigation hierarchy (menus, login pages, utility pages)

    - Parent-child security inheritance

    - Profile (role) restrictions on each scene

    - Public vs authenticated access
    
    The output CSV shows:

    - Navigation structure (menu > parent > child)

    - Which roles have access to each scene

    - Security inheritance relationships

    - Public scenes and potential concerns
    
    Examples:

        knack-sleuth role-access-review app.json

        knack-sleuth role-access-review --app-id YOUR_APP_ID

        knack-sleuth role-access-review app.json -o my_review.csv

        knack-sleuth role-access-review app.json --summary-only  # Show only top-level pages
    """
    from pathlib import Path
    import csv
    from knack_sleuth.security import generate_security_report, count_children
    
    # Load metadata
    app_export = load_app_metadata(file_path, app_id, refresh)
    
    # Generate security report
    console.print("[dim]Analyzing scene security with navigation hierarchy...[/dim]")
    report = generate_security_report(app_export.application)
    
    # Filter for summary mode if requested
    scenes_to_export = report.scene_analyses
    if summary_only:
        # Only include Menu and Top-Level scenes
        scenes_to_export = [
            s for s in report.scene_analyses
            if s.nav_level in ["Menu", "Top-Level"]
        ]
        # Calculate child counts for each top-level scene
        for scene in scenes_to_export:
            scene.child_count = count_children(scene.scene_key, report.scene_analyses)
    
    # Print summary to console
    console.print()
    console.print("=" * 80)
    console.print(f"[bold cyan]ROLE ACCESS REVIEW: {report.app_name}[/bold cyan]")
    console.print("=" * 80)
    console.print(f"\nTotal Scenes: {report.total_scenes}")
    console.print(f"  Menu Scenes: {report.menu_scenes}")
    console.print(f"  Utility Pages (Require Knack Account): {report.utility_pages}")
    console.print(f"  Scenes with Parent (Inherit Security): {report.scenes_with_parents}")
    console.print(f"  Scenes Inheriting Security from Parent: {report.scenes_inheriting_security}")
    console.print(f"  Top-Level Scenes (No Parent): {report.total_scenes - report.scenes_with_parents}")
    console.print(f"\nPublic Scenes (No Login Required): {report.public_scenes}")
    console.print(f"Login Required Scenes: {report.login_required_scenes}")
    console.print(f"Unrestricted Authenticated Scenes: {report.unrestricted_authenticated_scenes}")
    console.print(f"\nTotal User Profiles (Roles): {report.total_profiles}")
    
    console.print("\n" + "=" * 80)
    console.print("[bold cyan]USER PROFILES (ROLES)[/bold cyan]")
    console.print("=" * 80)
    for profile_key, profile_name in report.profiles.items():
        access_count = report.profile_access_counts.get(profile_name, 0)
        console.print(f"  {profile_name:30} ({profile_key:20}) - Access to {access_count} scenes")
    
    console.print("\n" + "=" * 80)
    console.print("[bold cyan]SECURITY CONCERNS[/bold cyan]")
    console.print("=" * 80)
    if report.public_scenes > 0:
        console.print(f"⚠️  {report.public_scenes} scenes are publicly accessible without login")
    if report.unrestricted_authenticated_scenes > 0:
        console.print(f"⚠️  {report.unrestricted_authenticated_scenes} scenes require login but have no profile restrictions")
    if report.public_scenes == 0 and report.unrestricted_authenticated_scenes == 0:
        console.print("✓ No obvious security concerns in scene access controls")
    
    # Determine output path with timestamp
    if not output:
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output = Path(f"role_access_review_{timestamp}.csv")

    # Export to CSV
    fieldnames = [
        'root_nav',
        'scene_name',
        'nav_level',
        'allowed_profile_count',
        'allowed_profiles',
        'page_nav',
        'scene_key',
        'scene_slug',
        'scene_type',
        'view_names',
        'view_keys',
        'security_concern',
        'requires_login',
        'inherits_security',
    ]

    # Add child_count column if in summary mode
    if summary_only:
        fieldnames.insert(fieldnames.index('page_nav') + 1, 'child_count')

    with output.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for scene in scenes_to_export:
            row = scene.model_dump()
            # Convert lists to comma-separated strings
            row['allowed_profiles'] = ', '.join(scene.allowed_profiles)
            row['view_names'] = ', '.join(scene.view_names)
            row['view_keys'] = ', '.join(scene.view_keys)
            # Remove fields not in fieldnames
            if not summary_only:
                row.pop('child_count', None)
            writer.writerow({k: v for k, v in row.items() if k in fieldnames})
    
    console.print()
    if summary_only:
        children_omitted = report.total_scenes - len(scenes_to_export)
        console.print(f"[green]✓[/green] Summary report exported to [bold]{output}[/bold]")
        console.print(f"[dim]  {len(scenes_to_export)} top-level scenes ({children_omitted} children omitted)[/dim]")
    else:
        console.print(f"[green]✓[/green] Report exported to [bold]{output}[/bold]")
        console.print(f"[dim]  {len(scenes_to_export)} scenes[/dim]")
    console.print()


@cli.command(name="role-access-summary")
def role_access_summary(
    file_path: Optional[Path] = typer.Argument(
        None, help="Path to Knack application metadata JSON file (optional if using --app-id)"
    ),
    role: Optional[str] = typer.Option(
        None, "--role", help="User profile (role) name to filter by (e.g., 'Admin', 'Manager')"
    ),
    profile_key: Optional[str] = typer.Option(
        None, "--profile-key", help="Profile key to filter by (e.g., 'profile_1')"
    ),
    app_id: Optional[str] = typer.Option(
        None, "--app-id", help="Knack application ID (can also use KNACK_APP_ID env var)"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force refresh cached API data (ignore cache)"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output CSV file path (default: role_access_summary_<role>_<timestamp>.csv)"
    ),
):
    """
    Show all pages and views accessible by a specific user profile (role).

    This command helps troubleshoot access issues by showing exactly which pages
    and views a particular role can access. Perfect for answering questions like:
    "Why can't Joe (Manager role) see the Inventory List view?"

    You must specify either --role (profile name) or --profile-key.

    The output shows:
    - Navigation hierarchy (menu > parent > child)
    - All scenes (pages) the role can access
    - All views within each scene that the role can access
    - Scene keys and slugs for reference

    Examples:
        knack-sleuth role-access-summary --role "Manager" app.json
        knack-sleuth role-access-summary --profile-key "profile_1" --app-id YOUR_APP_ID
        knack-sleuth role-access-summary --role "Admin" app.json -o admin_access.csv
    """
    from pathlib import Path
    import csv
    from knack_sleuth.security import generate_security_report, get_views_for_profile

    # Validate that at least one of role or profile_key is provided
    if not role and not profile_key:
        err_console.print("[red]Error:[/red] You must specify either --role or --profile-key")
        raise typer.Exit(1)

    # Load metadata
    app_export = load_app_metadata(file_path, app_id, refresh)

    # Generate security report
    console.print("[dim]Analyzing scene security with navigation hierarchy...[/dim]")
    report = generate_security_report(app_export.application)

    # Find the target profile
    target_profile_key = None
    target_profile_name = None

    if profile_key:
        # Look up profile name from key
        target_profile_name = report.profiles.get(profile_key)
        if not target_profile_name:
            err_console.print(f"[red]Error:[/red] Profile key '{profile_key}' not found in application")
            console.print("\n[cyan]Available profiles:[/cyan]")
            for pk, pn in report.profiles.items():
                console.print(f"  {pk}: {pn}")
            raise typer.Exit(1)
        target_profile_key = profile_key
    else:
        # Look up profile key from name
        matching_profiles = [(k, v) for k, v in report.profiles.items() if v == role]
        if not matching_profiles:
            # Try case-insensitive match
            matching_profiles = [(k, v) for k, v in report.profiles.items() if v.lower() == role.lower()]

        if not matching_profiles:
            err_console.print(f"[red]Error:[/red] Role '{role}' not found in application")
            console.print("\n[cyan]Available roles:[/cyan]")
            for pk, pn in report.profiles.items():
                console.print(f"  {pn} ({pk})")
            raise typer.Exit(1)

        if len(matching_profiles) > 1:
            err_console.print(f"[yellow]Warning:[/yellow] Multiple profiles match '{role}':")
            for pk, pn in matching_profiles:
                console.print(f"  {pk}: {pn}")
            console.print("\nUsing first match. Use --profile-key to specify exactly.")

        target_profile_key, target_profile_name = matching_profiles[0]

    # Filter scenes accessible by this profile
    console.print(f"[dim]Filtering scenes accessible by '{target_profile_name}' ({target_profile_key})...[/dim]")

    accessible_scenes = []
    scenes_by_key = {s.key: s for s in app_export.application.scenes}

    for scene_analysis in report.scene_analyses:
        # Check if profile has access to this scene
        # Profile has access if:
        # 1. Scene is public (no login required), OR
        # 2. Scene has no profile restrictions (unrestricted authenticated), OR
        # 3. Profile is in the allowed_profiles list
        has_access = (
            not scene_analysis.requires_login or
            (scene_analysis.requires_login and scene_analysis.allowed_profile_count == 0) or
            target_profile_name in scene_analysis.allowed_profiles
        )

        if has_access:
            # Get the actual scene object to check views
            scene = scenes_by_key.get(scene_analysis.scene_key)
            if scene:
                # Get views accessible by this profile
                view_names, view_keys = get_views_for_profile(scene, target_profile_key, target_profile_name)

                accessible_scenes.append({
                    'root_nav': scene_analysis.root_nav,
                    'scene_name': scene_analysis.scene_name,
                    'page_nav': scene_analysis.page_nav,
                    'scene_key': scene_analysis.scene_key,
                    'scene_slug': scene_analysis.scene_slug,
                    'view_names': ', '.join(view_names) if view_names else '',
                    'view_keys': ', '.join(view_keys) if view_keys else '',
                    'view_count': len(view_names),
                })

    # Print summary to console
    console.print()
    console.print("=" * 80)
    console.print(f"[bold cyan]ROLE ACCESS SUMMARY: {report.app_name}[/bold cyan]")
    console.print("=" * 80)
    console.print(f"\nProfile: [bold]{target_profile_name}[/bold] ({target_profile_key})")
    console.print(f"Accessible Scenes: {len(accessible_scenes)}")

    total_views = sum(s['view_count'] for s in accessible_scenes)
    console.print(f"Accessible Views: {total_views}")

    scenes_with_views = sum(1 for s in accessible_scenes if s['view_count'] > 0)
    scenes_without_views = len(accessible_scenes) - scenes_with_views
    console.print(f"  Scenes with Views: {scenes_with_views}")
    console.print(f"  Scenes without Views: {scenes_without_views}")

    # Determine output path with timestamp
    if not output:
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_role_name = target_profile_name.replace(' ', '_').replace('/', '_')
        output = Path(f"role_access_summary_{safe_role_name}_{timestamp}.csv")

    # Export to CSV
    fieldnames = [
        'root_nav',
        'scene_name',
        'page_nav',
        'scene_key',
        'scene_slug',
        'view_names',
        'view_keys',
    ]

    with output.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for scene in accessible_scenes:
            writer.writerow({k: v for k, v in scene.items() if k in fieldnames})

    console.print()
    console.print(f"[green]✓[/green] Summary exported to [bold]{output}[/bold]")
    console.print(f"[dim]  {len(accessible_scenes)} scenes, {total_views} views[/dim]")
    console.print()


@cli.command(name="install-skill")
def install_skill(
    target_dir: Optional[Path] = typer.Option(
        None, "--target", "-t", help="Target directory (default: ~/.claude/skills/knack-explorer)"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Overwrite existing skill file"
    ),
):
    """
    Install the knack-explorer skill for Claude Code.

    This copies the knack-explorer skill definition to your local
    Claude Code skills directory (~/.claude/skills/knack-explorer/),
    making it available as a Claude Code skill in any project.

    Once installed, Claude Code can use the knack-explorer skill to
    run knack-sleuth commands on your behalf when analyzing Knack apps.

    Examples:

        uvx knack-sleuth install-skill

        knack-sleuth install-skill --force

        knack-sleuth install-skill --target ~/custom/skills/knack-explorer
    """
    # Determine target path
    if not target_dir:
        target_dir = Path.home() / ".claude" / "skills" / "knack-explorer"

    target_file = target_dir / "SKILL.md"

    # Read SKILL.md from package data
    try:
        skill_content = resources.files("knack_sleuth").joinpath("data/SKILL.md").read_text()
    except Exception as e:
        err_console.print(f"[red]Error:[/red] Could not read skill file from package: {e}")
        raise typer.Exit(1)

    # Check if already installed
    if target_file.exists() and not force:
        console.print(f"[yellow]Skill already installed at[/yellow] {target_file}")
        warning = _skill_drift_warning(target_file, skill_content)
        if warning:
            console.print(f"[yellow]{warning}[/yellow]")
        else:
            console.print("[dim]Installed skill matches this release[/dim]")
        console.print("[dim]Use --force to overwrite[/dim]")
        raise typer.Exit(0)

    # Create directory and write file
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file.write_text(skill_content)
    except Exception as e:
        err_console.print(f"[red]Error:[/red] Could not write skill file: {e}")
        raise typer.Exit(1)

    console.print()
    console.print(f"[green]✓[/green] Installed knack-explorer skill to [bold]{target_file}[/bold]")
    console.print()
    console.print("[dim]Claude Code will now offer the knack-explorer skill in any project.[/dim]")
    console.print("[dim]The skill lets Claude run knack-sleuth commands when analyzing Knack apps.[/dim]")
    console.print()


if __name__ == "__main__":
    cli()
