---
name: knack-explorer
description: Explore Knack.app database structure using knack-sleuth CLI. Use when analyzing Knack apps, objects, fields, or relationships.
allowed-tools:
  - Bash(uvx knack-sleuth *)
agent: knack-dev
context: fork
---

<!-- knack-sleuth-version: 0.7.1 -->

# Knack App Explorer

You have access to `knack-sleuth`, a CLI for exploring Knack.app databases.

**Important:** The Knack metadata API is public — no API key is required. You only need the
application ID (`--app-id`), or have `KNACK_APP_ID` set as an environment variable.

## Available commands

Each command is invoked via `uvx knack-sleuth <command> ...`. Run any command with `--help` for full options.

### Discovery & search

- `list-objects` — List all objects with field counts, row counts, connection counts (Ca/Ce), and instability (I).
  - Key flags: `--sort-by-rows`
- `search-object` — Find all usages of an object (connections, views, forms, formulas).
  - Key flags: `--no-fields` to suppress field-level detail
- `search-field` — Find all usages of a single field (by key or name) without cascading through the whole object.
- `show-coupling` — Show afferent (inbound) and efferent (outbound) coupling for an object.
- `find-orphans` — List orphaned fields and objects (defined but not used anywhere), plus page-layout debt: orphaned views (defined on a scene but left out of its layout, so they never render), dangling layout keys, and stale view rule references. Orphaned views carry a builder deep link — there is no API to delete a view.

All five discovery/search commands support `--format rich|json`; use `--format json` for machine-readable output (status messages go to stderr, so stdout stays clean).

### Schema export

- `export-db-schema` — Export your app's database schema (objects, fields, relationships). **This is the command you usually want for schema/ER work.**
  - Formats: `--format json|dbml|yaml|mermaid`
  - Detail levels: `--detail structural|minimal|compact|standard`
- `export-schema-subgraph` — Export a subset of the schema starting from a specific object.
  - Key flags: `--object NAME_OR_KEY`, `--depth 0|1|2`, plus the same `--format` and `--detail` as above
- `export-schema` — Export Knack's *internal* metadata schema (rarely needed; use `export-db-schema` for your app's structure).

### Change tracking

- `diff` — Compare two metadata snapshots (or a snapshot vs the live app) and report structural changes.
  - Key flags: `--format rich|json|markdown`, `--exit-code` to exit 1 when changes are found (CI-friendly)

### Analysis (experimental)

- `impact-analysis` — Analyze how changing an object or field would ripple through the app.
  - Formats: `--format json|yaml|markdown`
- `app-summary` — Generate a comprehensive architectural summary (domain model, coupling, tech debt).
  - Formats: `--format json|yaml|markdown`

### Security & access

- `role-access-review` — CSV report of which user profiles (roles) can access which scenes/pages.
  - Key flags: `--summary-only` for top-level pages only
- `role-access-summary` — Show all pages and views accessible by a specific role.
  - Key flags: `--role "Role Name"` or `--profile-key profile_1`

### Utility

- `download-metadata` — Download and save Knack app metadata to a local JSON file (the output path is a positional argument).
- `cache` — Manage the local metadata cache: `cache list`, `cache clear [--app-id ID]`, `cache dir`.

## Usage

Most commands work in two modes:

- **API mode:** pass `--app-id YOUR_APP_ID` (or set `KNACK_APP_ID`) to fetch metadata directly from Knack.
- **File mode:** point commands at a local metadata file previously created with `download-metadata`.

Object and field arguments accept either a key (`object_12`, `field_116`) or a name. On a failed
lookup the CLI prints "did you mean" suggestions. Field names repeat across objects — if a field
name is ambiguous, the CLI lists all candidate keys; re-run with the exact key.

### Caching

When using `--app-id` directly, metadata is auto-cached in `~/.cache/knack-sleuth/` (override
with `KNACK_CACHE_DIR`) and reused for 24 hours (`KNACK_CACHE_TTL_HOURS` to change).
Use `--refresh` to force a fresh download, and `cache list` / `cache clear` to inspect or
reset the cache.

### Download-first strategy (recommended for multi-command sessions)

When running multiple commands against the same app, download once and reuse the file:

```
uvx knack-sleuth download-metadata app.json --app-id YOUR_APP_ID
uvx knack-sleuth list-objects app.json
uvx knack-sleuth search-object "Object Name" app.json
uvx knack-sleuth export-db-schema app.json -f dbml -o schema.dbml
```

### Structured output for analysis

When you need to process command output programmatically, prefer `--format json`.
`impact-analysis`, `app-summary`, and `diff` take an `--output file.json` flag; the
discovery/search commands print clean JSON to stdout (status messages go to stderr),
so redirect with `>`:

- `uvx knack-sleuth impact-analysis object_12 --format json --output impact.json`
- `uvx knack-sleuth app-summary --format json --output summary.json`
- `uvx knack-sleuth list-objects --format json > objects.json`
- `uvx knack-sleuth search-object object_12 --format json > usage.json`
- `uvx knack-sleuth find-orphans --format json > orphans.json`

Use `--format markdown` when the output is for human consumption.

### Common patterns

- Search usages of one field:
  - `uvx knack-sleuth search-field field_116 --app-id YOUR_APP_ID`
- Find unused fields/objects (cleanup candidates):
  - `uvx knack-sleuth find-orphans --app-id YOUR_APP_ID`
- Diff two snapshots (structural changes only):
  - `uvx knack-sleuth diff old.json new.json`
- Diff a snapshot against the live app:
  - `uvx knack-sleuth diff old.json --app-id YOUR_APP_ID`
- Role access review (CSV output):
  - `uvx knack-sleuth role-access-review --app-id YOUR_APP_ID --output role-access.csv`
- Role access summary for a profile (CSV output):
  - `uvx knack-sleuth role-access-summary --app-id YOUR_APP_ID --profile-key profile_key --output role-summary.csv`

## Typical workflow

1. **Orient** — Run `list-objects` to see all objects, row counts, and coupling metrics.
2. **Investigate** — Use `search-object`, `search-field`, and `show-coupling` to trace how specific objects and fields are used.
3. **Visualize** — Export schemas with `export-db-schema` or `export-schema-subgraph` (DBML or Mermaid for diagrams, YAML for readability).
4. **Assess** — Run `impact-analysis` on objects/fields being considered for change, or `app-summary` for a full architectural overview.
5. **Clean up** — Use `find-orphans` to list unused resources — but flag identifier/system fields, which can be orphans by design. Orphaned views can only be removed through the builder link the command prints. Knack's REST API is record-only, and its MCP server mutates tables/fields but explicitly not pages/views — so no API can delete a view.
6. **Track changes** — Use `diff` to compare snapshots or snapshot-vs-live for "what changed?" questions.
7. **Audit access** — Use `role-access-review` and `role-access-summary` for permission and security questions.

## Presenting results

- Summarize key findings before showing raw data.
- Highlight important objects (high coupling, high row count, hub objects).
- When reporting on relationships, note the direction (inbound vs outbound).
- For impact analysis, call out the risk level and affected workflows.
- When multiple objects are involved, organize findings by domain cluster or dependency chain.
