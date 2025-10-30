#!/usr/bin/env python3
"""Example of using KnackSleuth to search for object and field usages."""

import json
from pathlib import Path

from knack_sleuth import KnackAppMetadata
from knack_sleuth.sleuth import KnackSleuth


def print_separator(title: str = ""):
    """Print a formatted separator."""
    if title:
        print(f"\n{'=' * 80}")
        print(f" {title}")
        print(f"{'=' * 80}\n")
    else:
        print(f"\n{'-' * 80}\n")


def main():
    # Load sample data
    sample_file = Path("tests/data/sample_knack_app_meta.json")
    with sample_file.open() as f:
        data = json.load(f)

    # Create the search engine
    app_export = KnackAppMetadata(**data)
    sleuth = KnackSleuth(app_export)

    print_separator("KNACK SLeutH - USAGE SEARCH DEMO")

    # Example 1: Search for an object (with cascading to fields)
    object_key = "object_12"  # Example object from test data
    obj = sleuth.get_object_info(object_key)

    print(f"Searching for object: {obj.name} ({object_key})")
    print(f"  Fields in this object: {len(obj.fields)}")

    results = sleuth.search_object(object_key)

    # Show object-level usages
    print_separator(f"Object-level usages for {obj.name}")
    object_usages = results.get("object_usages", [])
    print(f"Found {len(object_usages)} object-level usages:\n")

    for usage in object_usages[:5]:  # Show first 5
        print(f"  [{usage.location_type}]")
        print(f"    {usage.context}")
        print()

    if len(object_usages) > 5:
        print(f"  ... and {len(object_usages) - 5} more\n")

    # Show field-level usages (cascading)
    print_separator("Field-level usages (cascading from object)")
    field_count = sum(
        1 for key in results.keys() if key.startswith("field_")
    )
    print(f"Found usages for {field_count} fields in this object:\n")

    for field_key, usages in list(results.items())[1:4]:  # Show first 3 fields
        if field_key.startswith("field_"):
            obj_info, field_info = sleuth.get_field_info(field_key)
            if field_info:
                print(f"  Field: {field_info.name} ({field_key}) - {len(usages)} usages")
                for usage in usages[:2]:  # Show first 2 usages per field
                    print(f"    • [{usage.location_type}] {usage.context}")
                if len(usages) > 2:
                    print(f"    ... and {len(usages) - 2} more")
                print()

    # Example 2: Search for a specific field
    print_separator("FIELD-SPECIFIC SEARCH")
    field_key = "field_116"  # Connection field from test data
    obj_info, field_info = sleuth.get_field_info(field_key)

    if field_info:
        print(f"Searching for field: {obj_info.name}.{field_info.name} ({field_key})")
        print(f"  Field type: {field_info.type}\n")

        field_usages = sleuth.search_field(field_key)
        print(f"Found {len(field_usages)} usages:\n")

        for usage in field_usages:
            print(f"  [{usage.location_type}]")
            print(f"    {usage.context}")
            if usage.location_type == "view_column" and "column_header" in usage.details:
                print(f"    Column header: {usage.details['column_header']}")
            print()

    # Example 3: Show summary statistics
    print_separator("SUMMARY STATISTICS")
    total_objects = len(sleuth.app.objects)
    total_fields = len(sleuth.field_to_object)
    total_scenes = len(sleuth.app.scenes)

    print(f"Application: {sleuth.app.name}")
    print(f"  Total Objects: {total_objects}")
    print(f"  Total Fields: {total_fields}")
    print(f"  Total Scenes: {total_scenes}")
    print()

    # Count connection fields
    connection_count = 0
    for obj in sleuth.app.objects:
        for field in obj.fields:
            if field.type == "connection":
                connection_count += 1

    print(f"  Connection Fields: {connection_count}")
    print()


if __name__ == "__main__":
    main()
