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

from knack_sleuth.models import KnackAppExport
from knack_sleuth.sleuth import KnackSleuth
from knack_sleuth.config import Settings, KNACK_BUILDER_BASE_URL, KNACK_NG_BUILDER_BASE_URL

cli = typer.Typer()
console = Console()


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
        final_api_key = api_key or settings.knack_api_key
        
        if not final_app_id:
            console.print(
                "[red]Error:[/red] App ID is required. Provide via --app-id or KNACK_APP_ID environment variable."
            )
            raise typer.Exit(1)
        
        if not final_api_key:
            console.print(
                "[red]Error:[/red] API key is required. Provide via --api-key or KNACK_API_KEY environment variable."
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
            # Fetch from Knack API
            api_url = f"https://api.knack.com/v1/applications/{final_app_id}"
            
            try:
                if refresh:
                    console.print("[cyan]Forcing refresh from API...[/cyan]")
                
                with console.status(f"[cyan]Fetching metadata from Knack API..."):
                    response = httpx.get(
                        api_url,
                        headers={
                            "X-Knack-Application-Id": final_app_id,
                            "X-Knack-REST-API-Key": final_api_key,
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


@cli.command(name="download-metadata")
def download_metadata(
    output_file: Optional[Path] = typer.Argument(
        None, help="Output file path (default: {APP_ID}_metadata.json)"
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
    final_api_key = api_key or settings.knack_api_key
    
    if not final_app_id:
        console.print(
            "[red]Error:[/red] App ID is required. Provide via --app-id or KNACK_APP_ID environment variable."
        )
        raise typer.Exit(1)
    
    if not final_api_key:
        console.print(
            "[red]Error:[/red] API key is required. Provide via --api-key or KNACK_API_KEY environment variable."
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
        # Fetch from Knack API
        api_url = f"https://api.knack.com/v1/applications/{final_app_id}"
        
        try:
            if refresh:
                console.print("[cyan]Forcing refresh from API...[/cyan]")
            
            with console.status(f"[cyan]Fetching metadata from Knack API..."):
                response = httpx.get(
                    api_url,
                    headers={
                        "X-Knack-Application-Id": final_app_id,
                        "X-Knack-REST-API-Key": final_api_key,
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


if __name__ == "__main__":
    cli()
