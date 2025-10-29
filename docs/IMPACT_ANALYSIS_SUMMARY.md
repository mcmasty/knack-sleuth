# Impact Analysis Feature - Implementation Summary

## What Was Added

A new `impact-analysis` command that generates AI-friendly output to help assess the impact of database schema changes in Knack applications.

## Key Features

### 1. Structured Impact Report
The command outputs a comprehensive JSON structure containing:

- **Target Information**: What you're analyzing (object or field)
- **Direct Impacts**: Immediate effects on connections, views, forms, formulas
- **Cascade Impacts**: Secondary effects on related fields, objects, and scenes
- **Risk Assessment**: Automated risk level and impact score
- **Workflow Detection**: Which user workflows are affected

### 2. Multiple Output Formats

- **JSON**: Machine-readable for AI agents and automation
- **Markdown**: Human-readable reports for documentation
- **YAML**: Alternative structured format (optional)

### 3. Intelligent Risk Scoring

Automatically calculates:
- **Impact Score**: Total number of affected components
- **Breaking Change Likelihood**: none/low/medium/high
- **Affected Workflows**: User-facing impacts

### 4. Flexible Target Resolution

Supports searching by:
- Object key (`object_12`)
- Field key (`field_116`)
- Human-readable name (`"Institution"`)

## Use Cases

### For AI Agents

Provide the JSON output as context when asking:
- "What will break if I change this field?"
- "How do I safely migrate this data?"
- "What's the impact of deleting this object?"

### For Documentation

Generate markdown reports for:
- Change request documentation
- Impact assessment reviews
- Migration planning documents
- Audit trails

### For Automation

Integrate into CI/CD pipelines:
- Fail deployments if impact score exceeds threshold
- Auto-generate impact reports for code reviews
- Track schema evolution over time

## Example Output

```json
{
  "target": {
    "key": "object_12",
    "type": "object",
    "name": "College/School",
    "description": "5 fields"
  },
  "direct_impacts": {
    "connections": [...],
    "views": [...],
    "scenes": [...],
    "formulas": [...],
    "forms": [...]
  },
  "cascade_impacts": {
    "affected_fields": [...],
    "affected_objects": [],
    "affected_scenes": [...],
    "dependency_chains": []
  },
  "risk_assessment": {
    "breaking_change_likelihood": "high",
    "impact_score": 25,
    "affected_user_workflows": [
      "User data entry forms",
      "Data display views",
      "Related data relationships"
    ]
  },
  "metadata": {
    "total_direct_impacts": 15,
    "total_cascade_impacts": 10,
    "analysis_timestamp": null
  }
}
```

## Quick Start

```bash
# Basic usage
uv run knack-sleuth impact-analysis object_12

# Output to file
uv run knack-sleuth impact-analysis field_116 --format json --output impact.json

# Use in AI session
uv run knack-sleuth impact-analysis "Institution" > analysis.json
# Then paste analysis.json contents into your AI chat
```

## Files Modified/Created

### Modified
- `src/knack_sleuth/sleuth.py`: Added `generate_impact_analysis()` method
- `src/knack_sleuth/cli.py`: Added `impact-analysis` CLI command

### Created
- `examples/impact_analysis_example.py`: Demonstration script
- `docs/IMPACT_ANALYSIS.md`: Comprehensive documentation
- `docs/IMPACT_ANALYSIS_SUMMARY.md`: This summary

## Benefits

1. **Better Decision Making**: Understand full impact before making changes
2. **Reduced Risk**: Identify breaking changes before they happen
3. **AI Integration**: Structured data perfect for AI agent consumption
4. **Automation Ready**: Easy to integrate into existing workflows
5. **Documentation**: Auto-generate impact reports for team review

## Next Steps

To use this feature:

1. Run the command on your Knack app metadata
2. Review the risk assessment
3. Use JSON output as context for AI agents when planning migrations
4. Save reports for documentation and audit trails

## Example AI Workflow

```bash
# Generate impact analysis
uv run knack-sleuth impact-analysis object_12 \
  --app-id YOUR_APP_ID \
  --format json > impact.json

# In AI chat:
# "I want to change this object structure:"
# <paste impact.json contents>
# "What's the safest migration path?"
```

The AI can now:
- See exactly what will break
- Suggest migration steps in correct order
- Estimate effort based on impact score
- Warn about user-facing changes
- Help write migration scripts
