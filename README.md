# KnackSleuth

**Detective work for your Knack applications.** 🕵️

KnackSleuth investigates your Knack app metadata to uncover where objects, fields, and connections are used throughout your application. Like a good detective, it traces every lead—from data relationships and view dependencies to hidden references in formulas and filters.

Whether you're refactoring a complex app, auditing data dependencies, or trying to understand the ripple effects of a schema change, KnackSleuth does the investigative work so you don't have to.

## Installation

### Using uvx (Recommended)

Run KnackSleuth without installation using `uvx`:

```bash
uvx knack-sleuth --help
```

### Install with uv

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

## Usage

> **Note**: If you haven't installed knack-sleuth, replace `knack-sleuth` with `uvx knack-sleuth` in the examples below.

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

### List All Objects

Get an overview of all objects in your Knack application:

```bash
# Using a local JSON file
knack-sleuth list-objects path/to/knack_export.json

# Fetching from API
knack-sleuth list-objects --app-id YOUR_APP_ID

# Using environment variables
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


### Options

- `--app-id TEXT`: Knack application ID (or use `KNACK_APP_ID` env var)
- `--refresh`: Force refresh cached API data (ignore 24-hour cache)
- `--show-fields` / `--no-fields`: Control whether to show field-level usages (default: show)
- `--help`: Show help message
