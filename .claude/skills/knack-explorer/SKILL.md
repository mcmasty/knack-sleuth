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

- `list-objects` — List all objects in a Knack application with field and connection counts.
- `search-object` — Search for all usages of an object in a Knack application.
- `show-coupling` — Show coupling relationships for a specific object.
- `download-metadata` — Download and save Knack application metadata to a local file.
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

### Common patterns

- List objects (API):
  - `uvx knack-sleuth list-objects --app-id YOUR_APP_ID`
- List objects (local file):
  - `uvx knack-sleuth list-objects path/to/app.json`
- Download metadata for reuse:
  - `uvx knack-sleuth download-metadata --app-id YOUR_APP_ID --output app.json`
- Export DB schema (e.g. DBML):
  - `uvx knack-sleuth export-db-schema --app-id YOUR_APP_ID -f dbml --output schema.dbml`
- Role access review:
  - `uvx knack-sleuth role-access-review --app-id YOUR_APP_ID --output role-access.json`
- Role access summary for a profile:
  - `uvx knack-sleuth role-access-summary --app-id YOUR_APP_ID --profile-key profile_key --output role-summary.json`

### Typical workflow

1. Start by listing objects to understand the data model (`list-objects`).
2. Use search and coupling tools to understand usage and relationships (`search-object`, `show-coupling`, `export-schema-subgraph`).
3. Generate schema exports and summaries for deeper analysis or documentation (`export-db-schema`, `impact-analysis`, `app-summary`).
4. When questions involve permissions or UX, use role access commands (`role-access-review`, `role-access-summary`).

## Output:

Present findings in clear, structured format. Highlight key objects and relationships.
