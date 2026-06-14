"""Core functionality for loading Knack application metadata.

This module provides the core metadata loading functionality that can be
used both by the CLI and as a library by other codebases.

The cache primitives (:func:`find_valid_cache`, :func:`fetch_metadata_from_api`,
and :func:`write_cache`) are the single source of truth for how metadata is
located, fetched, and persisted. Both the library entry point
(:func:`load_app_metadata`) and the CLI compose these primitives so the caching
behavior stays consistent across every code path.
"""

import json
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta
import glob

import httpx

from knack_sleuth.models import KnackAppMetadata
from knack_sleuth.config import Settings, KNACK_API_BASE_URL

# Cached metadata files older than this are considered stale and re-fetched.
CACHE_MAX_AGE = timedelta(hours=24)


def _cache_glob(app_id: str) -> str:
    """Return the glob pattern used to locate cache files for an app."""
    return f"{app_id}_app_metadata_*.json"


def find_valid_cache(
    app_id: str, max_age: timedelta = CACHE_MAX_AGE
) -> Optional[tuple[Path, float]]:
    """Find the most recent non-stale cache file for an application.

    Looks in the current working directory for cache files matching the app's
    naming pattern and returns the newest one that is younger than ``max_age``.

    Args:
        app_id: Knack application ID.
        max_age: Maximum age before a cache file is considered stale.

    Returns:
        A ``(path, age_in_hours)`` tuple for the freshest valid cache file, or
        ``None`` if no usable cache file exists.
    """
    cache_files = sorted(glob.glob(_cache_glob(app_id)), reverse=True)
    if not cache_files:
        return None

    latest = Path(cache_files[0])
    age = datetime.now() - datetime.fromtimestamp(latest.stat().st_mtime)
    if age < max_age:
        return latest, age.total_seconds() / 3600
    return None


def fetch_metadata_from_api(app_id: str) -> dict:
    """Fetch raw application metadata from the public Knack metadata endpoint.

    The metadata endpoint is public: it only requires the application ID header
    and does not use an API key or any other authentication.

    Args:
        app_id: Knack application ID.

    Returns:
        The decoded JSON response as a dict.

    Raises:
        httpx.HTTPStatusError: If the API responds with an error status.
        httpx.RequestError: If the network request fails.
    """
    api_url = f"{KNACK_API_BASE_URL}/applications/{app_id}"
    response = httpx.get(
        api_url,
        headers={"X-Knack-Application-Id": app_id},
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()


def write_cache(app_id: str, data: dict) -> Path:
    """Write raw metadata to a timestamped cache file and return its path."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    cache_path = Path(f"{app_id}_app_metadata_{timestamp}.json")
    with cache_path.open("w") as f:
        json.dump(data, f, indent=2)
    return cache_path


def load_app_metadata(
    file_path: Optional[Path] = None,
    app_id: Optional[str] = None,
    refresh: bool = False,
    no_cache: bool = False,
) -> KnackAppMetadata:
    """
    Load Knack application metadata from file or API.

    This function can be used both by the CLI and as a library function.

    Args:
        file_path: Path to a local JSON metadata file. If provided, loads from file.
        app_id: Knack application ID. If provided without file_path, fetches from API.
                Note: The Knack metadata endpoint is public and does not require an API key.
        refresh: Force refresh from API, ignoring cache (only applies when using API).
        no_cache: Skip cache entirely - don't read from cache and don't write to cache.
                  Useful for library usage where you don't want filesystem side effects.

    Returns:
        KnackAppMetadata: Parsed Pydantic model of the application metadata.

    Raises:
        FileNotFoundError: If file_path is provided but doesn't exist.
        json.JSONDecodeError: If the JSON is invalid.
        httpx.HTTPStatusError: If API request fails.
        httpx.RequestError: If network connection fails.
        ValueError: If neither file_path nor app_id is provided.

    Examples:
        # Load from file
        metadata = load_app_metadata(file_path=Path("my_app.json"))

        # Load from API with caching
        metadata = load_app_metadata(app_id="abc123")

        # Load from API without any caching (library usage)
        metadata = load_app_metadata(app_id="abc123", no_cache=True)

        # Force refresh from API
        metadata = load_app_metadata(app_id="abc123", refresh=True)
    """
    settings = Settings()

    # Determine source: file or HTTP
    if file_path:
        # Load from file
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        with file_path.open() as f:
            data = json.load(f)
        return KnackAppMetadata(**data)

    # Load from API (with optional caching)
    final_app_id = app_id or settings.knack_app_id

    if not final_app_id:
        raise ValueError(
            "App ID is required. Provide via app_id parameter or KNACK_APP_ID environment variable."
        )

    # Reuse a fresh cache file when allowed.
    if not no_cache and not refresh:
        cached = find_valid_cache(final_app_id)
        if cached:
            cache_path, _ = cached
            try:
                with cache_path.open() as f:
                    data = json.load(f)
                return KnackAppMetadata(**data)
            except Exception:
                # Corrupt/unreadable cache: fall through to a fresh API fetch.
                pass

    # Fetch from the public Knack metadata endpoint (no API key required).
    data = fetch_metadata_from_api(final_app_id)
    app_export = KnackAppMetadata(**data)

    # Persist to cache unless caching is disabled.
    if not no_cache:
        write_cache(final_app_id, data)

    return app_export
