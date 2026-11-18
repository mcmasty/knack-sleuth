"""`knack-sleuth cache ...`: inspect and manage the local metadata cache."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from knack_sleuth.config import Settings
from knack_sleuth.core import get_cache_dir

from ._common import cli, console

cache_app = typer.Typer(help="Inspect and manage the local metadata cache.")
cli.add_typer(cache_app, name="cache")


def _cache_files(app_id: str | None = None) -> list[Path]:
    """All cache files (optionally for one app), newest first."""
    pattern = f"{app_id}_app_metadata_*.json" if app_id else "*_app_metadata_*.json"
    return sorted(get_cache_dir().glob(pattern), reverse=True)


@cache_app.command("dir")
def cache_dir():
    """Print the cache directory path."""
    typer.echo(str(get_cache_dir()))


@cache_app.command("list")
def cache_list(
    app_id: Annotated[
        str | None,
        typer.Option("--app-id", help="Only show cache files for this application ID"),
    ] = None,
):
    """List cached metadata files with age, size, and freshness."""

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
        table.add_row(
            path.name,
            path.name.split("_app_metadata_")[0],
            f"{age.total_seconds() / 3600:.1f}h",
            f"{path.stat().st_size / 1024:.1f} KB",
            "fresh" if age < ttl else "[red]stale[/red]",
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
    app_id: Annotated[
        str | None,
        typer.Option(
            "--app-id", help="Only delete cache files for this application ID"
        ),
    ] = None,
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
