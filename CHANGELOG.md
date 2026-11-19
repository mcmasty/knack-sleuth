# Changelog

## Unreleased

### Added

- `show-rules` lists page rules (`scenes[].rules`): the rules that hide a view, show a
  message or redirect away when a page loads. They are reported for every page that holds
  one of the object's views, and for pages whose rules test the object's fields. With
  `--view`, rules that only hide other views are left out. In the JSON output they are under
  `page_rules`.

### Fixed

- `role-access-summary --role` could pick a role whose name differs by whitespace over one
  that differs only by case ("job admin" chose "Job  Admin" over "Job Admin"). The role
  name is now matched as written, then ignoring case, then ignoring stray whitespace, and a
  looser reading is used only when a stricter one finds nothing.
- `role-access-review` gave a page the concern `OK` when it adds its own login, with no role
  limit, below a public page. The summary counted it as unrestricted but its row did not
  say so. Such a page is now flagged `UNRESTRICTED`, like a top-level one. A page below a
  login-only page is still covered by the flag on that page.
- Table cells in `list-objects`, `find-orphans` and `cache list` printed a name ending in a
  backslash with two, and crashed on a key containing a closing tag such as `[/x]`. Cells
  now hold the text exactly as written.
- `role-access-review --summary-only` gave a menu a `child_count` of 0 for a page that still
  names a deleted menu, even though the page sits below one of the menu's member pages and
  its navigation path says so. A menu reference that points at no scene is now skipped when
  counting, as it already was when building the path.
- `show-rules` marked inline-edit rules as active wherever the view had `cell_editor` on,
  including on a details view or a link column that cannot be edited in place. Rules are
  now active only on a field column of a table; anything else is listed as inactive with
  the reason.
- `show-rules --object` collapsed a page rule into "N rule(s) hiding other views" when the
  page was listed only because its rules test the object's fields. Those rules are the
  reason the page is shown, so they are now printed in full. Each page in the JSON
  `page_rules` says how it was matched (`matched_by`: `views` or `criteria`).
- A scene whose `menu` value is not a scene key (a list or an object) crashed
  `role-access-review`, `role-access-summary` and, since it began using the same analysis,
  `app-summary`, with a `TypeError`. Such a value now reads as "no menu".
- Looking up an object by name could pick the wrong one when two names differ only by
  whitespace ("Job  Status" and "Job Status"): the first in the export won. The name as
  written now wins, and a name that matches two objects only after whitespace is ignored is
  reported as not found instead of guessed.
- `role-access-review` reported a login page as PUBLIC when its login view's role limit was
  off and the page did not set `authenticated` itself, and reported the pages below it as
  public too. A page with a login view now counts as requiring a login whatever its role
  limit says; with the limit off it gets the `UNRESTRICTED` concern. On a real app this
  moves 2 pages from public to login-required.
- `list-objects` reported twice the number of connections in its total line and in
  `totals.connections` of the JSON output (228 for an app with 114), because it added each
  object's inbound and outbound counts. Each connection is now counted once, by its field
  key, so one that only a single object records is still counted. The per-object `Total`
  column is unchanged.
- `role-access-summary --role` did not find a role whose name was saved with a stray space.
  Role names are now matched like object and field names, ignoring case and extra
  whitespace.
- `show-rules` named no field for a condition on the logged-in user (`profile_3-field_9`,
  `all_users-field_9`) or on a connected record (`field_4-field_9`). These now read
  "logged-in user's Email" and "Program > Title".
- Names containing square brackets were read as Rich markup in terminal output: a field
  called "Amount [usd]" printed as "Amount", and a name containing a closing tag such as
  `[/internal]` crashed the command with a `MarkupError`. Every command now prints names,
  paths and identifiers exactly as written. JSON, CSV and Markdown output was never
  affected.
- An object or field whose name was saved with a stray space ("Status ") could not be found
  by the name you can see: `search-field Status` answered "Did you mean: Status ?". Name
  lookups now ignore leading, trailing and repeated whitespace.
- `show-rules` ignored the record rules that run when a table cell is edited in place
  (`columns[].edit_rules`), and listed such a table under "no form rules or action links".
  They are now reported as an `inline_edit` trigger, including when they change another
  object through a connection. Rules left behind on a table or column whose inline editing
  is off are listed as inactive. On a real app this adds 7 rules on 6 columns, 5 of them
  active.
- `role-access-review --summary-only` inflated `child_count` for a page whose name is part
  of another page's name: "Jobs" was credited with everything under "Jobs Archive". Children
  are now counted by following parent pages, not by matching names. On a real app two rows
  dropped from 9 to 6 and from 10 to 1.
- `app-summary` miscounted three access and navigation figures. They now agree with
  `role-access-review`:
  - Public and authenticated scenes were counted from each page's own `authenticated` flag,
    so a page behind a login page counted as public. On the sample app it reported 63 of 65
    pages as public; none are.
  - Navigation depth compared a page's `parent` (a slug) with scene keys, so it never went
    past 2. Parents are now followed by slug, a page below a namesake counts as a level,
    and a loop of parents never counts a page as its own ancestor.
  - "Role-restricted scenes" counted pages that have a layout. It now counts pages limited
    to named roles, directly or through an ancestor.
- `show-rules` dropped the span from relative date conditions: "is during the next 7 days"
  printed as "is during the next". The span is now shown, and is in the JSON output as
  `range` on the criterion.
- `show-rules` printed the recipient of a form's email notification as `None: None ?`. These
  recipients are bare addresses with no type or mode; they now show as a masked `to:`
  address, and the rule is labelled `Email notification`.
- `role-access-review` and `role-access-summary` read a leftover `allowed_profiles` list as
  a role restriction when `limit_profile_access` was off. Knack keeps the list after the
  "limit to roles" switch is turned off and no longer enforces it, so such a page was
  reported as locked to those roles when any logged-in user could open it. A login view's
  list now counts only while its `limit_profile_access` is on, and a page's own list is
  ignored when its `limit_profile_access` is `false`; these pages get the `UNRESTRICTED`
  concern instead (#24).

## 0.10.0

### Fixed

- `find-orphans` reported fields as unused when only other metadata named them: a
  connected-field formula (`{field_2.field_1}`), an equation stored as a list, a sum/count
  field or its filters, a conditional rule, validation, a scheduled task, or a page rule.
  These now count as usages (`field_reference`, `object_reference`, `scene_reference`), so
  `search-field`, `search-object`, `impact-analysis` and `app-summary` report them too. On a
  real app, 12 of 203 reported orphans were in use.
- `impact-analysis` of a field ignored the formula, rule, task and page-rule references that
  `find-orphans` now counts, so a field used only in a page rule scored `none`. Sum, count
  and similar fields that name it are now under `formulas` (with `equation: null`); object
  rules, validations, tasks and page rules are under a new `direct_impacts.rules`. Both count
  toward the score, and object analysis picks them up from the object's fields too.
- `impact-analysis` scored views and forms that no page shows. They are still listed, with
  `orphaned_view: true`, but no longer count, and their scenes are not listed as affected.
- `impact-analysis` of a field left out the pages of the forms that use it; object analysis
  already listed them.
- `app-summary` listed some objects twice in `transactional_entities` or `supporting_entities`,
  and listed core entities there as well, so the markdown counts were inflated (41
  transactional entries for 25 objects on a real app). Each object is now in exactly one
  category.
- DBML exports failed to load in dbdiagram and other DBML tools: every `Ref` pointed at the
  target's identifier field, which `structural` and `minimal` detail leave out, or at a column
  that doesn't exist when the target has no identifier, and quotes in the app name broke the
  project `Note`. Each table now declares the Knack record `id` as its primary key, Refs point
  at it, outbound connection columns appear at every detail level, and strings are escaped.
  The identifier field is no longer marked `pk`; its comment says `identifier` instead.
  Checked with `@dbml/core`: master's export of a real app gave 228 errors, now none.
- Mermaid exports drew one relationship per pair of objects, so a second connection between
  the same two objects disappeared (95 of 114 connections shown on a real app). Every
  connection now has its own line. Double quotes in a field description or connection name no
  longer break the diagram.
- DBML, Mermaid and YAML exports, and `app-summary`'s relationship `type`, read one-to-many
  connections backwards. Knack's `has` is how many connected records each connecting record
  holds, and `belongs_to` how many connecting records each connected record can belong to,
  so `Events.Client` with `has: one, belongs_to: many` is many Events to one Client. Real
  records confirm it: no Event holds two Clients, and one Client is on up to four Events.
  These were drawn as one Event to many Clients (`||--o{`, `<`, `one-to-many`,
  `one_to_many`); now they are `}o--||`, `>`, `many-to-one` and `many_to_one`, and the
  reverse for `has: many, belongs_to: one`. One-to-one and many-to-many are unchanged.
  In YAML, an inbound connection's `relationship_type` reads from the object listing it,
  so Clients lists the Events connection as `one-to-many`.
  `show-coupling` and `search-object` printed Knack's raw pair (`[one → many]`,
  `"one to many"`), which reads the same wrong way. They now print the same labels:
  `show-coupling` from the object shown (its JSON gains `relationship_type`), and
  `search-object`'s `relationship` from the connecting object.
- One null in the metadata, such as a view with `name: null`, made every command exit with
  a multi-line pydantic dump. A null now means "absent": fields with a default take it, and a
  null name, slug or inflection falls back to the key. Of 879 places in the sample metadata,
  a null used to break loading in 109 and now breaks it in 42. Those 42 are keys, types,
  connection targets and null list entries, and they now fail with one line naming the
  path, for example `Invalid metadata at application.scenes[2].views[0].key: Input should
  be a valid string, got null`.
- A null entry in a view's `allowed_profiles` crashed the security report.
- `impact-analysis` and `app-summary` list scenes and clusters in the same order on every run;
  they used to depend on Python's per-process string hashing.

### Changed

- `impact-analysis` fills `cascade_impacts.affected_objects` with the other objects that
  connect to, compute from, or have rules on the target. It was always empty. The
  always-empty `cascade_impacts.dependency_chains` and always-null
  `metadata.analysis_timestamp` are removed, and an unknown target type is an error instead
  of an analysis with likelihood `unknown`.
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
