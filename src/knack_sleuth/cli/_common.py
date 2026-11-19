"""Shared CLI plumbing: the Typer app, consoles, error exits, metadata loading
and the small output helpers every command uses."""

import csv
import json
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, TypeVar

import httpx
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.markup import escape
from rich.style import Style
from rich.text import Text

from knack_sleuth.config import Settings
from knack_sleuth.core import (
    builder_url,
    fetch_metadata_from_api,
    find_valid_cache,
    write_cache,
)
from knack_sleuth.core import load_app_metadata as core_load_metadata
from knack_sleuth.lookup import resolve_object, suggest_object_names
from knack_sleuth.models import KnackAppMetadata, KnackObject

console = Console()
err_console = Console(stderr=True)  # status + error output; keeps stdout clean for data

# No locals in crash dumps: commands hold raw metadata, and show-rules in
# particular holds email bodies and addresses it must never print.
cli = typer.Typer(pretty_exceptions_show_locals=False)

APP_ID_REQUIRED = (
    "App ID is required. Provide via --app-id or KNACK_APP_ID environment variable."
)

T = TypeVar("T")


# --- Errors -----------------------------------------------------------------


def fail(message: str) -> NoReturn:
    """Print an error to stderr and exit 1.

    The message is plain text (no callers pass markup), so it is escaped here.
    """
    err_console.print(f"[red]Error:[/red] {escape(message)}")
    raise typer.Exit(1) from None


@contextmanager
def exit_on_error(prefix: str = "") -> Iterator[None]:
    """Turn any exception raised in the block into a one-line error and exit 1.

    Intentional exits pass through untouched; typer.Exit is an Exception, so
    without that a broad handler would print a second, bogus error.
    """
    try:
        yield
    except typer.Exit:
        raise
    except httpx.HTTPStatusError as e:
        fail(f"HTTP {e.response.status_code}: {e.response.text}")
    except httpx.RequestError as e:
        fail(f"Failed to connect to Knack API: {e}")
    except ValidationError as e:
        fail(f"{prefix}{describe_validation_error(e)}")
    except Exception as e:
        fail(f"{prefix}{e}")


def describe_validation_error(error: ValidationError) -> str:
    """The first problem in Knack metadata as one line, with its JSON path."""
    first = error.errors()[0]
    path = ""
    for part in first["loc"]:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    got = ""
    if first["type"] != "missing":  # a missing key's input is its parent
        value = first.get("input")
        got = ", got " + ("null" if value is None else type(value).__name__)
    more = len(error.errors()) - 1
    extra = f" (and {more} more)" if more else ""
    return f"Invalid metadata at {path}: {first['msg']}{got}{extra}"


def validate_choice(value: str, valid: Iterable[str], label: str = "format") -> None:
    """Exit with an error unless value is one of valid."""
    valid = list(valid)
    if value not in valid:
        fail(f"Invalid {label} '{value}'. Use one of: {', '.join(valid)}")


def validate_output_format(output_format: str) -> None:
    """Exit with an error unless the format is rich or json."""
    if output_format not in ("rich", "json"):
        fail(f"Invalid format '{output_format}'. Use rich or json.")


# --- Metadata loading ---------------------------------------------------------


def require_app_id(app_id: str | None) -> str:
    """The app ID from the option or KNACK_APP_ID, or exit."""
    final_app_id = app_id or Settings().knack_app_id
    if not final_app_id:
        fail(APP_ID_REQUIRED)
    return final_app_id


def _from_cache(app_id: str, parse: Callable[[dict], T]) -> T | None:
    """Parse a fresh cache file, or None when there is none or it is unusable."""
    with exit_on_error():
        cached = find_valid_cache(app_id)
    if not cached:
        return None
    cache_path, cache_age_hours = cached
    try:
        with cache_path.open() as f:
            result = parse(json.load(f))
    except Exception:
        # Corrupt/unreadable cache: the caller falls through to an API fetch.
        err_console.print(
            f"[yellow]Warning:[/yellow] Failed to read cache "
            f"{escape(cache_path.name)}; fetching fresh data..."
        )
        return None
    err_console.print(
        f"[dim]Using cached data from {escape(cache_path.name)} "
        f"(age: {cache_age_hours:.1f}h)[/dim]"
    )
    return result


def _from_api(app_id: str, refresh: bool) -> dict:
    """Fetch metadata from the public Knack endpoint and cache it."""
    if refresh:
        err_console.print("[cyan]Forcing refresh from API...[/cyan]")
    with exit_on_error():
        with err_console.status("[cyan]Fetching metadata from Knack API..."):
            data = fetch_metadata_from_api(app_id)
        cache_path = write_cache(app_id, data)
    err_console.print(f"[dim]Cached metadata to {escape(cache_path.name)}[/dim]")
    return data


def load_by_app_id(app_id: str, refresh: bool, parse: Callable[[dict], T]) -> T:
    """Load metadata for an app from a fresh cache file, else from the API.

    Note: The Knack metadata endpoint is public and does not require an API key.
    """
    if not refresh:
        cached = _from_cache(app_id, parse)
        if cached is not None:
            return cached
    data = _from_api(app_id, refresh)
    with exit_on_error():
        return parse(data)


def _parse_metadata(data: dict) -> KnackAppMetadata:
    return KnackAppMetadata(**data)


def load_app_metadata(
    file_path: Path | None,
    app_id: str | None,
    refresh: bool = False,
) -> KnackAppMetadata:
    """
    CLI wrapper for loading Knack application metadata.

    Adds user-friendly console output and error handling on top of the core
    cache primitives. For library usage, import from knack_sleuth.core instead.
    """
    if file_path:
        with exit_on_error():
            return core_load_metadata(file_path=file_path)
    return load_by_app_id(require_app_id(app_id), refresh, _parse_metadata)


# --- Lookups ----------------------------------------------------------------


def print_suggestions(suggestions: list[str]) -> None:
    if suggestions:
        names = "[/cyan], [cyan]".join(escape(s) for s in suggestions)
        console.print(f"Did you mean: [cyan]{names}[/cyan]?")


def exit_ambiguous_field(identifier: str, matches: list) -> NoReturn:
    """List every field a name matches, then exit 1."""
    console.print(
        f"[yellow]Ambiguous:[/yellow] field name '{escape(identifier)}' matches "
        f"{len(matches)} fields:"
    )
    for obj, field in matches:
        console.print(
            escape(f"  {field.key} — {obj.name} → {field.name} ({field.type})")
        )
    console.print("\nRe-run with the field key to disambiguate.")
    raise typer.Exit(1)


def resolve_object_or_exit(
    app_export: KnackAppMetadata, identifier: str
) -> KnackObject:
    """Resolve an object by key or name, or exit with suggestions."""
    obj = resolve_object(app_export.application, identifier)
    if obj:
        return obj

    err_console.print(
        f"[red]Error:[/red] Object '{escape(identifier)}' not found in application"
    )
    print_suggestions(suggest_object_names(app_export.application, identifier))
    raise typer.Exit(1)


# --- Output -----------------------------------------------------------------


def scene_url(app_export: KnackAppMetadata, scene_key: str) -> str:
    return builder_url(
        app_export.application,
        scene_key,
        next_gen=Settings().knack_next_gen_builder,
    )


def print_builder_pages(app_export: KnackAppMetadata, scenes_to_review: set) -> None:
    """Print clickable Knack builder URLs for a set of scene keys."""
    if not scenes_to_review:
        return

    console.print(
        f"\n[bold cyan]Builder Pages to Review:[/bold cyan] {len(scenes_to_review)} scenes"
    )
    console.print()
    for scene_key in sorted(scenes_to_review):
        url = scene_url(app_export, scene_key)
        # A Text, not [link=...] markup: a "[" in the URL would break the tag.
        console.print(Text.assemble("  ", (url, Style(link=url))))
    console.print()
    console.print(
        "[dim]Tip: Set KNACK_NEXT_GEN_BUILDER=true to use Next-Gen builder URLs[/dim]"
    )


def print_usages(usages: Iterable, indent: str = "  ") -> None:
    for usage in usages:
        console.print(
            f"{indent}[yellow]•[/yellow] \\[{usage.location_type}] {escape(usage.context)}"
        )


def scene_keys_of(usages: Iterable) -> set[str]:
    """Scene keys named in usage details, for builder links."""
    return {u.details["scene_key"] for u in usages if "scene_key" in u.details}


def emit(content: str, output_file: Path | None, saved_label: str) -> None:
    """Write content to output_file, or echo it to stdout when there is none."""
    if not output_file:
        typer.echo(content)
        return
    with exit_on_error("Failed to save file: "):
        output_file.write_text(content)
    console.print(
        f"[green]✓[/green] {saved_label} saved to [bold]{escape(str(output_file))}[/bold]"
    )


def write_csv(
    path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]
) -> None:
    """Write rows to a CSV, keeping only the named columns."""
    with exit_on_error("Failed to save file: "), path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def timestamp() -> str:
    """UTC timestamp for default output filenames."""
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def file_size_kb(path: Path) -> str:
    return f"{path.stat().st_size / 1024:.1f} KB"
