#!/usr/bin/env python3
"""Example of using knack-sleuth as a library with no caching.

This demonstrates how to use knack-sleuth from another codebase,
loading metadata directly from the API without filesystem side effects.
"""

import os
from knack_sleuth import load_app_metadata, KnackSleuth


def main():
    """Demonstrate library usage without caching."""
    
    # For library usage, you typically want to:
    # 1. Load metadata without creating cache files (no_cache=True)
    # 2. Get the data directly into memory for processing
    
    # Option 1: Load from API without caching (library usage)
    # This fetches fresh data every time, no filesystem side effects
    app_id = os.getenv("KNACK_APP_ID")
    
    if not app_id:
        print("Please set KNACK_APP_ID environment variable")
        return
    
    print(f"Loading metadata for app: {app_id}")
    print("Using no_cache=True (no filesystem side effects)\n")
    
    # Load without any caching - clean for library usage
    app_metadata = load_app_metadata(app_id=app_id, no_cache=True)
    
    print(f"✓ Loaded: {app_metadata.application.name}")
    print(f"  Objects: {len(app_metadata.application.objects)}")
    print(f"  Scenes: {len(app_metadata.application.scenes)}\n")
    
    # Use the metadata with KnackSleuth
    sleuth = KnackSleuth(app_metadata)
    
    # Example: Get info about objects
    print("Objects in application:")
    for obj in app_metadata.application.objects[:5]:
        record_count = app_metadata.application.counts.get(obj.key, 0)
        print(f"  - {obj.name} ({obj.key}): {len(obj.fields)} fields, {record_count:,} records")
    
    if len(app_metadata.application.objects) > 5:
        print(f"  ... and {len(app_metadata.application.objects) - 5} more\n")
    
    # Example: Search for usages
    if app_metadata.application.objects:
        first_obj = app_metadata.application.objects[0]
        print(f"Searching for usages of: {first_obj.name}")
        results = sleuth.search_object(first_obj.key)
        object_usages = results.get("object_usages", [])
        print(f"  Found {len(object_usages)} object-level usages")
        
        field_count = sum(1 for key in results.keys() if key.startswith("field_"))
        print(f"  Found {field_count} fields with usages\n")


if __name__ == "__main__":
    main()
