# Impact Analysis for AI/Agent Integration

The `impact-analysis` command generates comprehensive, structured output designed specifically for AI agents and automated tools to understand the impact of database schema changes.

## Purpose

When planning changes to a Knack database (objects, fields, connections), you need to understand:
- What will break if you make the change
- Which user workflows are affected
- How much effort is required to migrate safely
- What dependencies exist in the application

This command provides that information in a machine-readable format suitable for feeding into AI agents, documentation generators, or impact assessment tools.

## Usage

### Basic Command

```bash
# Analyze an object
uv run knack-sleuth impact-analysis object_12

# Analyze a field
uv run knack-sleuth impact-analysis field_116

# Search by name instead of key
uv run knack-sleuth impact-analysis "Institution"

# Fetch from API
uv run knack-sleuth impact-analysis object_12 --app-id YOUR_APP_ID

# Output to file in different formats
uv run knack-sleuth impact-analysis object_12 --format json --output impact.json
uv run knack-sleuth impact-analysis object_12 --format markdown --output impact.md
```

### Output Formats

- **JSON** (default): Structured data for programmatic consumption
- **Markdown**: Human-readable report for documentation
- **YAML**: Alternative structured format (requires `pyyaml`)

## Output Structure

### JSON Schema

```json
{
  "target": {
    "key": "object_12",
    "type": "object",
    "name": "College/School",
    "description": "5 fields"
  },
  "direct_impacts": {
    "connections": [
      {
        "type": "connection_outbound",
        "description": "Institution (object_1) connects to this object via College/School (field_116)",
        "source_object": "object_1",
        "connection_field": "field_116"
      }
    ],
    "views": [
      {
        "view_key": "view_23",
        "view_name": "Institution Details",
        "view_type": "details",
        "scene_key": "scene_15",
        "scene_name": "Institution"
      }
    ],
    "scenes": [
      {
        "scene_key": "scene_15",
        "scene_name": "Institution",
        "scene_slug": "institution"
      }
    ],
    "formulas": [
      {
        "field_key": "field_120",
        "field_name": "Full Name",
        "object_key": "object_1",
        "equation": "{field_116} - {field_118}"
      }
    ],
    "forms": []
  },
  "cascade_impacts": {
    "affected_fields": [
      {
        "field_key": "field_117",
        "field_name": "Name",
        "field_type": "short_text",
        "usage_count": 12,
        "usages": [...]
      }
    ],
    "affected_objects": [],
    "affected_scenes": ["scene_15", "scene_18"],
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

## AI Agent Integration

### Use Case 1: Impact Assessment

When you want to change a field type or delete an object, ask an AI:

```
I want to change the "Institution" connection field (field_116) from a connection to a text field.

<impact_analysis>
{
  "target": {...},
  "direct_impacts": {...},
  "risk_assessment": {...}
}
</impact_analysis>

What are the risks and what steps should I take to migrate this safely?
```

The AI can:
- Identify exactly what will break
- Suggest migration order (e.g., update formulas first)
- Warn about user-facing impacts
- Estimate effort based on impact count

### Use Case 2: Migration Planning

```
I need to split the "Full Name" field into "First Name" and "Last Name".

Current state:
<impact_analysis>
{...full name field analysis...}
</impact_analysis>

Create a step-by-step migration plan.
```

The AI can generate:
- Field creation steps
- Data migration scripts
- Formula updates
- View reconfiguration steps
- Testing checklist

### Use Case 3: Refactoring Decisions

```
Should I merge these two objects or keep them separate?

Object A:
<impact_analysis>
{...object A analysis...}
</impact_analysis>

Object B:
<impact_analysis>
{...object B analysis...}
</impact_analysis>

Analyze the trade-offs and recommend an approach.
```

## Risk Assessment Levels

The tool automatically calculates a risk level:

- **none**: No impacts found (safe to delete/modify)
- **low**: 1-5 impacts (minimal risk, easy to fix)
- **medium**: 6-15 impacts (moderate risk, requires planning)
- **high**: 16+ impacts (high risk, extensive testing needed)

## Impact Score Calculation

Impact Score = Direct Impacts + Cascade Impacts

Where:
- **Direct Impacts**: Connections + Views + Forms + Formulas
- **Cascade Impacts**: Number of affected fields (for object changes)

Higher scores indicate more complex changes that require careful planning.

## Workflow Detection

The tool identifies affected user workflows:

- **User data entry forms**: Users who enter data will be affected
- **Data display views**: Users who view data will see changes
- **Related data relationships**: Connected data may become inconsistent
- **Calculated fields and formulas**: Computed values may break

## Examples

### Example 1: Low-Impact Field Change

```bash
$ uv run knack-sleuth impact-analysis field_200 --format markdown

# Impact Analysis: Status

**Type:** field  
**Key:** `field_200`  
**Description:** multiple_choice field  

## Risk Assessment

- **Breaking Change Likelihood:** low
- **Impact Score:** 2
- **Affected Workflows:** Data display views

## Direct Impacts

### Views (2)
- **Status Dashboard** (`view_45`) - table in scene Status Overview

### Forms (0)
*No form impacts*
```

### Example 2: High-Impact Object Change

```bash
$ uv run knack-sleuth impact-analysis object_1 --format json > impact.json

# Then use in AI session:
# "I need to understand the full impact of deleting this object"
# <attach impact.json>
```

## Integration with Other Tools

### CI/CD Pipeline

```bash
# Generate impact report before deployment
uv run knack-sleuth impact-analysis object_12 \
  --app-id $APP_ID \
  --format markdown \
  --output docs/impact_reports/object_12_$(date +%Y%m%d).md

# Fail deployment if impact score exceeds threshold
IMPACT_SCORE=$(uv run knack-sleuth impact-analysis object_12 --format json | jq '.risk_assessment.impact_score')
if [ "$IMPACT_SCORE" -gt 20 ]; then
  echo "Impact score too high: $IMPACT_SCORE"
  exit 1
fi
```

### Documentation Generation

```bash
# Generate impact reports for all objects
for obj in object_1 object_2 object_3; do
  uv run knack-sleuth impact-analysis $obj \
    --format markdown \
    --output docs/impacts/$obj.md
done
```

### AI Agent Workflow

```python
import json
import subprocess

# Generate impact analysis
result = subprocess.run(
    ["uv", "run", "knack-sleuth", "impact-analysis", "object_12", "--format", "json"],
    capture_output=True,
    text=True
)

impact = json.loads(result.stdout)

# Send to AI agent
prompt = f"""
I want to modify {impact['target']['name']}.

Impact Analysis:
{json.dumps(impact, indent=2)}

Risk Level: {impact['risk_assessment']['breaking_change_likelihood']}
Impact Score: {impact['risk_assessment']['impact_score']}

Please provide:
1. List of breaking changes
2. Migration plan with steps
3. Estimated effort in hours
4. Testing recommendations
"""

# ai_agent.query(prompt)
```

## Best Practices

1. **Always run before major changes**: Generate an impact report before modifying critical objects/fields
2. **Save reports for documentation**: Keep a history of impact analyses for audit trails
3. **Use JSON for automation**: Parse JSON output in scripts and CI/CD pipelines
4. **Use Markdown for reviews**: Share markdown reports in PRs for team review
5. **Include in AI context**: Always provide impact analysis when asking AI for migration help

## Future Enhancements

Potential additions to the impact analysis:

- Dependency chain visualization (A → B → C)
- Data migration complexity estimation
- Rollback plan generation
- Comparison mode (before/after analysis)
- Integration with Knack API for real-time analysis
- Historical impact tracking over time
