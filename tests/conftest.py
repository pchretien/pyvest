"""Shared pytest fixtures for all test modules."""

import pytest


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    return {
        'account_id': 'test_account_id',
        'access_token': 'test_access_token',
        'harvest_url': 'https://api.harvestapp.com/v2/time_entries',
        'days_back': 90,
        'aws': {
            'access_key_id': 'test_access_key',
            'secret_access_key': 'test_secret_key',
            'region': 'us-east-1',
            'bucket_name': 'test-bucket'
        }
    }
