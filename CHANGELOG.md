# Changelog

## Unreleased

### Changed

- `download-metadata` now goes through the same cache-then-API loader as every other
  command, so a download also refreshes the local cache, and an unreadable cache file reports
  the same warning everywhere.
- `impact-analysis` and `app-summary` reject an unknown `--format` before loading metadata.
- Development: `cli.py` (3,400 lines, 27 lint suppressions) is now the `knack_sleuth.cli`
  package, one module per command group, with no suppressions. `knack-sleuth` and
  `from knack_sleuth.cli import cli` work as before; `python -m knack_sleuth.cli` also works.
- Development: a lint ratchet (`scripts/lint_ratchet.py`, run in CI and pre-commit) fails
  when `# noqa`-suppressed findings or config-level ignores increase. Decreases pass;
  `bump-my-version` lowers `lint-baseline.json` in the release commit, and CI on a release
  tag fails if the baseline is looser than the code. Coverage floor raised from 72% to 90%.

## 0.9.2

### Fixed

- `app-summary` classed an object with exactly 100 records as neither a small lookup table nor
  a large transactional table, so it fell through to "supporting". 100 now counts as
  transactional.

## 0.9.1

### Fixed

- `export-schema --mode <unknown>` no longer prints a second, misleading "Failed to generate
  or save schema: 1" error after the real one. This was found by ruff's TRY301 rule.
- `export-db-schema --format mermaid` no longer emits attribute names that Mermaid can't parse
  when a field name contains ª, ¹, ², ³, µ, º, ¼, ½ or ¾ (e.g. "Area m²"). Field names are
  Unicode-normalised first, so "Area m²" becomes `areaM2`. This was found by a hypothesis
  property test.

### Changed

- `rich` is now a declared dependency. It was already installed through typer, but the CLI
  imports it directly.
- Development: CI also checks formatting (`ruff format`), dead code (vulture), declared
  dependencies (deptry), a minimum coverage (lines and branches combined) and the built wheel.
  The 3.11–3.13 test jobs now actually run on those versions; previously `.python-version`
  made every job run on 3.14. Dependency vulnerabilities are audited by a separate workflow
  that doesn't gate releases. A pre-commit config, an expanded ruff rule set and hypothesis
  property tests were added.

## 0.9.0

### Added

- `show-rules --object <name|key> [--view view_NNN] [--format json]` shows what an object's
  forms, action links and scheduled tasks do:
  - Email rules: subject, recipients and conditions. Record-field recipients appear by field key
    and name. Custom addresses are masked to their domain. Bodies and sender addresses are never
    printed.
  - Record rules: field = value assignments, plus connected-record updates and inserts.
  - Submit rules: message, redirect or child page.
  - Scheduled tasks, with their run status.
  - Record rules on other objects' views that change this object through a connection, with
    the conditions and emails of the same click or submit.
  - Conditional field rules, which set values whenever a record is saved.
  - Views on the object that have no rules, so "nothing here" can be seen rather than inferred.
  - Rules on orphaned views are flagged unreachable.
  - A warning when an email rule uses a field that a record rule on the same trigger blanks
    first. Email rules run after record rules.
- Object lookup falls back to an object's singular or plural inflection when only one object
  matches, so `--object Applicant` finds an object named "Applicants".

### Fixed

- `app-summary` no longer crashes when a connected object has no connections of its own.
  This was found by pyrefly.

### Changed

- Crash tracebacks no longer print local variables. Commands hold raw app metadata, which can
  include email bodies and addresses.
- CI now gates on `ruff check` and `pyrefly check` as well as the tests, and `uv sync --locked`
  fails on a stale lock file. The publish workflow runs the same checks first and publishes only
  if they pass. Ruff now lints `tests/` too.
- The `knack-explorer` skill now fires on behaviour questions as well as schema questions, such as
  "does this button send an email?", "what happens when a user submits X?" and "which roles can
  change this?". It also states that a code search finding nothing does not prove nothing happens.
  It gains a "Behaviour lives in view rules" section, a worked example, and guidance on checking
  the age of a cached snapshot and fetching fresh metadata without credentials. Run
  `knack-sleuth install-skill --force` to update an installed copy.

Earlier releases are recorded in the git history.
