"""Core functionality for loading Knack application metadata.

This module provides the core metadata loading functionality that can be
used both by the CLI and as a library by other codebases.
"""

import json
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta
import glob

import httpx

from knack_sleuth.models import KnackAppMetadata
from knack_sleuth.config import Settings


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
    
    # Check for cached file (unless no_cache is True)
    cached_file = None
    
    if not no_cache and not refresh:
        # Look for existing cache files for this app
        cache_pattern = f"{final_app_id}_app_metadata_*.json"
        cache_files = sorted(glob.glob(cache_pattern), reverse=True)
        
        if cache_files:
            latest_cache = Path(cache_files[0])
            cache_modified = datetime.fromtimestamp(latest_cache.stat().st_mtime)
            cache_age = datetime.now() - cache_modified
            
            # Use cache if less than 24 hours old
            if cache_age < timedelta(hours=24):
                cached_file = latest_cache
    
    # Load from cache if available
    if cached_file:
        try:
            with cached_file.open() as f:
                data = json.load(f)
            return KnackAppMetadata(**data)
        except Exception:
            # If cache fails, fall through to API fetch
            cached_file = None
    
    # Fetch from Knack API (metadata endpoint doesn't require API key)
    api_url = f"https://api.knack.com/v1/applications/{final_app_id}"
    
    response = httpx.get(
        api_url,
        headers={
            "X-Knack-Application-Id": final_app_id,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    
    app_export = KnackAppMetadata(**data)
    
    # Save to cache file (unless no_cache is True)
    if not no_cache:
        timestamp = datetime.now().strftime("%Y%m%d%H%M")
        cache_filename = f"{final_app_id}_app_metadata_{timestamp}.json"
        cache_path = Path(cache_filename)
        
        with cache_path.open('w') as f:
            json.dump(data, f, indent=2)
    
    return app_export
