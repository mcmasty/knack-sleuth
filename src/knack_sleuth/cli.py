import json
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta
import glob

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

from knack_sleuth import __version__
from knack_sleuth.models import KnackAppExport
from knack_sleuth.sleuth import KnackSleuth
from knack_sleuth.config import Settings, KNACK_BUILDER_BASE_URL, KNACK_NG_BUILDER_BASE_URL

cli = typer.Typer()
console = Console()


def version_callback(value: bool):
    """Display version and exit."""
    if value:
        console.print(f"knack-sleuth version {__version__}")
        raise typer.Exit()


def load_app_metadata(
    file_path: Optional[Path],
    app_id: Optional[str],
    api_key: Optional[str],
    refresh: bool = False,
) -> KnackAppExport:
    """
    Load Knack application metadata from file or API.
    
    Handles caching automatically when using API.
    """
    settings = Settings()
    
    # Determine source: file or HTTP
    if file_path:
        # Load from file
        if not file_path.exists():
            console.print(f"[red]Error:[/red] File not found: {file_path}")
            raise typer.Exit(1)
        
        try:
            with file_path.open() as f:
                data = json.load(f)
            return KnackAppExport(**data)
        except json.JSONDecodeError as e:
            console.print(f"[red]Error:[/red] Invalid JSON: {e}")
            raise typer.Exit(1)
        except Exception as e:
            console.print(f"[red]Error:[/red] Failed to parse metadata: {e}")
            raise typer.Exit(1)
    else:
        # Load from API (with caching)
        final_app_id = app_id or settings.knack_app_id
        
        if not final_app_id:
            console.print(
                "[red]Error:[/red] App ID is required. Provide via --app-id or KNACK_APP_ID environment variable."
            )
            raise typer.Exit(1)
        
        # Check for cached file
        cached_file = None
        cache_age_hours = None
        
        if not refresh:
            # Look for existing cache files for this app
            cache_pattern = f"{final_app_id}_app_metadata_*.json"
            cache_files = sorted(glob.glob(cache_pattern), reverse=True)
            
            if cache_files:
                latest_cache = Path(cache_files[0])
                cache_modified = datetime.fromtimestamp(latest_cache.stat().st_mtime)
                cache_age = datetime.now() - cache_modified
                cache_age_hours = cache_age.total_seconds() / 3600
                
                # Use cache if less than 24 hours old
                if cache_age < timedelta(hours=24):
                    cached_file = latest_cache
                    console.print(
                        f"[dim]Using cached data from {latest_cache.name} "
                        f"(age: {cache_age_hours:.1f}h)[/dim]"
                    )
        
        # Load from cache or fetch from API
        if cached_file:
            try:
                with cached_file.open() as f:
                    data = json.load(f)
                return KnackAppExport(**data)
            except Exception as e:
                console.print(
                    f"[yellow]Warning:[/yellow] Failed to load cache: {e}. Fetching from API..."
                )
                cached_file = None  # Force API fetch
        
        if not cached_file:
            # Fetch from Knack API (metadata endpoint doesn't require API key)
            api_url = f"https://api.knack.com/v1/applications/{final_app_id}"
            
            try:
                if refresh:
                    console.print("[cyan]Forcing refresh from API...[/cyan]")
                
                with console.status(f"[cyan]Fetching metadata from Knack API..."):
                    response = httpx.get(
                        api_url,
                        headers={
                            "X-Knack-Application-Id": final_app_id,
                        },
                        timeout=30.0,
                    )
                    response.raise_for_status()
                    data = response.json()
                
                app_export = KnackAppExport(**data)
                
                # Save to cache file
                timestamp = datetime.now().strftime("%Y%m%d%H%M")
                cache_filename = f"{final_app_id}_app_metadata_{timestamp}.json"
                cache_path = Path(cache_filename)
                
                with cache_path.open('w') as f:
                    json.dump(data, f, indent=2)
                
                console.print(f"[dim]Cached metadata to {cache_filename}[/dim]")
                return app_export
                
            except httpx.HTTPStatusError as e:
                console.print(f"[red]Error:[/red] HTTP {e.response.status_code}: {e.response.text}")
                raise typer.Exit(1)
            except httpx.RequestError as e:
                console.print(f"[red]Error:[/red] Failed to connect to Knack API: {e}")
                raise typer.Exit(1)
            except Exception as e:
                console.print(f"[red]Error:[/red] Failed to parse API response: {e}")
                raise typer.Exit(1)


@cli.callback()
def main(
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
    pass


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
    api_key: Optional[str] = typer.Option(
        None, "--api-key", help="Knack API key (can also use KNACK_API_KEY env var)"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force refresh cached API data (ignore cache)"
    ),
    show_fields: bool = typer.Option(
        True, "--show-fields/--no-fields", help="Show field-level usages"
    ),
):
    """
    Search for all usages of an object in a Knack application.

    This will find where the object is used in connections, views, and other places.
    By default, it also cascades to show usages of all fields in the object.

    You can either:
    1. Provide a local JSON file: knack-sleuth search-object object_12 path/to/file.json
    2. Fetch from API: knack-sleuth search-object object_12 --app-id YOUR_APP_ID --api-key YOUR_KEY
    3. Use environment variables: KNACK_APP_ID and KNACK_API_KEY
    
    When fetching from API, data is automatically cached locally and reused for 24 hours.
    Use --refresh to force fetching fresh data from the API.
    """
    # Load metadata
    app_export = load_app_metadata(file_path, app_id, api_key, refresh)

    # Create search engine
    sleuth = KnackSleuth(app_export)

    # Find the object (support both key and name lookup)
    target_object = None
    if object_identifier.lower().startswith("object_"):
        # Search by key (case insensitive)
        for obj in sleuth.app.objects:
            if obj.key.lower() == object_identifier.lower():
                target_object = obj
                object_identifier = obj.key
                break
    else:
        # Search by name
        for obj in sleuth.app.objects:
            if obj.name.lower() == object_identifier.lower():
                target_object = obj
                object_identifier = obj.key
                break

    if not target_object:
        console.print(
            f"[red]Error:[/red] Object '{object_identifier}' not found in application"
        )
        raise typer.Exit(1)

    # Perform search
    results = sleuth.search_object(object_identifier)

    # Display results
    console.print(
        Panel(
            f"[bold cyan]{target_object.name}[/bold cyan] ({object_identifier})",
            title="Object Search Results",
            subtitle=f"{len(target_object.fields)} fields",
        )
    )

    # Show object-level usages
    object_usages = results.get("object_usages", [])
    console.print(f"\n[bold cyan]Object-level usages:[/bold cyan] {len(object_usages)}")

    if object_usages:
        for usage in object_usages:
            console.print(f"  [yellow]•[/yellow] [{usage.location_type}] {usage.context}")
    else:
        console.print("  [dim]No direct object usages found[/dim]")

    # Show field-level usages
    if show_fields:
        field_results = {k: v for k, v in results.items() if k.startswith("field_")}
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
                        console.print(f"    [yellow]•[/yellow] [{usage.location_type}] {usage.context}")
        else:
            console.print("\n[dim]No field usages found[/dim]")

    # Builder Pages to Review
    settings = Settings()
    # Use account slug for builder URLs (not application slug)
    account_slug = app_export.application.account.get('slug', app_export.application.slug)
    
    # Collect unique scenes from all usages
    scenes_to_review = set()
    for usage in object_usages:
        if 'scene_key' in usage.details:
            scenes_to_review.add(usage.details['scene_key'])
    
    # Also collect scenes from field usages
    if show_fields:
        for field_key, usages in results.items():
            if field_key.startswith("field_"):
                for usage in usages:
                    if 'scene_key' in usage.details:
                        scenes_to_review.add(usage.details['scene_key'])
    
    if scenes_to_review:
        console.print(f"\n[bold cyan]Builder Pages to Review:[/bold cyan] {len(scenes_to_review)} scenes")
        console.print()
        
        # Build URLs based on builder version
        if settings.knack_next_gen_builder:
            # Next-Gen builder
            for scene_key in sorted(scenes_to_review):
                url = f"{KNACK_NG_BUILDER_BASE_URL}/{account_slug}/portal/pages/{scene_key}"
                console.print(f"  [link={url}]{url}[/link]")
        else:
            # Classic builder
            for scene_key in sorted(scenes_to_review):
                url = f"{KNACK_BUILDER_BASE_URL}/{account_slug}/portal/pages/{scene_key}"
                console.print(f"  [link={url}]{url}[/link]")
        
        console.print()
        console.print(f"[dim]Tip: Set KNACK_NEXT_GEN_BUILDER=true to use Next-Gen builder URLs[/dim]")

    console.print()


@cli.command(name="list-objects")
def list_objects(
    file_path: Optional[Path] = typer.Argument(
        None, help="Path to Knack application metadata JSON file (optional if using --app-id)"
    ),
    app_id: Optional[str] = typer.Option(
        None, "--app-id", help="Knack application ID (can also use KNACK_APP_ID env var)"
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", help="Knack API key (can also use KNACK_API_KEY env var)"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force refresh cached API data (ignore cache)"
    ),
    sort_by_rows: bool = typer.Option(
        False, "--sort-by-rows", help="Sort by row count (largest first) instead of by name"
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
    
    You can either:
    1. Provide a local JSON file: knack-sleuth list-objects path/to/file.json
    2. Fetch from API: knack-sleuth list-objects --app-id YOUR_APP_ID --api-key YOUR_KEY
    3. Use environment variables: KNACK_APP_ID and KNACK_API_KEY
    
    When fetching from API, data is automatically cached locally and reused for 24 hours.
    Use --refresh to force fetching fresh data from the API.
    """
    # Load metadata
    app_export = load_app_metadata(file_path, app_id, api_key, refresh)
    
    # Create table
    table = Table(title=f"[bold cyan]{app_export.application.name}[/bold cyan] - Objects")
    table.add_column("Key", style="dim")
    table.add_column("Name", style="bold cyan")
    table.add_column("Rows", justify="right", style="magenta")
    table.add_column("Fields", justify="right", style="yellow")
    table.add_column("Ca", justify="right", style="blue")  # Afferent (inbound)
    table.add_column("Ce", justify="right", style="red")   # Efferent (outbound)
    table.add_column("Total", justify="right", style="green")
    
    # Add rows and calculate totals
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
        
        table.add_row(
            obj.key,
            obj.name,
            f"{row_count:,}",  # Format with comma separators
            str(field_count),
            str(afferent_count),
            str(efferent_count),
            str(connection_count),
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
    api_key: Optional[str] = typer.Option(
        None, "--api-key", help="Knack API key (can also use KNACK_API_KEY env var)"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force refresh cached API data (ignore cache)"
    ),
):
    """
    Show coupling relationships for a specific object.

    Displays:
    - Afferent Coupling (Ca): Objects that depend on this object (inbound connections)
    - Efferent Coupling (Ce): Objects this object depends on (outbound connections)
    
    This provides a focused view of an object's dependencies from its perspective.
    """
    # Load metadata
    app_export = load_app_metadata(file_path, app_id, api_key, refresh)
    
    # Find the object (support both key and name lookup)
    target_object = None
    if object_identifier.lower().startswith("object_"):
        # Search by key (case insensitive)
        for obj in app_export.application.objects:
            if obj.key.lower() == object_identifier.lower():
                target_object = obj
                object_identifier = obj.key
                break
    else:
        # Search by name
        for obj in app_export.application.objects:
            if obj.name.lower() == object_identifier.lower():
                target_object = obj
                object_identifier = obj.key
                break
    
    if not target_object:
        console.print(
            f"[red]Error:[/red] Object '{object_identifier}' not found in application"
        )
        raise typer.Exit(1)
    
    # Display header
    console.print()
    console.print(
        Panel(
            f"[bold cyan]{target_object.name}[/bold cyan] ({object_identifier})",
            title="Object Coupling",
            subtitle=f"Ca: {len(target_object.connections.inbound) if target_object.connections else 0} | Ce: {len(target_object.connections.outbound) if target_object.connections else 0}",
        )
    )
    
    # Build object lookup for names
    objects_by_key = {obj.key: obj for obj in app_export.application.objects}
    
    # Afferent Coupling (Ca) - Inbound connections
    if target_object.connections and target_object.connections.inbound:
        console.print(f"\n[bold cyan]Afferent Coupling (Ca):[/bold cyan] {len(target_object.connections.inbound)} objects depend on this")
        console.print("[dim]Objects that have connections pointing TO this object[/dim]\n")
        
        for conn in sorted(target_object.connections.inbound, key=lambda c: objects_by_key.get(c.object, type('obj', (), {'name': ''})).name):
            source_obj = objects_by_key.get(conn.object)
            if source_obj:
                relationship = f"{conn.has} → {conn.belongs_to}"
                console.print(
                    f"  [yellow]←[/yellow] [bold cyan]{source_obj.name}[/bold cyan] ({conn.object})\n"
                    f"     via [dim]{conn.name}[/dim] ({conn.key}) [{relationship}]"
                )
    else:
        console.print(f"\n[bold cyan]Afferent Coupling (Ca):[/bold cyan] 0 objects")
        console.print("[dim]No objects depend on this object[/dim]")
    
    # Efferent Coupling (Ce) - Outbound connections
    if target_object.connections and target_object.connections.outbound:
        console.print(f"\n[bold cyan]Efferent Coupling (Ce):[/bold cyan] {len(target_object.connections.outbound)} objects this depends on")
        console.print("[dim]Objects that this object connects TO[/dim]\n")
        
        for conn in sorted(target_object.connections.outbound, key=lambda c: objects_by_key.get(c.object, type('obj', (), {'name': ''})).name):
            target_obj = objects_by_key.get(conn.object)
            if target_obj:
                relationship = f"{conn.has} → {conn.belongs_to}"
                console.print(
                    f"  [yellow]→[/yellow] [bold cyan]{target_obj.name}[/bold cyan] ({conn.object})\n"
                    f"     via [dim]{conn.name}[/dim] ({conn.key}) [{relationship}]"
                )
    else:
        console.print(f"\n[bold cyan]Efferent Coupling (Ce):[/bold cyan] 0 objects")
        console.print("[dim]This object does not depend on other objects[/dim]")
    
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
        console.print(
            "[red]Error:[/red] App ID is required. Provide via --app-id or KNACK_APP_ID environment variable."
        )
        raise typer.Exit(1)
    
    # Determine output filename
    if not output_file:
        output_file = Path(f"{final_app_id}_metadata.json")
    
    # Check for cached file
    cached_file = None
    
    if not refresh:
        # Look for existing cache files for this app
        cache_pattern = f"{final_app_id}_app_metadata_*.json"
        cache_files = sorted(glob.glob(cache_pattern), reverse=True)
        
        if cache_files:
            latest_cache = Path(cache_files[0])
            cache_modified = datetime.fromtimestamp(latest_cache.stat().st_mtime)
            cache_age = datetime.now() - cache_modified
            cache_age_hours = cache_age.total_seconds() / 3600
            
            # Use cache if less than 24 hours old
            if cache_age < timedelta(hours=24):
                cached_file = latest_cache
                console.print(
                    f"[dim]Using cached data from {latest_cache.name} "
                    f"(age: {cache_age_hours:.1f}h)[/dim]"
                )
    
    # Load from cache or fetch from API
    if cached_file:
        try:
            with cached_file.open() as f:
                data = json.load(f)
        except Exception as e:
            console.print(
                f"[yellow]Warning:[/yellow] Failed to load cache: {e}. Fetching from API..."
            )
            cached_file = None  # Force API fetch
    
    if not cached_file:
        # Fetch from Knack API (no authentication required for metadata endpoint)
        api_url = f"https://api.knack.com/v1/applications/{final_app_id}"
        
        try:
            if refresh:
                console.print("[cyan]Forcing refresh from API...[/cyan]")
            
            with console.status(f"[cyan]Fetching metadata from Knack API..."):
                response = httpx.get(
                    api_url,
                    headers={
                        "X-Knack-Application-Id": final_app_id,
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
            
        except httpx.HTTPStatusError as e:
            console.print(f"[red]Error:[/red] HTTP {e.response.status_code}: {e.response.text}")
            raise typer.Exit(1)
        except httpx.RequestError as e:
            console.print(f"[red]Error:[/red] Failed to connect to Knack API: {e}")
            raise typer.Exit(1)
        except Exception as e:
            console.print(f"[red]Error:[/red] Failed to fetch metadata: {e}")
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
        console.print(f"[red]Error:[/red] Failed to save file: {e}")
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
    api_key: Optional[str] = typer.Option(
        None, "--api-key", help="Knack API key (can also use KNACK_API_KEY env var)"
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
        knack-sleuth impact-analysis "Institution" my_app.json --format markdown
    """
    # Load metadata
    app_export = load_app_metadata(file_path, app_id, api_key, refresh)

    # Create search engine
    sleuth = KnackSleuth(app_export)

    # Find the target (support both key and name lookup)
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
        for obj in sleuth.app.objects:
            if obj.name.lower() == target_identifier.lower():
                target_key = obj.key
                target_type = "object"
                break

        if not target_key:
            # Search fields
            for obj in sleuth.app.objects:
                for field in obj.fields:
                    if field.name.lower() == target_identifier.lower():
                        target_key = field.key
                        target_type = "field"
                        break
                if target_key:
                    break

    if not target_key:
        console.print(
            f"[red]Error:[/red] Could not find object or field '{target_identifier}'"
        )
        raise typer.Exit(1)

    # Generate analysis
    analysis = sleuth.generate_impact_analysis(target_key, target_type)

    if "error" in analysis:
        console.print(f"[red]Error:[/red] {analysis['error']}")
        raise typer.Exit(1)

    # Format output
    if output_format == "json":
        output_content = json.dumps(analysis, indent=2)
    elif output_format == "yaml":
        try:
            import yaml
            output_content = yaml.dump(analysis, default_flow_style=False, sort_keys=False)
        except ImportError:
            console.print(
                "[yellow]Warning:[/yellow] PyYAML not installed. Falling back to JSON.\n"
                "Install with: uv add pyyaml"
            )
            output_content = json.dumps(analysis, indent=2)
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
        console.print(f"[red]Error:[/red] Unknown format '{output_format}'")
        raise typer.Exit(1)

    # Output to file or stdout
    if output_file:
        try:
            with output_file.open('w') as f:
                f.write(output_content)
            console.print(f"[green]✓[/green] Analysis saved to [bold]{output_file}[/bold]")
        except Exception as e:
            console.print(f"[red]Error:[/red] Failed to save file: {e}")
            raise typer.Exit(1)
    else:
        console.print(output_content)


@cli.command(name="app-summary")
def app_summary(
    file_path: Optional[Path] = typer.Argument(
        None, help="Path to Knack application metadata JSON file (optional if using --app-id)"
    ),
    app_id: Optional[str] = typer.Option(
        None, "--app-id", help="Knack application ID (can also use KNACK_APP_ID env var)"
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", help="Knack API key (can also use KNACK_API_KEY env var)"
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
    app_export = load_app_metadata(file_path, app_id, api_key, refresh)

    # Create search engine and generate summary
    sleuth = KnackSleuth(app_export)
    
    with console.status("[cyan]Analyzing application architecture..."):
        summary = sleuth.generate_app_summary()

    # Format output
    if output_format == "json":
        output_content = json.dumps(summary, indent=2)
    elif output_format == "yaml":
        try:
            import yaml
            output_content = yaml.dump(summary, default_flow_style=False, sort_keys=False)
        except ImportError:
            console.print(
                "[yellow]Warning:[/yellow] PyYAML not installed. Falling back to JSON.\n"
                "Install with: uv add pyyaml"
            )
            output_content = json.dumps(summary, indent=2)
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
        console.print(f"[red]Error:[/red] Unknown format '{output_format}'")
        raise typer.Exit(1)

    # Output to file or stdout
    if output_file:
        try:
            with output_file.open('w') as f:
                f.write(output_content)
            console.print(f"[green]✓[/green] Summary saved to [bold]{output_file}[/bold]")
        except Exception as e:
            console.print(f"[red]Error:[/red] Failed to save file: {e}")
            raise typer.Exit(1)
    else:
        console.print(output_content)


if __name__ == "__main__":
    cli()
