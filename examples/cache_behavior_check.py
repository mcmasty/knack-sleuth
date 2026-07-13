#!/usr/bin/env python3
"""Manual check that the no_cache parameter and cache directory work correctly.

Not a pytest test — run it directly with KNACK_APP_ID set to exercise the
real API and the cache directory:

    KNACK_APP_ID=your_app_id uv run python examples/cache_behavior_check.py
"""

import os
from pathlib import Path

from knack_sleuth import load_app_metadata
from knack_sleuth.core import get_cache_dir


def check_no_cache():
    """Verify that no_cache=True doesn't create cache files."""

    app_id = os.getenv("KNACK_APP_ID")
    if not app_id:
        print("⚠️  KNACK_APP_ID not set - skipping API check")
        print("   To run against the API, set KNACK_APP_ID")
        return

    cache_dir = get_cache_dir()
    print(f"Cache directory: {cache_dir}")
    print(f"App ID: {app_id}\n")

    def cache_files():
        return sorted(cache_dir.glob(f"{app_id}_app_metadata_*.json"))

    existing = cache_files()
    if existing:
        print(f"Found {len(existing)} existing cache file(s)")
        for cache_file in existing:
            print(f"  - {cache_file.name}")
        print()

    # Check 1: no_cache=True must not create files
    print("Check 1: Loading with no_cache=True...")
    metadata = load_app_metadata(app_id=app_id, no_cache=True)
    print(f"✓ Loaded: {metadata.application.name}")
    if len(cache_files()) == len(existing):
        print("✓ No new cache files created (as expected)")
    else:
        print("✗ FAIL: new cache file(s) created!")
        return

    print()

    # Check 2: default behavior may read or write cache
    print("Check 2: Loading with default caching...")
    metadata = load_app_metadata(app_id=app_id)
    print(f"✓ Loaded: {metadata.application.name}")
    print("✓ Using existing cache or created cache (normal behavior)")

    print("\nAll checks passed! ✓")


def check_file_load():
    """Verify loading from a file."""
    print("Check 3: Loading from file...")

    sample_file = Path("tests/data/sample_knack_app_meta.json")
    if not sample_file.exists():
        print("⚠️  Sample file not found - skipping file load check")
        return

    metadata = load_app_metadata(file_path=sample_file)
    print(f"✓ Loaded: {metadata.application.name}")
    print(f"  Objects: {len(metadata.application.objects)}")
    print(f"  Scenes: {len(metadata.application.scenes)}")


if __name__ == "__main__":
    print("=" * 60)
    print("Cache behavior check")
    print("=" * 60)
    print()

    check_file_load()
    print()
    check_no_cache()
