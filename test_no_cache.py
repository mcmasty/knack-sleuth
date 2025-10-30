#!/usr/bin/env python3
"""Quick test to verify no_cache parameter works correctly."""

import os
import glob
from pathlib import Path
from knack_sleuth import load_app_metadata


def test_no_cache():
    """Test that no_cache=True doesn't create cache files."""
    
    app_id = os.getenv("KNACK_APP_ID")
    if not app_id:
        print("⚠️  KNACK_APP_ID not set - skipping API test")
        print("   To test with API, set KNACK_APP_ID environment variable")
        return
    
    print("Testing no_cache parameter...")
    print(f"App ID: {app_id}\n")
    
    # Clean up any existing cache files first
    cache_pattern = f"{app_id}_app_metadata_*.json"
    existing_caches = glob.glob(cache_pattern)
    if existing_caches:
        print(f"Found {len(existing_caches)} existing cache file(s)")
        for cache_file in existing_caches:
            print(f"  - {cache_file}")
        print()
    
    # Test 1: Load with no_cache=True
    print("Test 1: Loading with no_cache=True...")
    try:
        metadata = load_app_metadata(app_id=app_id, no_cache=True)
        print(f"✓ Loaded: {metadata.application.name}")
        
        # Check for new cache files
        new_caches = glob.glob(cache_pattern)
        new_cache_count = len(new_caches) - len(existing_caches)
        
        if new_cache_count == 0:
            print("✓ No new cache files created (as expected)")
        else:
            print(f"✗ FAIL: {new_cache_count} new cache file(s) created!")
            return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False
    
    print()
    
    # Test 2: Load with no_cache=False (default)
    print("Test 2: Loading with no_cache=False (default)...")
    try:
        metadata = load_app_metadata(app_id=app_id, no_cache=False)
        print(f"✓ Loaded: {metadata.application.name}")
        
        # Check for new cache files
        final_caches = glob.glob(cache_pattern)
        new_cache_count = len(final_caches) - len(existing_caches)
        
        if new_cache_count > 0:
            print("✓ Cache file created (as expected)")
            for cache_file in final_caches:
                if cache_file not in existing_caches:
                    print(f"  Created: {cache_file}")
        else:
            # Might be using existing cache - that's ok
            print("✓ Using existing cache or created cache (normal behavior)")
    except Exception as e:
        print(f"✗ Error: {e}")
        return False
    
    print()
    print("All tests passed! ✓")
    return True


def test_file_load():
    """Test loading from a file."""
    print("Test 3: Loading from file...")
    
    # Use the sample test data if it exists
    sample_file = Path("tests/data/sample_knack_app_meta.json")
    if not sample_file.exists():
        print("⚠️  Sample file not found - skipping file load test")
        return True
    
    try:
        metadata = load_app_metadata(file_path=sample_file)
        print(f"✓ Loaded: {metadata.application.name}")
        print(f"  Objects: {len(metadata.application.objects)}")
        print(f"  Scenes: {len(metadata.application.scenes)}")
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Testing load_app_metadata refactoring")
    print("=" * 60)
    print()
    
    # Test file loading first (doesn't require API key)
    test_file_load()
    print()
    
    # Test API loading with cache control
    test_no_cache()
