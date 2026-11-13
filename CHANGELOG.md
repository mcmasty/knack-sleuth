# Changelog

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
