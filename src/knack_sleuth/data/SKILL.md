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

## Available commands

Each command is invoked via `uvx knack-sleuth <command> ...`.

- `list-objects` — List all objects in a Knack application with field counts, connection counts (Ca/Ce), and instability (I).
- `search-object` — Search for all usages of an object in a Knack application.
- `search-field` — Search for all usages of a single field (by key or name) without cascading through the whole object.
- `show-coupling` — Show coupling relationships for a specific object.
- `find-orphans` — List orphaned fields and objects (defined but not used anywhere).
- `download-metadata` — Download and save Knack application metadata to a local file.
- `diff` — Compare two metadata snapshots (or a snapshot vs the live app) and report structural changes.
- `export-schema` — Export Knack's internal metadata schema (how an application looks to Knack itself).
- `export-db-schema` — Export your application's database schema (how your app looks to you).
- `export-schema-subgraph` — Export a subgraph of the database schema starting from a specific object.
- `impact-analysis` — [EXPERIMENTAL] Generate a comprehensive impact analysis for human and AI/agent consumption.
- `app-summary` — [EXPERIMENTAL] Generate a comprehensive architectural summary for human and AI/agent consumption.
- `role-access-review` — Generate a role access review showing which user profiles can access which scenes.
- `role-access-summary` — Show all pages and views accessible by a specific user profile (role).

## Usage

Most commands can work in two modes:

- **API mode (recommended):** pass `--app-id YOUR_APP_ID` to fetch metadata directly from Knack.
- **File mode:** point commands at a local metadata file previously created with `download-metadata`.

Object and field arguments accept either a key (`object_12`, `field_116`) or a name. On a failed
lookup the CLI prints "did you mean" suggestions. Field names repeat across objects — if a field
name is ambiguous, the CLI lists all candidate keys; re-run with the exact key.

### Common patterns

- List objects (API):
  - `uvx knack-sleuth list-objects --app-id YOUR_APP_ID`
- List objects (local file):
  - `uvx knack-sleuth list-objects path/to/app.json`
- Search usages of one field:
  - `uvx knack-sleuth search-field field_116 --app-id YOUR_APP_ID`
- Find unused fields/objects (cleanup candidates):
  - `uvx knack-sleuth find-orphans --app-id YOUR_APP_ID`
- Download metadata for reuse (output file is a positional argument):
  - `uvx knack-sleuth download-metadata app.json --app-id YOUR_APP_ID`
- Diff two snapshots (structural changes only; `--format json` for machine-readable output):
  - `uvx knack-sleuth diff old.json new.json`
- Diff a snapshot against the live app:
  - `uvx knack-sleuth diff old.json --app-id YOUR_APP_ID`
- Export DB schema (e.g. DBML):
  - `uvx knack-sleuth export-db-schema --app-id YOUR_APP_ID -f dbml --output schema.dbml`
- Role access review (CSV output):
  - `uvx knack-sleuth role-access-review --app-id YOUR_APP_ID --output role-access.csv`
- Role access summary for a profile (CSV output):
  - `uvx knack-sleuth role-access-summary --app-id YOUR_APP_ID --profile-key profile_key --output role-summary.csv`

### Typical workflow

1. Start by listing objects to understand the data model (`list-objects`).
2. Use search and coupling tools to understand usage and relationships (`search-object`, `search-field`, `show-coupling`, `export-schema-subgraph`).
3. Generate schema exports and summaries for deeper analysis or documentation (`export-db-schema`, `impact-analysis`, `app-summary`).
4. For cleanup or refactoring questions, list unused resources (`find-orphans`) — but flag identifier/system fields, which can be orphans by design.
5. For "what changed?" questions, compare snapshots or snapshot-vs-live (`diff`).
6. When questions involve permissions or UX, use role access commands (`role-access-review`, `role-access-summary`).

## Output:

Present findings in clear, structured format. Highlight key objects and relationships.
