# Development Ideas

Ideas from a code review pass (2026-06), kept here so they don't get lost.
Status legend: 💡 idea · 🚧 in progress · ✅ done

## Feature additions

### ✅ 1. `search-field` command
`KnackSleuth.search_field()` exists in the library (and is exported in `__all__`)
but was never exposed as a CLI command. Users had to run `search-object` on the
parent object and scan the cascade. A direct `knack-sleuth search-field field_116`
(or by name, with ambiguity handling since field names repeat across objects) is
the most natural gap to fill.

### ✅ 2. `diff` command for metadata snapshots
`knack-sleuth diff old.json new.json` (or `diff old.json --app-id X` for
snapshot-vs-live). Design decisions from the implementation:
- Entities matched by stable Knack keys, so renames are renames (not
  remove+add)
- Change set: objects added/removed/renamed; fields added/removed/changed
  (name, type, required, unique, connection relationship); scenes
  added/removed/renamed; views added/removed/changed (name, type)
- Noise rules: fields of added/removed objects (and views of added/removed
  scenes) are not repeated; record counts excluded (data, not structure)
- Output: rich (default), `--format json`, `--format markdown`; `--exit-code`
  exits 1 on differences (git-diff style, CI-friendly)
Future extensions: diff object-level rules/tasks, view sources/columns, scene
security settings — the current attribute set is deliberately conservative.

### ✅ 3. `find-orphans` command
Orphan detection exists inside `KnackSleuth._analyze_technical_debt()` but only
surfaces as *counts* in `app-summary`. A command that lists *which* fields and
objects are orphaned is the actionable version — that's the cleanup workflow
this tool exists for.

### ✅ 4. `--format json` on the interactive commands
Implemented: --format json on list-objects/search-object/search-field/show-coupling/find-orphans; errors and cache/status messages now go to stderr so piped stdout stays clean.

### ✅ 5. Instability metric (I = Ce / (Ca + Ce))
We already compute afferent/efferent coupling and use Robert Martin's
terminology in `list-objects`. The instability ratio completes the metric
family — objects with high Ca and low I are the "don't touch" ones, which pairs
naturally with `impact-analysis`.

## Structural improvements

### ✅ 6. Move the cache out of the CWD
Implemented: ~/.cache/knack-sleuth (XDG-aware, KNACK_CACHE_DIR override), KNACK_CACHE_TTL_HOURS, and cache dir|list|clear subcommands.

### ✅ 7. One shared object/field resolver
`search-object`, `show-coupling`, and `impact-analysis` each hand-rolled the
same "is it a key or a name?" loop, and `db_schema.py` had its own
`find_object_by_identifier`. Consolidated into `knack_sleuth.lookup` with
"did you mean?" suggestions (difflib) on miss.

## Housekeeping

- ✅ **Test coverage is lopsided**: `core.py` and `db_schema.py` are tested;
  `sleuth.py` (the actual search engine), `security.py`, and `cli.py` had no
  tests despite `tests/conftest.py` providing fixtures. Typer's `CliRunner`
  makes CLI tests cheap. Highest-value non-feature work. (Addressed across
  several PRs: lookup/orphan/CLI/json tests, env-driven core cache tests, and
  a 29-test `security.py` suite with independently-derived expectations plus
  role-access CLI smoke tests.)

## Follow-ups surfaced by the security.py test suite

- 💡 **`inherits_security` is not a trustworthy signal**: `Scene.authenticated`
  defaults to `False` (never `None`), so `analyze_scene_security`'s
  `parent_auth is not None` checks are always true and `inherits_security`
  is `True` for every scene with a resolvable parent — even one with its own
  explicit restriction. No wrong `requires_login` values in the sample data,
  but the boolean should mean "actually inherited something".
- 💡 **Slug collisions silently drop scenes in navigation**: `scenes_by_slug`
  is a plain dict; when two scenes share a slug (the sample app has two
  scenes with slug `users`), only the later one is kept. Security-identical
  in this dataset, but a latent misclassification risk. Consider keying
  navigation by scene key, or warning on duplicate slugs.
- ✅ **`httpx[http2]` extra is unused** — nothing passes `http2=True`, so `h2`
  is a dead transitive dependency. Drop the extra.
- ✅ **PyYAML fallback is dead code** — `pyyaml` is a hard dependency, but
  `impact-analysis` and `app-summary` still carry `try: import yaml / except
  ImportError` branches telling users to install it.
- ✅ **`requires-python = ">=3.13"` is stricter than the code** — nothing needs
  more than ~3.10-era syntax (`X | None`, builtin generics). Relaxing widens
  the `uvx` audience; CI would add matrix entries.
- ✅ **`test_no_cache.py` at repo root** is a manual script, not a pytest test —
  move to `examples/`/`scripts/` or convert to a real test.
- ✅ **Typo**: `__init__.py` docstring says "KnackSlueth".
