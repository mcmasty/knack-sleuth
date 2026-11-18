# Tests

This directory contains the test suite for knack-sleuth.

## Running Tests

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_core.py

# Run specific test class
uv run pytest tests/test_core.py::TestLoadFromFile

# Run specific test
uv run pytest tests/test_core.py::TestLoadFromFile::test_load_from_file_success

# Run with coverage (if coverage is installed)
uv run pytest --cov=knack_sleuth --cov-report=html
```

## Test Structure

### `conftest.py`
Contains shared pytest fixtures:
- `sample_metadata_file`: Path to sample JSON file
- `sample_metadata_dict`: Parsed sample metadata
- `mock_api_response`: Mock httpx response
- `mock_api_error`: Mock API error

### `test_core.py`
High-value tests for `knack_sleuth.core.load_app_metadata()`:

#### TestLoadFromFile
- ✅ Load from valid file
- ✅ Error on missing file
- ✅ Error on invalid JSON

#### TestNoCacheParameter
- ✅ `no_cache=True` doesn't create cache files
- ✅ `no_cache=False` creates cache files
- ✅ Default behavior is `no_cache=False`

#### TestCacheExpiry
- ✅ Cache used within 24 hours
- ✅ Cache ignored after 24 hours

#### TestRefreshParameter
- ✅ `refresh=True` bypasses valid cache

#### TestErrorHandling
- ✅ ValueError when app_id missing
- ✅ HTTPStatusError for API errors
- ✅ RequestError for network errors

#### TestSettingsIntegration
- ✅ Uses app_id from environment settings

**Total: 13 tests**

## Test Data

The `data/` directory contains:
- `sample_knack_app_meta.json`: Sample Knack application metadata for testing

## Writing New Tests

### Example Test

```python
def test_new_feature(mocker, sample_metadata_file):
    """Test a new feature."""
    # Arrange
    mock_something = mocker.patch("knack_sleuth.core.something")

    # Act
    result = load_app_metadata(file_path=sample_metadata_file)

    # Assert
    assert result.application.name == "Sample Application"
    mock_something.assert_called_once()
```

### Using Fixtures

```python
def test_with_fixtures(sample_metadata_file, mock_api_response):
    """Use shared fixtures."""
    # sample_metadata_file and mock_api_response are automatically available
    pass
```

### Mocking Best Practices

1. **Mock at the boundary**: Mock `httpx.get`, not internal functions
2. **Be specific**: Mock `knack_sleuth.core.httpx.get`, not globally
3. **Verify behavior**: Assert calls, not implementation details
4. **Use fixtures**: Share common mocks via conftest.py

## CI/CD Integration

`.github/workflows/test.yml` runs on every push and PR, and `publish.yml` runs it
before a release:

- **Lint job (Python 3.11):** `ruff check`, `ruff format --check`, the lint
  ratchet (below), `pyrefly check`, `vulture` (dead code) and `deptry src`
  (imports match declared dependencies).
- **Test job (3.11–3.13, Ubuntu and macOS):** `pytest --cov`. `UV_PYTHON` is set
  per job because `.python-version` (3.14, for local development) would otherwise
  win, and a step fails if the interpreter doesn't match the matrix entry.
- **Package job:** builds the wheel, installs it outside the checkout, and runs the
  CLI and `install-skill` to confirm the package data ships.

`.github/workflows/audit.yml` runs `uv audit` against `uv.lock` when dependencies
change, weekly and on demand. It deliberately doesn't gate releases, so a failure
there is the maintainer's to triage: upgrade the package, or add `--ignore <ID>`
with a reason.

Whether PRs must pass these checks before merging is set by branch protection on
GitHub, not by anything in this repo.

Pre-commit runs the fast subset (ruff lint and format, the lint ratchet, pyrefly, and whitespace,
YAML/TOML and large-file checks) before each commit. Tests, coverage, vulture and
deptry run only in CI.

```bash
uv run pre-commit install
uv run pre-commit run --all-files   # all hooks, on demand
```

## Lint Ratchet

Functions over the complexity or size limits carry a `# noqa` so the debt stays
visible where it lives instead of loosening the limit for everyone.
`scripts/lint_ratchet.py` keeps that debt from growing: it re-runs ruff with
`--ignore-noqa`, counts the hidden findings per file and rule, and compares them
with `lint-baseline.json`. It also compares the config-level escape hatches
(`ignore`, `per-file-ignores`, `max-complexity`), so debt can't move from a
comment into `pyproject.toml` unnoticed.

It fails when a count goes up. A count that goes down passes, so a PR that only
removes suppressions doesn't touch `lint-baseline.json`, and several cleanup PRs
can be open at once without conflicting over it. (A PR that moves a still-suppressed
function to another file creates a new file/rule pair, which counts as an increase,
so that PR does update the baseline.)

The release locks the gains in. `bump-my-version` runs `--tighten` as a pre-commit
hook, which lowers the baseline to the code and adds it to the bump commit; it
refuses, and so aborts the bump, if anything went up. CI on a release tag runs
`--strict`, which also fails when the baseline is looser than the code, so a
release can't ship with the tightening skipped. Between releases, a suppression
that was removed can come back in the same file and rule without failing CI.

```bash
uv run python scripts/lint_ratchet.py             # check (CI, pre-commit)
uv run python scripts/lint_ratchet.py --strict    # check + baseline must be tight (release tags)
uv run python scripts/lint_ratchet.py --tighten   # lower the baseline (release bump)
uv run python scripts/lint_ratchet.py --update    # rewrite the baseline, increases included
```

Only run `--update` for an increase if review agreed the suppression is needed;
the baseline diff shows exactly what changed. If a bump aborts on the ratchet,
`git checkout .` restores the files it had already edited.

## Coverage

```bash
uv run pytest --cov
```

Settings live in `[tool.coverage.*]` in `pyproject.toml`. With branch coverage on,
`fail_under` applies to the combined line-and-branch percentage, not to branches
alone. Nothing enforces a ratchet automatically: raise `fail_under` by hand when
coverage goes up, and don't lower it.

## Property-Based Tests

`test_properties.py` uses [hypothesis](https://hypothesis.readthedocs.io/) to
check invariants over generated input. In CI (`CI` is set) the `ci` profile in
`conftest.py` derandomizes it, so the same code gets the same examples on every
run and a release won't fail on a newly drawn random counterexample. (A change to
the tests, the code or hypothesis itself can still change which examples run.) Locally it explores freely; if it finds a failure, it prints a
reproducible example to turn into a regression test.
