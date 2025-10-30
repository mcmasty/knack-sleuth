# Library Usage

While `knack-sleuth` is primarily a CLI tool, it can also be used as a library in your Python projects.

## Installation

```bash
uv add knack-sleuth
# or
pip install knack-sleuth
```

## Loading Metadata

The `load_app_metadata()` function provides flexible ways to load Knack application metadata:

```python
from knack_sleuth import load_app_metadata, KnackSleuth

# Option 1: Load from a local JSON file
metadata = load_app_metadata(file_path=Path("my_app.json"))

# Option 2: Load from API with automatic caching (default behavior)
metadata = load_app_metadata(app_id="abc123")

# Option 3: Load from API without any caching (recommended for library usage)
metadata = load_app_metadata(app_id="abc123", no_cache=True)

# Option 4: Force refresh from API (ignore existing cache)
metadata = load_app_metadata(app_id="abc123", refresh=True)
```

### The `no_cache` Parameter

The `no_cache` parameter is specifically designed for library usage:

- **`no_cache=False`** (default): Normal caching behavior
  - Reads from cache if available and less than 24 hours old
  - Writes new cache files when fetching from API
  - Creates files like `{APP_ID}_app_metadata_{timestamp}.json` in current directory

- **`no_cache=True`**: No filesystem side effects
  - Always fetches fresh data from API
  - Does not read from cache
  - Does not create cache files
  - **Recommended for library usage** where you don't want filesystem side effects

### When to Use `no_cache=True`

Use `no_cache=True` when:

1. **Library/Script Usage**: Your code is used as a library by other applications
2. **No Filesystem Access**: You want to avoid creating cache files in the working directory
3. **Always Fresh Data**: You always want the latest data from the API
4. **Controlled Environments**: Running in containers, serverless functions, or CI/CD where you don't want cache files

### Example: Library Usage

```python
import os
from knack_sleuth import load_app_metadata, KnackSleuth

def analyze_app(app_id: str):
    """Analyze a Knack app without creating cache files."""
    
    # Load metadata without caching - clean for library usage
    metadata = load_app_metadata(app_id=app_id, no_cache=True)
    
    # Create search engine
    sleuth = KnackSleuth(metadata)
    
    # Analyze objects
    for obj in metadata.application.objects:
        print(f"Analyzing {obj.name}...")
        results = sleuth.search_object(obj.key)
        # Process results...
    
    return metadata

# Use it
app_id = os.getenv("KNACK_APP_ID")
analyze_app(app_id)
```

## Using the Pydantic Models

The metadata is returned as a fully-typed Pydantic model:

```python
from knack_sleuth import load_app_metadata

metadata = load_app_metadata(app_id="abc123", no_cache=True)

# Access application info
app = metadata.application
print(f"App: {app.name}")
print(f"ID: {app.id}")

# Iterate over objects
for obj in app.objects:
    print(f"  - {obj.name} ({obj.key})")
    print(f"    Fields: {len(obj.fields)}")
    
    # Access connections
    if obj.connections:
        print(f"    Inbound connections: {len(obj.connections.inbound)}")
        print(f"    Outbound connections: {len(obj.connections.outbound)}")

# Access scenes
for scene in app.scenes:
    print(f"Scene: {scene.name} ({scene.slug})")
    for view in scene.views:
        print(f"  View: {view.name} ({view.type})")
```

## Using KnackSleuth for Search

After loading metadata, use `KnackSleuth` to search for usages:

```python
from knack_sleuth import load_app_metadata, KnackSleuth

# Load metadata
metadata = load_app_metadata(app_id="abc123", no_cache=True)

# Create search engine
sleuth = KnackSleuth(metadata)

# Search for object usages
results = sleuth.search_object("object_12")

# Object-level usages
for usage in results["object_usages"]:
    print(f"[{usage.location_type}] {usage.context}")

# Field-level usages (cascaded)
for field_key, usages in results.items():
    if field_key.startswith("field_"):
        obj_info, field_info = sleuth.get_field_info(field_key)
        print(f"\nField: {field_info.name} ({field_key})")
        for usage in usages:
            print(f"  - {usage.context}")

# Search for specific field
field_usages = sleuth.search_field("field_116")
for usage in field_usages:
    print(f"[{usage.location_type}] {usage.context}")
```

## Complete Example

See `examples/library_usage_example.py` for a complete working example.

## Error Handling

The function raises standard Python exceptions that you can catch:

```python
from pathlib import Path
from knack_sleuth import load_app_metadata
import httpx

try:
    metadata = load_app_metadata(app_id="abc123", no_cache=True)
except FileNotFoundError as e:
    print(f"File not found: {e}")
except ValueError as e:
    print(f"Invalid parameters: {e}")
except httpx.HTTPStatusError as e:
    print(f"API error: {e.response.status_code}")
except httpx.RequestError as e:
    print(f"Network error: {e}")
```

## CLI vs Library Usage

| Feature | CLI Usage | Library Usage |
|---------|-----------|---------------|
| Import | N/A | `from knack_sleuth import load_app_metadata` |
| Error Handling | Rich console output + exit codes | Python exceptions |
| Caching | Automatic with console feedback | Optional (`no_cache=True` recommended) |
| Status Messages | Rich progress indicators | Silent (raises exceptions) |
| Use Case | Interactive terminal usage | Programmatic/scripted usage |
