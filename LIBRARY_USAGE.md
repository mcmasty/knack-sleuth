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

## Finding Orphans

`KnackSleuth` exposes five orphan detectors. The first two find unreachable *data*;
the last three find *page-layout* debt — a Knack scene stores its layout
(`groups[].columns[].keys[]`) separately from its view definitions (`scene.views`),
and nothing keeps the two in sync.

```python
from knack_sleuth import KnackSleuth, load_app_metadata

sleuth = KnackSleuth(load_app_metadata(app_id="abc123", no_cache=True))

# Unused data definitions
for obj, field in sleuth.find_orphaned_fields():
    print(f"{obj.name}.{field.name} ({field.key}) is unused")

for obj in sleuth.find_orphaned_objects():
    print(f"{obj.name} ({obj.key}) has no connections and no views")
```

### Orphaned views

A view defined on a scene but left out of that scene's layout never renders. These
accumulate when a page is copied or a view is moved.

```python
for orphan in sleuth.find_orphaned_views():
    print(f"{orphan.scene.name}: {orphan.view.name} ({orphan.view.key})")
```

`OrphanedView` carries the full `Scene` and `View` models, not just keys, so you can
inspect the dead view's source object, columns, or inputs.

Two exclusions are built in, and they matter: `login` views render from the scene
chrome rather than the layout grid, and a scene with an *entirely* empty layout has no
layout to be excluded from (Knack leaves `groups` empty on the child pages it generates
for Edit/Details/Delete links). Without them the check over-reports by roughly 5x.

### Dangling layout keys and stale rule references

The inverse defect, and its knock-on:

```python
for item in sleuth.find_dangling_layout_keys():
    where = f"moved to {item.moved_to}" if item.moved_to else "deleted"
    print(f"{item.scene.key} layout points at {item.view_key} ({where})")

for item in sleuth.find_stale_view_rule_references():
    # reason is "orphaned" (defined but off-layout) or "missing" (gone entirely)
    print(f"{item.scene.key} {item.rule_path} -> {item.view_key} ({item.reason})")
```

`rule_path` is a dotted path into the scene, e.g. `rules.0.view_keys`, so you can locate
the rule in a raw metadata export.

### Orphaned views do not count as usage

A reference living only in an orphaned view cannot keep a field or object looking alive,
so `find_orphaned_fields()` and `find_orphaned_objects()` ignore it. The reference is
still reported by `search_field()`, tagged so you can tell the dead ones apart:

```python
for usage in sleuth.search_field("field_116"):
    if usage.details.get("orphaned_view"):
        print(f"DEAD: {usage.context}")
    else:
        print(f"live: {usage.context}")
```

`sleuth.orphaned_view_keys` holds the same set if you need it directly.

## Linking into the Builder

No API can delete a view. Knack's REST API is record-level CRUD only ("View-Based
DELETE" deletes a *record through* a view). Knack's MCP server can create, update, and
delete tables and fields, but it "does not support Knack-based frontend / Page / Theme
building" — pages and views stay builder-only. So orphaned views cannot be removed
programmatically; the cleanup path is the builder UI.

That is awkward for an orphan specifically: it is not on the page canvas, so there is
nothing to hover and delete. `builder_url()` builds a view-level deep link, which is the
only handle on it.

```python
from knack_sleuth import builder_url

app = metadata.application

# Page-level link
builder_url(app, "scene_455")
# -> https://builder.knack.com/{account_slug}/{app_slug}/pages/scene_455

# View-level link -- the one an orphan needs
for orphan in sleuth.find_orphaned_views():
    print(builder_url(
        app,
        orphan.scene.key,
        view_key=orphan.view.key,
        view_type=orphan.view.type,
    ))
# -> https://builder.knack.com/{account_slug}/{app_slug}/pages/scene_455/views/view_1377/form

# Next-Gen builder host
builder_url(app, "scene_455", next_gen=True)
# -> https://builder-next.knack.com/...
```

The grammar is `{account_slug}/{app_slug}/pages/{scene_key}` — two *different* slugs, since
the account owns the app. `builder_url()` reads both off the `Application` model and falls
back to the app slug when `account.slug` is absent.

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
