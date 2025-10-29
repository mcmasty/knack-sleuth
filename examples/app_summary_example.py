#!/usr/bin/env python3
"""Example of using the app-summary feature for comprehensive architecture analysis."""

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

    print_separator("APP SUMMARY - COMPREHENSIVE ARCHITECTURE ANALYSIS")

    # Generate the full summary
    summary = sleuth.generate_app_summary()

    # Display key insights
    print_separator("APPLICATION OVERVIEW")
    app = summary["application"]
    metrics = app["complexity_metrics"]
    print(f"Application: {app['name']}")
    print(f"ID: {app['id']}")
    print()
    print("Complexity Metrics:")
    print(f"  Objects: {metrics['total_objects']}")
    print(f"  Fields: {metrics['total_fields']}")
    print(f"  Scenes: {metrics['total_scenes']}")
    print(f"  Views: {metrics['total_views']}")
    print(f"  Records: {metrics['total_records']:,}")
    print(f"  Connection Density: {metrics['connection_density']:.3f}")

    # Domain Model Insights
    print_separator("DOMAIN MODEL CLASSIFICATION")
    domain = summary["domain_model"]
    
    print(f"Core Entities: {len(domain['core_entities'])}")
    for entity in domain["core_entities"][:3]:
        print(f"  - {entity['name']} (centrality: {entity['centrality_score']}, records: {entity['record_count']:,})")
    
    print(f"\nTransactional Entities: {len(domain['transactional_entities'])}")
    for entity in domain["transactional_entities"][:3]:
        print(f"  - {entity['name']} ({entity['record_count']:,} records)")
    
    print(f"\nReference Data: {len(domain['reference_data'])}")
    for entity in domain["reference_data"][:3]:
        used_by_count = len(entity.get("used_by", []))
        print(f"  - {entity['name']} (used by {used_by_count} objects)")

    # Relationship Topology
    print_separator("RELATIONSHIP TOPOLOGY")
    relationships = summary["relationship_map"]
    
    print(f"Total Connections: {relationships['connection_graph']['total_connections']}")
    print("\nHub Objects (high connectivity):")
    for hub in relationships["hub_objects"][:5]:
        print(f"  - {hub['object']}: {hub['total_connections']} connections")
        print(f"    {hub['interpretation']}")
    
    print(f"\nDependency Clusters: {len(relationships['dependency_clusters'])}")
    for cluster in relationships["dependency_clusters"][:2]:
        print(f"  - Cluster: {', '.join(cluster['objects'])}")
        print(f"    Cohesion: {cluster['cohesion']}")

    # Data Patterns
    print_separator("DATA PATTERNS")
    patterns = summary["data_patterns"]
    
    calc = patterns["calculation_complexity"]
    print("\nCalculation Complexity:")
    print(f"  Formula fields: {calc['total_formula_fields']}")
    print(f"  Objects with formulas: {calc['objects_with_formulas']}")
    print(f"  Assessment: {calc['interpretation']}")

    # UI Architecture
    print_separator("UI ARCHITECTURE")
    ui = summary["ui_architecture"]
    
    scenes = ui["scene_patterns"]
    print(f"Scenes: {scenes['total_scenes']} total")
    print(f"  Authenticated: {scenes['authenticated_scenes']}")
    print(f"  Public: {scenes['public_scenes']}")
    
    nav = ui["navigation_depth"]
    print("\nNavigation:")
    print(f"  Max depth: {nav['max_depth']}")
    print(f"  Avg depth: {nav['avg_depth']}")
    print(f"  Complexity: {nav['interpretation']}")
    
    print("\nView Types:")
    for view_type, count in sorted(
        ui["view_patterns"].items(), key=lambda x: x[1], reverse=True
    )[:5]:
        print(f"  {view_type}: {count}")

    # Technical Debt
    print_separator("TECHNICAL DEBT INDICATORS")
    debt = summary["technical_debt_indicators"]
    
    print(f"Orphaned fields: {debt['orphaned_fields']}")
    print(f"Orphaned objects: {debt['orphaned_objects']}")
    print(f"Bottleneck objects: {len(debt['bottleneck_objects'])}")
    print(f"High fan-out objects: {len(debt['high_fan_out_objects'])}")
    print(f"\nAssessment: {debt['interpretation']}")

    # Extensibility
    print_separator("EXTENSIBILITY ASSESSMENT")
    ext = summary["extensibility_assessment"]
    
    print(f"Modularity Score: {ext['modularity_score']}")
    print(f"Architectural Style: {ext['architectural_style']}")
    print(f"Tight Coupling Pairs: {len(ext['tight_coupling_pairs'])}")
    print(f"\nAssessment: {ext['interpretation']}")

    # AI Integration Example
    print_separator("AI INTEGRATION EXAMPLE")
    print("To use this summary with an AI agent:")
    print()
    print("1. Generate the summary:")
    print("   uv run knack-sleuth app-summary --app-id YOUR_APP_ID > app_summary.json")
    print()
    print("2. Ask the AI:")
    print("   'I want to [architectural change]. Here's my app summary:")
    print("   <paste app_summary.json>")
    print("   What should I consider? What are the risks? What's the best approach?'")
    print()
    print("Example questions:")
    print("  - 'Should I split this into multiple apps?'")
    print("  - 'How do I add multi-entity support?'")
    print("  - 'Which objects are safe to refactor?'")
    print("  - 'Where should I add this new feature?'")
    print("  - 'What's the migration path for this change?'")

    # Full JSON output
    print_separator("FULL JSON OUTPUT (sample)")
    print(json.dumps(summary, indent=2)[:1000] + "\n... (truncated)")


if __name__ == "__main__":
    main()
