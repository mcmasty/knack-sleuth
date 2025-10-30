"""Pytest configuration and shared fixtures."""

import json
from pathlib import Path
import pytest


@pytest.fixture
def sample_metadata_file():
    """Path to sample Knack metadata JSON file."""
    return Path("tests/data/sample_knack_app_meta.json")


@pytest.fixture
def sample_metadata_dict(sample_metadata_file):
    """Sample Knack metadata as a dictionary."""
    with sample_metadata_file.open() as f:
        return json.load(f)


@pytest.fixture
def mock_api_response(sample_metadata_dict):
    """Mock API response with sample metadata."""
    class MockResponse:
        status_code = 200
        
        def json(self):
            return sample_metadata_dict
        
        def raise_for_status(self):
            pass
    
    return MockResponse()


@pytest.fixture
def mock_api_error():
    """Mock API error response."""
    import httpx
    
    class MockResponse:
        status_code = 404
        text = "Application not found"
    
    def raise_error(*args, **kwargs):
        """Raise HTTPStatusError regardless of arguments."""
        response = MockResponse()
        raise httpx.HTTPStatusError(
            "404 Not Found",
            request=None,
            response=response
        )
    
    return raise_error
