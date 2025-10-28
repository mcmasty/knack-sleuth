# KnackSleuth
Find usages of data objects in the knack app metadata

## Usage

### List All Objects

Get an overview of all objects in your Knack application:

```bash
# Using a local JSON file
uv run knack-sleuth list-objects path/to/knack_export.json

# Fetching from API
uv run knack-sleuth list-objects --app-id YOUR_APP_ID --api-key YOUR_KEY

# Using environment variables
uv run knack-sleuth list-objects
```

This displays a table showing:
- Object key and name
- Number of rows (records) in each object
- Number of fields in each object
- Number of connections (inbound + outbound)

### Search for Object Usages

Search for all places where an object is used in your Knack application.

#### Using a Local JSON File

```bash
# Search by object key
uv run knack-sleuth search-object object_12 path/to/knack_export.json

# Search by object name
uv run knack-sleuth search-object "College/School" path/to/knack_export.json

# Hide field-level usages (show only object-level)
uv run knack-sleuth search-object object_12 path/to/knack_export.json --no-fields
```

#### Fetching from Knack API

You can fetch metadata directly from the Knack API instead of using a local file:

```bash
# Using command-line options
uv run knack-sleuth search-object object_12 --app-id YOUR_APP_ID --api-key YOUR_API_KEY

# Using environment variables
export KNACK_APP_ID=your_app_id
export KNACK_API_KEY=your_api_key
uv run knack-sleuth search-object object_12

# Or use a .env file in the project root:
# KNACK_APP_ID=your_app_id
# KNACK_API_KEY=your_api_key
uv run knack-sleuth search-object object_12

# Force refresh cached data (ignore cache)
uv run knack-sleuth search-object object_12 --refresh
```

**Caching Behavior:**
- API responses are automatically cached to `{APP_ID}_app_metadata_{YYYYMMDDHHMM}.json`
- Cached data is reused for 24 hours to avoid unnecessary API calls
- Use `--refresh` to force fetching fresh data from the API
- Cache files are stored in the current working directory

The command will show:
- **Object-level usages**: Where the object appears in connections, views, and other metadata
- **Field-level usages**: Where each field is used (columns, sorts, formulas, etc.) - can be disabled with `--no-fields`

### Options

- `--app-id TEXT`: Knack application ID (or use `KNACK_APP_ID` env var)
- `--api-key TEXT`: Knack API key (or use `KNACK_API_KEY` env var)
- `--refresh`: Force refresh cached API data (ignore 24-hour cache)
- `--show-fields` / `--no-fields`: Control whether to show field-level usages (default: show)
- `--help`: Show help message
