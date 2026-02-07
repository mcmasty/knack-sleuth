---
name: knack-explorer
description: Explore Knack.app database structure using knack-sleuth CLI. Use when analyzing Knack apps, objects, fields, or relationships.
allowed-tools:
  - Bash(uvx knack-sleuth *)
agent: knack-dev
context: fork
---

# Knack App Explorer

You have access to `knack-sleuth`, a CLI for exploring Knack.app databases.

**Important:** The Knack metadata API is public — no API key is required. You only need the application ID (`--app-id`), or have `KNACK_APP_ID` set as an environment variable.

## Available commands

Each command is invoked via `uvx knack-sleuth <command> ...`. Run any command with `--help` for full options.

### Discovery & search

- `list-objects` — List all objects with field counts, row counts, and coupling metrics (Ca/Ce).
  - Key flags: `--sort-by-rows`
- `search-object` — Find all usages of an object (connections, views, forms, formulas).
  - Key flags: `--no-fields` to suppress field-level detail
- `show-coupling` — Show afferent (inbound) and efferent (outbound) coupling for an object.

### Schema export

- `export-db-schema` — Export your app's database schema (objects, fields, relationships). **This is the command you usually want for schema/ER work.**
  - Formats: `--format json|dbml|yaml|mermaid`
  - Detail levels: `--detail structural|minimal|compact|standard`
- `export-schema-subgraph` — Export a subset of the schema starting from a specific object.
  - Key flags: `--object NAME_OR_KEY`, `--depth 0|1|2`, plus same `--format` and `--detail` as above
- `export-schema` — Export Knack's *internal* metadata schema (rarely needed; use `export-db-schema` for your app's structure).

### Analysis (experimental)

- `impact-analysis` — Analyze how changing an object or field would ripple through the app.
  - Formats: `--format json|yaml|markdown`
- `app-summary` — Generate a comprehensive architectural summary (domain model, coupling, tech debt).
  - Formats: `--format json|yaml|markdown`

### Security & access

- `role-access-review` — CSV report of which roles can access which scenes/pages.
  - Key flags: `--summary-only` for top-level pages only
- `role-access-summary` — Show all pages and views accessible by a specific role.
  - Key flags: `--role "Role Name"` or `--profile-key profile_1`

### Utility

- `download-metadata` — Download and cache Knack app metadata as a local JSON file.

## Usage patterns

### Environment variable

If `KNACK_APP_ID` is set, you can omit `--app-id` from all commands:
- `uvx knack-sleuth list-objects`

### Download-first strategy (recommended for multi-command sessions)

When running multiple commands against the same app, download once and reuse the file. This avoids repeated API calls and is faster:

```
uvx knack-sleuth download-metadata --app-id APP_ID --output app.json
uvx knack-sleuth list-objects app.json
uvx knack-sleuth search-object "Object Name" app.json
uvx knack-sleuth export-db-schema app.json -f dbml -o schema.dbml
```

### Caching

When using `--app-id` directly, metadata is auto-cached for 24 hours. Use `--refresh` to force a fresh download.

### Structured output for analysis

When you need to process command output programmatically, prefer `--format json` and `--output file.json`:
- `uvx knack-sleuth impact-analysis object_12 --format json --output impact.json`
- `uvx knack-sleuth app-summary --format json --output summary.json`

Use `--format markdown` when the output is for human consumption.

## Typical workflow

1. **Orient** — Run `list-objects` to see all objects, row counts, and coupling metrics.
2. **Investigate** — Use `search-object` and `show-coupling` to trace how specific objects are used.
3. **Visualize** — Export schemas with `export-db-schema` or `export-schema-subgraph` (DBML or Mermaid for diagrams, YAML for readability).
4. **Assess** — Run `impact-analysis` on objects/fields being considered for change, or `app-summary` for a full architectural overview.
5. **Audit access** — Use `role-access-review` and `role-access-summary` for permission and security questions.

## Presenting results

- Summarize key findings before showing raw data.
- Highlight important objects (high coupling, high row count, hub objects).
- When reporting on relationships, note the direction (inbound vs outbound).
- For impact analysis, call out the risk level and affected workflows.
- When multiple objects are involved, organize findings by domain cluster or dependency chain.
