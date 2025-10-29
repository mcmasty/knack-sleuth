# Application Summary - Universal Architecture Analysis

The `app-summary` command generates a comprehensive architectural analysis of your entire Knack application, providing universal context for ANY architectural discussion or change.

## Purpose

Unlike specific impact analysis tools, `app-summary` gives you a complete structural overview that can be used to reason about:
- **Any** architectural change
- **Any** refactoring decision  
- **Any** feature addition
- **Any** splitting/merging decision
- **Any** performance optimization

It's the foundation for informed architectural conversations with AI agents, team members, or stakeholders.

## What It Analyzes

### 1. Application Metadata & Complexity Metrics
- Total objects, fields, scenes, views, records
- Connection density (how interconnected your data is)
- Overall complexity assessment

### 2. Domain Model Classification
Automatically classifies every object as:
- **Core Entities**: Central business concepts (users, primary data)
- **Transactional Entities**: Time-based records (orders, logs, events)
- **Reference Data**: Lookup tables (statuses, types, categories)
- **Supporting Entities**: Auxiliary data

Each with:
- Centrality score (how important/connected)
- Record counts
- Field type distribution

### 3. Relationship Topology
- **Connection Graph**: Complete map of how objects connect
- **Hub Objects**: Highly connected objects (refactoring risks)
- **Dependency Clusters**: Natural groupings of related objects
- **Coupling Analysis**: Which objects are tightly coupled

### 4. Data Patterns
- **Scoping Detection**: User-level, date-level, entity-level
- **Temporal Patterns**: Stateful entities, lifecycle tracking
- **Calculation Complexity**: Formula chains and dependencies

### 5. UI Architecture
- Scene patterns (authenticated vs public)
- View type distribution (forms, tables, details, etc.)
- Navigation depth and complexity
- User workflow indicators

### 6. Access Patterns
- Authentication model
- Role-based access control usage
- Data visibility patterns

### 7. Technical Debt Indicators
- Orphaned fields/objects (unused resources)
- Bottleneck objects (many inbound connections)
- High fan-out objects (many outbound connections)
- Complexity hotspots

### 8. Extensibility Assessment
- Modularity score (how well-clustered your architecture is)
- Architectural style (hub-and-spoke, modular, mixed)
- Tight coupling identification
- Change readiness indicators

## Usage

### Basic Command

```bash
# From local file
uv run knack-sleuth app-summary path/to/metadata.json

# From Knack API
uv run knack-sleuth app-summary --app-id YOUR_APP_ID

# Output to file
uv run knack-sleuth app-summary --app-id YOUR_APP_ID --output summary.json

# Different formats
uv run knack-sleuth app-summary --app-id YOUR_APP_ID --format markdown
uv run knack-sleuth app-summary --app-id YOUR_APP_ID --format yaml
```

### Output Formats

- **JSON** (default): Complete structured data for programmatic use
- **Markdown**: Human-readable summary for documentation
- **YAML**: Alternative structured format

## Output Structure

```json
{
  "application": {
    "name": "Your App Name",
    "id": "app_id",
    "complexity_metrics": {
      "total_objects": 25,
      "total_fields": 342,
      "total_scenes": 67,
      "total_views": 156,
      "total_records": 15420,
      "connection_density": 0.34
    }
  },
  "domain_model": {
    "core_entities": [...],
    "transactional_entities": [...],
    "reference_data": [...],
    "supporting_entities": [...]
  },
  "relationship_map": {
    "connection_graph": {...},
    "hub_objects": [...],
    "dependency_clusters": [...]
  },
  "data_patterns": {
    "temporal_objects": [...],
    "calculation_complexity": {...}
  },
  "ui_architecture": {
    "scene_patterns": {...},
    "view_patterns": {...},
    "navigation_depth": {...}
  },
  "access_patterns": {...},
  "technical_debt_indicators": {...},
  "extensibility_assessment": {...}
}
```

## Use Cases with AI Agents

### Universal Architecture Questions

```
Generate summary:
$ uv run knack-sleuth app-summary --app-id YOUR_APP_ID > app_summary.json

Ask AI with context:
"Here's my Knack app architecture summary:
<paste app_summary.json>

I want to [your question]. What should I consider?"
```

### Example Question 1: Multi-Entity Conversion

```
"I want to convert this single-entity app to support multiple legal entities.

<app_summary.json>

Questions:
1. Which objects need entity-level scoping?
2. What's the migration complexity?
3. Which objects can be shared vs entity-specific?
4. What's the safest implementation path?"
```

**AI can see:**
- Hub objects that will be affected
- Natural clusters that should stay together
- Coupling that needs careful handling

### Example Question 2: Should I Split This App?

```
"Should I split this into separate apps for different departments?

<app_summary.json>

What's the best approach and what are the tradeoffs?"
```

**AI can see:**
- Dependency clusters (natural split boundaries)
- Hub objects (splitting risks)
- Cross-cluster connections (coordination needed)
- Modularity score (feasibility)

### Example Question 3: Where to Add New Feature?

```
"I need to add a new workflow for [feature]. 

<app_summary.json>

Where should I add it in the architecture?
Which objects should it connect to?"
```

**AI can see:**
- Existing domain model structure
- Hub objects to potentially leverage
- Architectural style to match
- Coupling implications

### Example Question 4: Performance Optimization

```
"The app is getting slow. Where should I optimize?

<app_summary.json>

What are the likely bottlenecks and how do I address them?"
```

**AI can see:**
- High-connection objects (query bottlenecks)
- Formula complexity (calculation overhead)
- View patterns (rendering bottlenecks)
- Record counts (data volume issues)

### Example Question 5: Technical Debt Cleanup

```
"I need to clean up technical debt. What should I prioritize?

<app_summary.json>

Give me a prioritized list with effort estimates."
```

**AI can see:**
- Orphaned resources (safe to remove)
- Bottleneck objects (high-impact refactoring)
- Tight coupling (requires coordinated changes)
- Modularity score (architectural improvements)

## Interpreting the Output

### Complexity Metrics

- **Connection Density (0-1)**: 
  - < 0.2: Loosely connected
  - 0.2-0.5: Moderately connected
  - \> 0.5: Highly interconnected

### Centrality Score (0-1)

- < 0.3: Peripheral object
- 0.3-0.6: Moderately important
- \> 0.6: Core hub object (high change risk)

### Modularity Score (0-1)

- < 0.4: Low modularity (changes have wide impact)
- 0.4-0.7: Moderate modularity (some natural boundaries)
- \> 0.7: High modularity (easy to extend)

### Architectural Styles

- **hub_and_spoke**: Centralized around key objects
  - Pro: Simple to understand
  - Con: Changes to hub affect everything
  
- **modular**: Clear separation into clusters
  - Pro: Easy to extend independently
  - Con: May need coordination between modules
  
- **mixed**: Combination of patterns
  - Pro: Flexible
  - Con: May indicate organic growth without planning

### Hub Object Interpretations

- **Central dependency**: Many depend on this - breaking change risk HIGH
- **Aggregator**: Pulls from many sources - refactoring complexity HIGH
- **Core hub**: Bidirectional dependencies - coordination required
- **Moderately connected**: Standard coupling - manageable changes

### Cohesion Levels (Clusters)

- **high (>0.7)**: Strong module boundary - good split candidate
- **medium (0.4-0.7)**: Related but not inseparable
- **low (<0.4)**: Weak relationship - may not be natural grouping

## Integration Workflows

### 1. Architecture Review Workflow

```bash
# Monthly architecture review
uv run knack-sleuth app-summary --app-id $APP_ID \
  --format markdown \
  --output docs/architecture/summary_$(date +%Y%m).md

# Compare with previous month to track evolution
```

### 2. Pre-Refactoring Workflow

```bash
# Before major change
uv run knack-sleuth app-summary --app-id $APP_ID > pre_change_summary.json

# Make changes...

# After change
uv run knack-sleuth app-summary --app-id $APP_ID > post_change_summary.json

# Compare to see impact
diff pre_change_summary.json post_change_summary.json
```

### 3. AI Planning Workflow

```bash
# Generate summary
uv run knack-sleuth app-summary --app-id $APP_ID > summary.json

# Use in AI session
# Paste summary.json
# Ask architectural questions
# AI provides context-aware recommendations

# Document decision
echo "Decision: [chosen approach]" >> docs/decisions/$(date +%Y%m%d)_decision.md
echo "Based on:" >> docs/decisions/$(date +%Y%m%d)_decision.md
cat summary.json >> docs/decisions/$(date +%Y%m%d)_decision.md
```

### 4. Onboarding Workflow

```bash
# Generate markdown summary for new team members
uv run knack-sleuth app-summary --app-id $APP_ID \
  --format markdown \
  --output docs/ARCHITECTURE.md

# New team member reads ARCHITECTURE.md to understand app structure
```

## Best Practices

1. **Generate Before Major Changes**: Always run app-summary before architectural decisions
2. **Version Control Summaries**: Track architecture evolution over time
3. **Share with AI**: Include full JSON when asking AI for architectural advice
4. **Use Markdown for Teams**: Share markdown summaries in documentation and PRs
5. **Monitor Metrics**: Track complexity metrics and modularity score over time
6. **Identify Risks Early**: Watch centrality scores and bottleneck objects
7. **Plan Modularly**: Use clusters to guide feature placement

## Comparing with Other Commands

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `app-summary` | Complete architecture overview | Major decisions, AI planning, documentation |
| `impact-analysis` | Specific change impact | Before modifying a single object/field |
| `search-object` | Find object usage | Debugging, understanding specific object |
| `list-objects` | Object inventory | Quick reference, finding objects |
| `show-coupling` | Object relationships | Understanding dependencies |

## Future Enhancements

Potential additions:

- Historical trend tracking
- Architecture diff between versions
- Automated recommendation engine
- Visual architecture diagrams
- Complexity scoring and thresholds
- Integration with version control
- Performance prediction models

## Examples

### Simple App Analysis

```bash
$ uv run knack-sleuth app-summary simple_app.json --format markdown

# Output shows:
- 5 core entities
- Low modularity (0.3) - hub-and-spoke architecture
- One central "Customers" hub
- No multi-tenancy
- Recommendation: Good for small teams, consider modularizing if growing
```

### Complex App Analysis

```bash
$ uv run knack-sleuth app-summary complex_app.json --format json > summary.json

# Output shows:
- 45 objects, high connection density (0.6)
- 3 clear dependency clusters
- Moderately modular (0.55)
- Multiple hub objects
- Some technical debt (orphaned fields)
# AI can help plan targeted refactoring to improve modularity
```

## Summary

`app-summary` is your universal architectural context tool. It doesn't tell you WHAT to do, but provides all the information needed to make informed decisions about ANY architectural change. Perfect for AI-assisted planning, team discussions, and architectural evolution tracking.
