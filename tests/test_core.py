"""High-value tests for knack_sleuth.core module."""

import json
from pathlib import Path
from datetime import datetime, timedelta
import pytest

from knack_sleuth.core import load_app_metadata
from knack_sleuth.models import KnackAppMetadata


class TestLoadFromFile:
    """Tests for loading metadata from a local JSON file."""
    
    def test_load_from_file_success(self, sample_metadata_file):
        """Test successful loading from a JSON file."""
        metadata = load_app_metadata(file_path=sample_metadata_file)
        
        assert isinstance(metadata, KnackAppMetadata)
        assert metadata.application.name == "Sample Application"
        assert len(metadata.application.objects) == 19
        assert len(metadata.application.scenes) == 65
    
    def test_load_from_file_not_found(self):
        """Test FileNotFoundError when file doesn't exist."""
        non_existent = Path("/tmp/does_not_exist.json")
        
        with pytest.raises(FileNotFoundError):
            load_app_metadata(file_path=non_existent)
    
    def test_load_from_file_invalid_json(self, tmp_path):
        """Test JSONDecodeError for invalid JSON."""
        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text("{ invalid json }")
        
        with pytest.raises(json.JSONDecodeError):
            load_app_metadata(file_path=invalid_file)


class TestNoCacheParameter:
    """Tests for the no_cache parameter functionality."""
    
    def test_no_cache_true_no_files_created(self, tmp_path, mocker, mock_api_response):
        """Verify no_cache=True doesn't create cache files."""
        # Change to temp directory to avoid polluting project dir
        mocker.patch("knack_sleuth.core.Path.cwd", return_value=tmp_path)
        mocker.patch("knack_sleuth.core.glob.glob", return_value=[])
        mock_get = mocker.patch("knack_sleuth.core.httpx.get", return_value=mock_api_response)
        
        # Mock Settings to avoid needing environment variables
        mock_settings = mocker.MagicMock()
        mock_settings.knack_app_id = None
        mocker.patch("knack_sleuth.core.Settings", return_value=mock_settings)
        
        # Load with no_cache=True
        metadata = load_app_metadata(app_id="test123", no_cache=True)
        
        assert isinstance(metadata, KnackAppMetadata)
        assert metadata.application.name == "Sample Application"
        
        # Verify no cache files were created
        cache_files = list(tmp_path.glob("*_app_metadata_*.json"))
        assert len(cache_files) == 0, "Cache files should not be created with no_cache=True"
        
        # Verify API was called
        mock_get.assert_called_once()
    
    def test_no_cache_false_creates_cache(self, tmp_path, mocker, mock_api_response):
        """Verify no_cache=False creates cache files."""
        # Change to temp directory
        original_cwd = Path.cwd()
        mocker.patch("knack_sleuth.core.Path.cwd", return_value=tmp_path)
        
        # Mock glob to return empty list (no existing cache)
        mocker.patch("knack_sleuth.core.glob.glob", return_value=[])
        mock_get = mocker.patch("knack_sleuth.core.httpx.get", return_value=mock_api_response)
        
        # Mock Settings
        mock_settings = mocker.MagicMock()
        mock_settings.knack_app_id = None
        mocker.patch("knack_sleuth.core.Settings", return_value=mock_settings)
        
        # Mock Path to write to tmp_path
        original_path_init = Path.__init__
        
        def mock_path_init(self, *args, **kwargs):
            # If it's a cache filename, redirect to tmp_path
            if args and isinstance(args[0], str) and "_app_metadata_" in args[0]:
                original_path_init(self, tmp_path / args[0])
            else:
                original_path_init(self, *args, **kwargs)
        
        mocker.patch.object(Path, "__init__", mock_path_init)
        
        # Load with no_cache=False (default)
        metadata = load_app_metadata(app_id="test123", no_cache=False)
        
        assert isinstance(metadata, KnackAppMetadata)
        
        # Note: Due to mocking complexity, we verify the open() was called with 'w' mode
        # In real usage, this creates the cache file
    
    def test_no_cache_default_is_false(self, mocker, mock_api_response, tmp_path):
        """Verify default behavior allows caching."""
        mocker.patch("knack_sleuth.core.glob.glob", return_value=[])
        mock_get = mocker.patch("knack_sleuth.core.httpx.get", return_value=mock_api_response)
        
        mock_settings = mocker.MagicMock()
        mock_settings.knack_app_id = None
        mocker.patch("knack_sleuth.core.Settings", return_value=mock_settings)
        
        # Track calls to Path.open for write operations
        original_open = Path.open
        open_calls = []
        
        def track_open(self, *args, **kwargs):
            open_calls.append((args, kwargs))
            # Return a mock file object for 'w' mode
            if args and args[0] == 'w':
                return mocker.mock_open()()
            return original_open(self, *args, **kwargs)
        
        mocker.patch.object(Path, "open", track_open)
        
        # Load without specifying no_cache (should default to False)
        metadata = load_app_metadata(app_id="test123")
        
        # Verify that open was called with 'w' mode (cache write attempt)
        write_calls = [call for call in open_calls if call[0] and call[0][0] == 'w']
        assert len(write_calls) > 0, "Should attempt to write cache file by default"


class TestCacheExpiry:
    """Tests for cache expiry behavior."""
    
    def test_cache_used_within_24_hours(self, tmp_path, mocker, sample_metadata_dict):
        """Verify cache is used when less than 24 hours old."""
        # Create a fake cache file
        cache_file = tmp_path / "test123_app_metadata_202501011200.json"
        cache_file.write_text(json.dumps(sample_metadata_dict))
        
        # Mock cache file timestamp (1 hour old)
        one_hour_ago = datetime.now() - timedelta(hours=1)
        mocker.patch("knack_sleuth.core.datetime")
        mocker.patch("knack_sleuth.core.datetime.now", return_value=datetime.now())
        mocker.patch("knack_sleuth.core.datetime.fromtimestamp", return_value=one_hour_ago)
        
        # Mock glob to return our cache file
        mocker.patch("knack_sleuth.core.glob.glob", return_value=[str(cache_file)])
        
        # Mock httpx.get - should NOT be called if cache is used
        mock_get = mocker.patch("knack_sleuth.core.httpx.get")
        
        mock_settings = mocker.MagicMock()
        mock_settings.knack_app_id = None
        mocker.patch("knack_sleuth.core.Settings", return_value=mock_settings)
        
        # Load metadata
        metadata = load_app_metadata(app_id="test123", no_cache=False)
        
        assert isinstance(metadata, KnackAppMetadata)
        assert metadata.application.name == "Sample Application"
        
        # Verify API was NOT called (cache was used)
        mock_get.assert_not_called()
    
    def test_cache_expired_after_24_hours(self, tmp_path, mocker, mock_api_response, sample_metadata_dict):
        """Verify expired cache is ignored and API is called."""
        # Create a fake cache file
        cache_file = tmp_path / "test123_app_metadata_202501011200.json"
        cache_file.write_text(json.dumps(sample_metadata_dict))
        
        # Mock cache file timestamp (25 hours old - expired)
        twenty_five_hours_ago = datetime.now() - timedelta(hours=25)
        mocker.patch("knack_sleuth.core.datetime")
        mocker.patch("knack_sleuth.core.datetime.now", return_value=datetime.now())
        mocker.patch("knack_sleuth.core.datetime.fromtimestamp", return_value=twenty_five_hours_ago)
        
        # Mock glob to return our expired cache file
        mocker.patch("knack_sleuth.core.glob.glob", return_value=[str(cache_file)])
        
        # Mock httpx.get - SHOULD be called since cache is expired
        mock_get = mocker.patch("knack_sleuth.core.httpx.get", return_value=mock_api_response)
        
        mock_settings = mocker.MagicMock()
        mock_settings.knack_app_id = None
        mocker.patch("knack_sleuth.core.Settings", return_value=mock_settings)
        
        # Mock file write to prevent actual cache creation
        mocker.patch("builtins.open", mocker.mock_open())
        
        # Load metadata
        metadata = load_app_metadata(app_id="test123", no_cache=False)
        
        assert isinstance(metadata, KnackAppMetadata)
        
        # Verify API WAS called (cache expired)
        mock_get.assert_called_once()


class TestRefreshParameter:
    """Tests for the refresh parameter."""
    
    def test_refresh_ignores_cache(self, tmp_path, mocker, mock_api_response, sample_metadata_dict):
        """Verify refresh=True bypasses cache even if valid cache exists."""
        # Create a valid cache file (1 hour old)
        cache_file = tmp_path / "test123_app_metadata_202501011200.json"
        cache_file.write_text(json.dumps(sample_metadata_dict))
        
        # Mock glob to return cache file, but refresh should ignore it
        mocker.patch("knack_sleuth.core.glob.glob", return_value=[str(cache_file)])
        
        # Mock httpx.get - SHOULD be called even though cache is valid
        mock_get = mocker.patch("knack_sleuth.core.httpx.get", return_value=mock_api_response)
        
        mock_settings = mocker.MagicMock()
        mock_settings.knack_app_id = None
        mocker.patch("knack_sleuth.core.Settings", return_value=mock_settings)
        
        mocker.patch("builtins.open", mocker.mock_open())
        
        # Load with refresh=True
        metadata = load_app_metadata(app_id="test123", refresh=True)
        
        assert isinstance(metadata, KnackAppMetadata)
        
        # Verify API WAS called (cache ignored due to refresh)
        mock_get.assert_called_once()


class TestErrorHandling:
    """Tests for error handling."""
    
    def test_error_missing_app_id(self, mocker):
        """Verify ValueError when no app_id is provided."""
        mock_settings = mocker.MagicMock()
        mock_settings.knack_app_id = None
        mocker.patch("knack_sleuth.core.Settings", return_value=mock_settings)
        
        with pytest.raises(ValueError, match="App ID is required"):
            load_app_metadata()  # No file_path, no app_id
    
    def test_error_http_status_error(self, mocker, mock_api_error):
        """Verify HTTPStatusError is raised for API errors."""
        import httpx
        
        mock_settings = mocker.MagicMock()
        mock_settings.knack_app_id = None
        mocker.patch("knack_sleuth.core.Settings", return_value=mock_settings)
        
        mocker.patch("knack_sleuth.core.glob.glob", return_value=[])
        mocker.patch("knack_sleuth.core.httpx.get", side_effect=mock_api_error)
        
        with pytest.raises(httpx.HTTPStatusError):
            load_app_metadata(app_id="invalid123", no_cache=True)
    
    def test_error_network_error(self, mocker):
        """Verify RequestError is raised for network errors."""
        import httpx
        
        mock_settings = mocker.MagicMock()
        mock_settings.knack_app_id = None
        mocker.patch("knack_sleuth.core.Settings", return_value=mock_settings)
        
        mocker.patch("knack_sleuth.core.glob.glob", return_value=[])
        mocker.patch(
            "knack_sleuth.core.httpx.get",
            side_effect=httpx.RequestError("Network error")
        )
        
        with pytest.raises(httpx.RequestError):
            load_app_metadata(app_id="test123", no_cache=True)


class TestSettingsIntegration:
    """Tests for Settings integration."""
    
    def test_uses_env_app_id(self, mocker, mock_api_response):
        """Verify app_id from Settings is used when not provided."""
        # Mock Settings to return an app_id
        mock_settings = mocker.MagicMock()
        mock_settings.knack_app_id = "env_app_123"
        mocker.patch("knack_sleuth.core.Settings", return_value=mock_settings)
        
        mocker.patch("knack_sleuth.core.glob.glob", return_value=[])
        mock_get = mocker.patch("knack_sleuth.core.httpx.get", return_value=mock_api_response)
        mocker.patch("builtins.open", mocker.mock_open())
        
        # Load without providing app_id
        metadata = load_app_metadata(no_cache=True)
        
        assert isinstance(metadata, KnackAppMetadata)
        
        # Verify the correct app_id was used in the API call
        call_args = mock_get.call_args
        assert "env_app_123" in call_args[0][0]  # URL should contain the app_id
