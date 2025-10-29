#!/usr/bin/env python3
"""Example of using the impact analysis feature for AI/Agent consumption."""

import json
from pathlib import Path

from knack_sleuth import KnackAppExport
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
    app_export = KnackAppExport(**data)
    sleuth = KnackSleuth(app_export)

    print_separator("IMPACT ANALYSIS - AI/AGENT READY OUTPUT")

    # Example 1: Analyze an object
    object_key = "object_12"  # College/School object
    obj = sleuth.get_object_info(object_key)

    print(f"Analyzing object: {obj.name} ({object_key})")
    print(f"  Fields in this object: {len(obj.fields)}\n")

    analysis = sleuth.generate_impact_analysis(object_key)

    # Display high-level summary
    print_separator("SUMMARY")
    print(f"Target: {analysis['target']['name']}")
    print(f"Type: {analysis['target']['type']}")
    print(f"Description: {analysis['target']['description']}")
    print()
    print("Risk Assessment:")
    print(f"  Breaking Change Likelihood: {analysis['risk_assessment']['breaking_change_likelihood']}")
    print(f"  Impact Score: {analysis['risk_assessment']['impact_score']}")
    print(f"  Affected Workflows: {', '.join(analysis['risk_assessment']['affected_user_workflows']) or 'None'}")
    print()
    print("Impact Counts:")
    print(f"  Direct Impacts: {analysis['metadata']['total_direct_impacts']}")
    print(f"  Cascade Impacts: {analysis['metadata']['total_cascade_impacts']}")
    print(f"  Connections: {len(analysis['direct_impacts']['connections'])}")
    print(f"  Views: {len(analysis['direct_impacts']['views'])}")
    print(f"  Forms: {len(analysis['direct_impacts']['forms'])}")
    print(f"  Formulas: {len(analysis['direct_impacts']['formulas'])}")
    print(f"  Affected Fields: {len(analysis['cascade_impacts']['affected_fields'])}")
    print(f"  Affected Scenes: {len(analysis['cascade_impacts']['affected_scenes'])}")

    # Show JSON output (what an AI would receive)
    print_separator("JSON OUTPUT (for AI consumption)")
    print(json.dumps(analysis, indent=2))

    # Example 2: Analyze a specific field
    print_separator("FIELD ANALYSIS EXAMPLE")
    field_key = "field_116"
    obj_info, field_info = sleuth.get_field_info(field_key)

    if field_info:
        print(f"Analyzing field: {obj_info.name}.{field_info.name} ({field_key})")
        print(f"  Field type: {field_info.type}\n")

        field_analysis = sleuth.generate_impact_analysis(field_key)

        print(f"Target: {field_analysis['target']['name']}")
        print(f"Risk Level: {field_analysis['risk_assessment']['breaking_change_likelihood']}")
        print(f"Impact Score: {field_analysis['risk_assessment']['impact_score']}")
        print(f"Direct Impacts: {field_analysis['metadata']['total_direct_impacts']}")

    # Example 3: Show what to send to an AI agent
    print_separator("EXAMPLE: AI AGENT CONTEXT")
    print("When asking an AI to help design a database change, provide:")
    print()
    print("1. The change you want to make:")
    print("   'I want to change the Institution connection field to a text field'")
    print()
    print("2. The impact analysis JSON:")
    print("   <impact_analysis>")
    print(json.dumps(analysis, indent=2)[:500] + "...")
    print("   </impact_analysis>")
    print()
    print("3. Your question:")
    print("   'What are the risks and what steps should I take to migrate this safely?'")
    print()
    print("The AI can then:")
    print("  - Understand exactly what will break")
    print("  - Suggest migration steps in the right order")
    print("  - Warn about user-facing impacts")
    print("  - Help you write migration scripts")
    print("  - Estimate the effort required")


if __name__ == "__main__":
    main()
