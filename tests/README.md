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

To run tests in CI/CD:

```yaml
# GitHub Actions example
- name: Run tests
  run: |
    uv sync
    uv run pytest -v
```

## Coverage

To measure test coverage:

```bash
uv add --dev pytest-cov
uv run pytest --cov=knack_sleuth --cov-report=term-missing
```

Target: >80% coverage for core modules
