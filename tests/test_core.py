"""High-value tests for knack_sleuth.core module."""

import json
import os
import time
from pathlib import Path

import pytest

from knack_sleuth.core import get_cache_dir, load_app_metadata
from knack_sleuth.models import KnackAppMetadata


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Isolated cache directory for each test."""
    monkeypatch.setenv("KNACK_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("KNACK_APP_ID", raising=False)
    monkeypatch.delenv("KNACK_CACHE_TTL_HOURS", raising=False)
    return tmp_path


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


class TestCacheDirectory:
    """Tests for cache directory resolution."""

    def test_env_override(self, cache_dir):
        assert get_cache_dir() == cache_dir

    def test_xdg_default(self, monkeypatch, tmp_path):
        monkeypatch.delenv("KNACK_CACHE_DIR", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))

        resolved = get_cache_dir()
        assert resolved == tmp_path / "xdg" / "knack-sleuth"
        assert resolved.is_dir()  # created on demand


class TestNoCacheParameter:
    """Tests for the no_cache parameter functionality."""

    def test_no_cache_true_no_files_created(self, cache_dir, mocker, mock_api_response):
        """Verify no_cache=True doesn't create cache files."""
        mock_get = mocker.patch(
            "knack_sleuth.core.httpx.get", return_value=mock_api_response
        )

        metadata = load_app_metadata(app_id="test123", no_cache=True)

        assert isinstance(metadata, KnackAppMetadata)
        assert metadata.application.name == "Sample Application"
        assert list(cache_dir.glob("*_app_metadata_*.json")) == []
        mock_get.assert_called_once()

    def test_default_creates_cache_file(self, cache_dir, mocker, mock_api_response):
        """Verify the default behavior writes a cache file to the cache dir."""
        mocker.patch("knack_sleuth.core.httpx.get", return_value=mock_api_response)

        metadata = load_app_metadata(app_id="test123")

        assert isinstance(metadata, KnackAppMetadata)
        files = list(cache_dir.glob("test123_app_metadata_*.json"))
        assert len(files) == 1
        cached = json.loads(files[0].read_text())
        assert cached["application"]["name"] == "Sample Application"


class TestCacheExpiry:
    """Tests for cache expiry behavior."""

    def _write_cache_file(self, cache_dir, sample_metadata_dict, age_hours=0.0):
        cache_file = cache_dir / "test123_app_metadata_202501011200.json"
        cache_file.write_text(json.dumps(sample_metadata_dict))
        if age_hours:
            old = time.time() - age_hours * 3600
            os.utime(cache_file, (old, old))
        return cache_file

    def test_cache_used_within_ttl(self, cache_dir, mocker, sample_metadata_dict):
        """A fresh cache file is used and the API is not called."""
        self._write_cache_file(cache_dir, sample_metadata_dict, age_hours=1)
        mock_get = mocker.patch("knack_sleuth.core.httpx.get")

        metadata = load_app_metadata(app_id="test123")

        assert metadata.application.name == "Sample Application"
        mock_get.assert_not_called()

    def test_cache_expired_after_ttl(
        self, cache_dir, mocker, mock_api_response, sample_metadata_dict
    ):
        """An expired cache file is ignored and the API is called."""
        self._write_cache_file(cache_dir, sample_metadata_dict, age_hours=25)
        mock_get = mocker.patch(
            "knack_sleuth.core.httpx.get", return_value=mock_api_response
        )

        metadata = load_app_metadata(app_id="test123")

        assert isinstance(metadata, KnackAppMetadata)
        mock_get.assert_called_once()

    def test_ttl_configurable_via_env(
        self, cache_dir, monkeypatch, mocker, mock_api_response, sample_metadata_dict
    ):
        """KNACK_CACHE_TTL_HOURS shortens the freshness window."""
        monkeypatch.setenv("KNACK_CACHE_TTL_HOURS", "1")
        self._write_cache_file(cache_dir, sample_metadata_dict, age_hours=2)
        mock_get = mocker.patch(
            "knack_sleuth.core.httpx.get", return_value=mock_api_response
        )

        load_app_metadata(app_id="test123")

        # 2h-old cache is stale under a 1h TTL
        mock_get.assert_called_once()

    def test_corrupt_cache_falls_back_to_api(self, cache_dir, mocker, mock_api_response):
        """An unreadable cache file falls through to a fresh API fetch."""
        (cache_dir / "test123_app_metadata_202501011200.json").write_text("{ not json")
        mock_get = mocker.patch(
            "knack_sleuth.core.httpx.get", return_value=mock_api_response
        )

        metadata = load_app_metadata(app_id="test123")

        assert isinstance(metadata, KnackAppMetadata)
        mock_get.assert_called_once()


class TestRefreshParameter:
    """Tests for the refresh parameter."""

    def test_refresh_ignores_cache(
        self, cache_dir, mocker, mock_api_response, sample_metadata_dict
    ):
        """Verify refresh=True bypasses cache even if a fresh cache exists."""
        cache_file = cache_dir / "test123_app_metadata_202501011200.json"
        cache_file.write_text(json.dumps(sample_metadata_dict))
        mock_get = mocker.patch(
            "knack_sleuth.core.httpx.get", return_value=mock_api_response
        )

        metadata = load_app_metadata(app_id="test123", refresh=True)

        assert isinstance(metadata, KnackAppMetadata)
        mock_get.assert_called_once()


class TestErrorHandling:
    """Tests for error handling."""

    def test_error_missing_app_id(self, cache_dir):
        """Verify ValueError when no app_id is provided."""
        with pytest.raises(ValueError, match="App ID is required"):
            load_app_metadata()  # No file_path, no app_id

    def test_error_http_status_error(self, cache_dir, mocker, mock_api_error):
        """Verify HTTPStatusError is raised for API errors."""
        import httpx

        mocker.patch("knack_sleuth.core.httpx.get", side_effect=mock_api_error)

        with pytest.raises(httpx.HTTPStatusError):
            load_app_metadata(app_id="invalid123", no_cache=True)

    def test_error_network_error(self, cache_dir, mocker):
        """Verify RequestError is raised for network errors."""
        import httpx

        mocker.patch(
            "knack_sleuth.core.httpx.get",
            side_effect=httpx.RequestError("Network error"),
        )

        with pytest.raises(httpx.RequestError):
            load_app_metadata(app_id="test123", no_cache=True)


class TestSettingsIntegration:
    """Tests for Settings integration."""

    def test_uses_env_app_id(self, cache_dir, monkeypatch, mocker, mock_api_response):
        """Verify app_id from the environment is used when not provided."""
        monkeypatch.setenv("KNACK_APP_ID", "env_app_123")
        mock_get = mocker.patch(
            "knack_sleuth.core.httpx.get", return_value=mock_api_response
        )

        metadata = load_app_metadata(no_cache=True)

        assert isinstance(metadata, KnackAppMetadata)
        call_args = mock_get.call_args
        assert "env_app_123" in call_args[0][0]  # URL should contain the app_id


class TestKnackFieldFormatCoercion:
    """Knack emits `"format": ""` instead of omitting the key (issue: empty-string format)."""

    def test_empty_string_format_coerced_to_none(self):
        """An empty-string format must not fail validation."""
        from knack_sleuth.models import KnackField

        field = KnackField(key="field_1", name="Name", type="short_text", format="")

        assert field.format is None

    def test_dict_format_still_parsed(self):
        """A real format object is unaffected by the coercion."""
        from knack_sleuth.models import KnackField

        field = KnackField(
            key="field_2", name="Amount", type="currency", format={"format": "£"}
        )

        assert field.format is not None
        assert field.format.model_dump()["format"] == "£"

    def test_omitted_format_still_none(self):
        """Omitting format entirely keeps the existing default."""
        from knack_sleuth.models import KnackField

        field = KnackField(key="field_3", name="Plain", type="short_text")

        assert field.format is None


class TestBuilderUrl:
    """Builder URL grammar is {account_slug}/{app_slug}/pages/{scene_key}."""

    @staticmethod
    def _app(account_slug="acme", app_slug="portal"):
        from knack_sleuth.models import KnackAppMetadata

        return KnackAppMetadata(
            application={
                "id": "app_1",
                "name": "Test",
                "slug": app_slug,
                "home_scene": {"key": "scene_1", "slug": "home"},
                "account": {"slug": account_slug},
            }
        ).application

    def test_page_url_uses_the_application_slug(self):
        """Regression: the app slug was hardcoded to 'portal', which was only
        ever right for the one app whose slug happened to be 'portal'."""
        from knack_sleuth.core import builder_url

        url = builder_url(self._app(app_slug="sample-application"), "scene_5")

        assert url == "https://builder.knack.com/acme/sample-application/pages/scene_5"

    def test_view_url_appends_view_key_and_type(self):
        from knack_sleuth.core import builder_url

        url = builder_url(self._app(), "scene_5", view_key="view_9", view_type="form")

        assert url == "https://builder.knack.com/acme/portal/pages/scene_5/views/view_9/form"

    def test_next_gen_builder_uses_its_own_host(self):
        from knack_sleuth.core import builder_url

        url = builder_url(self._app(), "scene_5", next_gen=True)

        assert url.startswith("https://builder-next.knack.com/acme/portal/")

    def test_account_slug_falls_back_to_application_slug(self):
        from knack_sleuth.core import builder_url

        app = self._app()
        app.account = {}

        assert builder_url(app, "scene_5") == "https://builder.knack.com/portal/portal/pages/scene_5"
