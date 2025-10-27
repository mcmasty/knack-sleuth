#!/usr/bin/env python3
"""Example of using KnackSlueth models to parse Knack metadata."""

import json
from pathlib import Path

from knack_slueth import KnackAppExport


def main():
    # Load a Knack app export JSON file
    sample_file = Path("tests/data/sample_knack_app_meta.json")
    with sample_file.open() as f:
        data = json.load(f)

    # Parse with Pydantic models
    app = KnackAppExport(**data).application

    print(f"Application: {app.name}")
    print(f"Total Objects: {len(app.objects)}")
    print(f"Total Scenes: {len(app.scenes)}")
    print()

    # Example: Find all connection fields
    print("Connection Fields:")
    for obj in app.objects:
        for field in obj.fields:
            if field.type == "connection" and field.relationship:
                print(
                    f"  - {obj.name}.{field.name} ({field.key}) -> {field.relationship.object}"
                )
    print()

    # Example: Find fields used in views
    print("Fields used in table views:")
    for scene in app.scenes:
        for view in scene.views:
            if view.type == "table" and view.source:
                print(f"  Scene: {scene.name} / View: {view.name}")
                print(f"    Data Source: {view.source.object}")
                for col in view.columns:
                    if col.field:
                        print(f"      Field: {col.field.get('key', 'N/A')}")
                print()


if __name__ == "__main__":
    main()
