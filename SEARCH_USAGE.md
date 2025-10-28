# KnackSlueth Search API

## Overview

KnackSlueth provides powerful search capabilities to find all usages of objects and fields throughout your Knack application metadata.

## Basic Usage

```python
import json
from knack_slueth import KnackAppExport, KnackSlueth

# Load your Knack app export
with open("my_knack_app.json") as f:
    data = json.load(f)

# Create the search engine
app_export = KnackAppExport(**data)
slueth = KnackSlueth(app_export)

# Search for an object (with cascading to all its fields)
results = slueth.search_object("object_11")

# Search for a specific field
usages = slueth.search_field("field_116")
```

## Search Methods

### `search_object(object_key: str) -> dict[str, list[Usage]]`

Searches for all usages of an object and **cascades to search all fields** in that object.

**Returns:** Dictionary with:
- `"object_usages"`: List of places where the object itself is used
- `"field_XXX"`: Lists of usages for each field in the object (e.g., `"field_116"`)

**Example:**
```python
results = slueth.search_object("object_2")

# Object-level usages
for usage in results["object_usages"]:
    print(usage.context)

# Field-level usages (cascaded)
for field_key, usages in results.items():
    if field_key.startswith("field_"):
        print(f"Field {field_key}: {len(usages)} usages")
```

### `search_field(field_key: str) -> list[Usage]`

Searches for all usages of a specific field.

**Returns:** List of `Usage` objects

**Example:**
```python
usages = slueth.search_field("field_116")
for usage in usages:
    print(f"[{usage.location_type}] {usage.context}")
```

## Usage Object

Each usage found is represented by a `Usage` dataclass:

```python
@dataclass
class Usage:
    location_type: str  # Type of usage (see below)
    context: str        # Human-readable description
    details: dict       # Additional metadata
```

### Location Types

**Object-level:**
- `connection_outbound` - Object is target of a connection from another object
- `connection_inbound` - Object connects to another object
- `view_source` - Object is displayed in a view
- `view_parent_source` - Object is used as a parent source in a view

**Field-level:**
- `connection_field` - Field is a connection to another object
- `object_sort` - Field is used for sorting an object
- `object_identifier` - Field is the identifier (display field) for an object
- `field_equation` - Field is referenced in another field's equation/formula
- `view_column` - Field appears as a column in a table view
- `view_sort` - Field is used for sorting in a view
- `view_parent_connection` - Field is used as a parent connection in a view
- `view_connection_key` - Field is a connection key in a view
- `form_input` - Field appears as an input in a form view

## Helper Methods

### `get_object_info(object_key: str) -> KnackObject | None`

Get the full object definition.

```python
obj = slueth.get_object_info("object_11")
print(f"Object: {obj.name}")
print(f"Fields: {len(obj.fields)}")
```

### `get_field_info(field_key: str) -> tuple[KnackObject | None, KnackField | None]`

Get the field definition and its parent object.

```python
obj, field = slueth.get_field_info("field_116")
print(f"Field: {obj.name}.{field.name}")
print(f"Type: {field.type}")
```

## Complete Example

```python
import json
from knack_slueth import KnackAppExport, KnackSlueth

# Load data
with open("knack_app_export.json") as f:
    app_export = KnackAppExport(**json.load(f))

# Initialize search
slueth = KnackSlueth(app_export)

# Find all usages of an object and its fields
object_key = "object_11"
obj = slueth.get_object_info(object_key)
print(f"Analyzing: {obj.name} ({object_key})")

results = slueth.search_object(object_key)

# Show object usages
print(f"\nObject usages: {len(results['object_usages'])}")
for usage in results["object_usages"]:
    print(f"  • {usage.context}")

# Show field usages (cascaded)
for field in obj.fields:
    if field.key in results:
        usages = results[field.key]
        print(f"\n{field.name} ({field.key}): {len(usages)} usages")
        for usage in usages:
            print(f"  • [{usage.location_type}] {usage.context}")
```

## See Also

- `examples/search_example.py` - Complete working example
- `examples/parse_example.py` - Basic model usage
- `src/knack_slueth/models.py` - Data models
- `src/knack_slueth/slueth.py` - Search implementation
