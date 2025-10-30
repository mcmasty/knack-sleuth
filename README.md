# KnackSleuth

**Detective work for your Knack applications.** 🕵️

KnackSleuth investigates your Knack app metadata to uncover where objects, fields, and connections are used throughout your application. Like a good detective, it traces every lead—from data relationships and view dependencies to hidden references in formulas and filters.

Whether you're refactoring a complex app, auditing data dependencies, or trying to understand the ripple effects of a schema change, KnackSleuth can fast track the investigative work.

## Installation

### Using uvx (Recommended for stand-alone tool usage)

Run KnackSleuth without installation using `uvx`:

```bash
uvx knack-sleuth --help
```

### Add to Project with uv (Recommended for library usage)

Add knack-sleuth as a dependency to your project:

```bash
uv add knack-sleuth
```

Then import and use it in your code as shown in the Library Usage section.

### Install as Global Tool with uv

Install as a tool with uv:

```bash
uv tool install knack-sleuth
knack-sleuth --help
```

### Install with pip

```bash
pip install knack-sleuth
knack-sleuth --help
```



## Library Usage

The foundation of knack-sleuth is a generation of a Pydantic model of the Knack Application Metadata.

ℹ️ **Examples are not included in the installed package** — clone/fork the repo to run them from source.



```zsh
uv run examples/parse_example.py
```

which basically shows off this Pydantic model:

```python
import json
from pathlib import Path

from knack_sleuth import KnackAppMetadata


def main():
    # Load a Knack app export JSON file
    sample_file = Path("tests/data/sample_knack_app_meta.json")
    with sample_file.open() as f:
        data = json.load(f)

    # Parse with Pydantic models - returns validated Application object
    app = KnackAppMetadata(**data).application

```

Similar usage available for `search-object`

```zsh
uv run examples/search_example.py
```

```python
import json
from pathlib import Path

from knack_sleuth import KnackAppMetadata, KnackSleuth


def main():
    # Load sample data
    sample_file = Path("tests/data/sample_knack_app_meta.json")
    with sample_file.open() as f:
        data = json.load(f)

    # Parse metadata and create the search engine
    app_export = KnackAppMetadata(**data)
    sleuth = KnackSleuth(app_export)  # Initialize search engine

    print_separator("KNACK SLEUTH - USAGE SEARCH DEMO")

    # Example 1: Search for an object by key (with cascading to fields)
    object_key = "object_12"  # Example object from test data
    obj = sleuth.get_object_info(object_key)  # Returns usage info for this object

```


You can use knack-sleuth as a library in case you wanted to integrate these models or functions into your own scripts.


Additional examples in the `examples` directory.


## CLI Usage

> **Note**: If you haven't installed knack-sleuth, replace `knack-sleuth` with `uvx knack-sleuth` in the examples below.

### Application ID and Local Files

Most commands can work with metadata in two ways:

1. **From a local JSON file** (if you don't want the default behavior):
   ```bash
   knack-sleuth <command> path/to/knack_export.json
   ```

2. **From the Knack API** (requires Application ID):
   ```bash
   # Via command-line option
   knack-sleuth <command> --app-id YOUR_APP_ID
   
   # Via environment variable
   export KNACK_APP_ID=your_app_id
   knack-sleuth <command>
   
   # Via .env file in your working directory
   # KNACK_APP_ID=your_app_id
   knack-sleuth <command>
   ```

**Caching Behavior:**
- When fetching from the API, metadata is automatically cached to `{APP_ID}_app_metadata_{YYYYMMDDHHMM}.json`
- Cached files are reused for 24 hours to avoid unnecessary API calls
- If no file path is provided and a valid cache exists, it will be used automatically
- Use `--refresh` flag to force fetching fresh data from the API and update the cache
- Cache files are stored in your current working directory


### List All Objects

Get an overview of all objects in your Knack application:

```bash
# Using a local JSON file
knack-sleuth list-objects path/to/knack_export.json

# Fetching from API
knack-sleuth list-objects --app-id YOUR_APP_ID

# Using environment variables
export KNACK_APP_ID=your_app_id
knack-sleuth list-objects

# Sort by row count (largest first)
knack-sleuth list-objects --sort-by-rows path/to/knack_export.json
```

This displays a table showing:
- Object key and name
- Number of rows (records) in each object
- Number of fields in each object
- **Ca** (Afferent coupling): Number of inbound connections - how many other objects depend on this one
- **Ce** (Efferent coupling): Number of outbound connections - how many other objects this one depends on
- Total connections (Ca + Ce)

**Sorting:**
- Default: Alphabetically by object name
- `--sort-by-rows`: Sort by row count (largest first) to quickly identify your biggest tables

**Coupling Insights:**
- High Ca, Low Ce = Hub/core objects that many others depend on (stable, reusable)
- Low Ca, High Ce = Highly coupled objects with many dependencies (potentially fragile)
- High Ca + High Ce = Central, complex objects (review for potential refactoring)

### Search for Object Usages

Search for all places where an object is used in your Knack application.

#### Using a Local JSON File

```bash
# Search by object key
knack-sleuth search-object object_12 path/to/knack_export.json

# Search by object name
knack-sleuth search-object "Object Name" path/to/knack_export.json

# Hide field-level usages (show only object-level)
knack-sleuth search-object object_12 path/to/knack_export.json --no-fields
```

#### Fetching from Knack API

You can fetch metadata directly from the Knack API instead of using a local file:

```bash
# Using command-line options
knack-sleuth search-object object_12 --app-id YOUR_APP_ID

# Using environment variables
export KNACK_APP_ID=your_app_id
knack-sleuth search-object object_12

# Or use a .env file in the project root:
# KNACK_APP_ID=your_app_id
knack-sleuth search-object object_12

# Force refresh cached data (ignore cache)
knack-sleuth search-object object_12 --refresh
```

**Caching Behavior:**
- API responses are automatically cached to `{APP_ID}_app_metadata_{YYYYMMDDHHMM}.json`
- Cached data is reused for 24 hours to avoid unnecessary API calls
- Use `--refresh` to force fetching fresh data from the API
- Cache files are stored in the current working directory

The command will show:
- **Object-level usages**: Where the object appears in connections, views, and other metadata
- **Field-level usages**: Where each field is used (columns, sorts, formulas, etc.) - can be disabled with `--no-fields`
- **Builder Pages to Review**: Direct links to scenes in the Knack builder where this object is used

#### Builder Integration

The search results include clickable links to the Knack builder pages where the object is used:

```bash
# Classic builder URLs (default)
export KNACK_NEXT_GEN_BUILDER=false
knack-sleuth search-object object_12
# → https://builder.knack.com/your-account/portal/pages/scene_7

# Next-Gen builder URLs
export KNACK_NEXT_GEN_BUILDER=true
knack-sleuth search-object object_12
# → https://builder-next.knack.com/your-account/portal/pages/scene_7
```

### Show Object Coupling

View the coupling relationships for a specific object - see which objects depend on it and which objects it depends on:

```bash
# Using object key
knack-sleuth show-coupling object_12 path/to/knack_export.json

# Using object name
knack-sleuth show-coupling "Object Name" path/to/knack_export.json

# From API
knack-sleuth show-coupling object_34 --app-id YOUR_APP_ID
```

This displays:
- **Afferent Coupling (Ca)**: Objects that depend on this object (incoming connections with ← arrows)
- **Efferent Coupling (Ce)**: Objects this object depends on (outgoing connections with → arrows)
- Connection details: field names, keys, and relationship types

Perfect for understanding an object's role in your data model from its perspective.

### Download Metadata

Download and save your Knack application metadata to a local file:

```bash
# Download with default filename ({APP_ID}_metadata.json)
knack-sleuth download-metadata

# Specify custom filename
knack-sleuth download-metadata my_app_backup.json

# Force fresh download (ignore cache)
knack-sleuth download-metadata --refresh
```

This is useful for:
- Creating backups of your app structure
- Working offline with the metadata
- Sharing app structure with others
- Version control / tracking changes over time

The file is saved as formatted JSON (indented) for easy reading and version control.

## Experimental Commands

⚠️ **Alpha/Beta Features** — These commands are actively being developed and refined. Results may vary, and as they are used we hope to improve them. Use at your own risk.

These experimental commands generate comprehensive architectural analysis and impact assessments designed for both human understanding and AI/agent processing. They aim to accelerate development on Knack by providing structured insights into your application's data model, relationships, and dependencies.

### Impact Analysis

Generate a comprehensive analysis of how changing a specific object or field would impact your Knack application:

```bash
# Using object key
knack-sleuth impact-analysis object_12 path/to/knack_export.json --format json

# Using object name
knack-sleuth impact-analysis "Object Name" my_app.json --format markdown

# From API
knack-sleuth impact-analysis field_116 --app-id YOUR_APP_ID --output impact.json
```

**Output Formats:**
- `json`: Structured output for AI/agent processing (default)
- `markdown`: Human-friendly documentation
- `yaml`: Alternative structured format

**What it shows:**
- Direct impacts: connections, views, forms, and formulas affected
- Cascade impacts: dependent fields and scenes
- Risk assessment: breaking change likelihood and impact score
- Affected user workflows

### App Summary

Generate a comprehensive architectural summary of your entire Knack application:

See [docs/AI_USE_CASE_HYPOTHETICAL.md](docs/AI_USE_CASE_HYPOTHETICAL.md) for context on the problem that motivated this experimental feature.

```bash
# Using a local JSON file
knack-sleuth app-summary path/to/knack_export.json

# From API with markdown output
knack-sleuth app-summary --app-id YOUR_APP_ID --format markdown

# Save to file
knack-sleuth app-summary my_app.json --output summary.json
```

**Output Formats:**
- `json`: Structured output for AI/agent processing (default)
- `markdown`: Human-friendly documentation
- `yaml`: Alternative structured format

**What it includes:**
- Domain model classification (user profiles, core entities, transactional/reference/supporting data)
- Relationship topology (connections, clusters, hub objects)
- Data patterns (temporal, calculation complexity)
- UI architecture (scenes, views, navigation depth)
- Access patterns (authentication, roles)
- Technical debt indicators (orphaned resources, bottlenecks)
- Extensibility assessment (modularity, coupling)

**Use Cases:**
- Understanding overall application architecture
- Planning major refactorings or migrations
- AI-assisted architecture discussions and recommendations
- Documentation generation
- Complexity assessment for onboarding new developers

---

## Concepts & Terminology

> ⚠️ **Important Note**: The metrics and classifications in this section represent *technical analysis* of your Knack application's data structure and architecture. They should **not** be confused with business importance or business meaning. An object that is technically "important" (high centrality, high importance score, or a hub) may have little business significance, and conversely, a critical business object may have a simple technical structure. These metrics are designed to help identify technical risks, change complexity, and architectural patterns—not to reflect business priorities or domain significance.

### Connection

A **connection** is a direct relationship between two objects via a field. When you create a "connection" field in Knack (like a lookup, link, or relationship), you create a connection in the graph.

**Examples:**
- A "Client" field on an Order object connects to the Clients object
- A "Category" field on a Product object connects to the Categories object

Connections are directional—an object can have:
- **Outbound connections**: connections this object creates (e.g., Order → Client)
- **Inbound connections**: connections pointing to this object (e.g., Invoice → Order)

### Centrality

**Centrality** (0-1 scale) measures how important an object is in the system based on its connections and usage:

- **Calculation**: Weighted combination of connection density (70%) and view usage (30%)
- **Low (<0.3)**: Peripheral object, used in few places
- **Medium (0.3-0.6)**: Moderately important, used in several areas
- **High (>0.6)**: Core object, critical to app architecture, high change risk

### Importance

**Importance** (0-1 scale) ranks objects among core entities based on overall architectural impact:

- **Calculation**: Weighted combination of data volume (60%) and connectivity (40%)
- **Data volume**: Objects with more records tend to affect more users
- **Connectivity**: Objects with more connections have wider architectural impact
- **Core Entity Selection & Display**: Objects are selected and displayed as core entities in descending order by importance score (top ~20% of objects)
- **Importance determines ranking**: The order in which core entities appear shows their architectural importance from most to least critical

### Hub Object

A **hub object** is an object with many connections (≥3 total), making it a central point in your data model. Objects act as hubs when many other objects reference them or depend on them.

**Characteristics:**
- Highly connected (3+ relationships)
- Often represent core business concepts
- May be a bottleneck if many objects depend on them
- Good candidates for review during refactoring

**Interpretation:**
- **High inbound, low outbound**: A stable hub that others depend on (like a shared lookup table)
- **High outbound, low inbound**: A central aggregator that pulls data from many sources
- **High both ways**: A central, complex object that may benefit from decomposition

### Cluster

A **cluster** is a group of objects that are tightly interconnected with each other—they have more connections within the group than outside it. Clusters represent logical groupings or domains within your application.

**Visual analogy:** Think of connections and clusters like a map:
- **Connection** = a single road between two cities
- **Hub object** = a city with many roads connecting to it (central hub)
- **Cluster** = a region where cities are all interconnected with each other

In your app, a cluster might represent:
- A business process (e.g., "Order Processing": Orders, Invoices, Payments, Customers)
- A domain area (e.g., "User Management": Users, Roles, Permissions)
- A feature set (e.g., "Reporting": Reports, Datasets, Metrics)

Clusters help you understand the modular structure of your application and identify which objects naturally belong together.

---

### Options

- `--app-id TEXT`: Knack application ID (or use `KNACK_APP_ID` env var)
- `--refresh`: Force refresh cached API data (ignore 24-hour cache)
- `--show-fields` / `--no-fields`: Control whether to show field-level usages (default: show)
- `--format TEXT`: Output format (`json`, `markdown`, `yaml`)
- `--output TEXT` / `-o`: Save output to file instead of stdout
- `--help`: Show help message
