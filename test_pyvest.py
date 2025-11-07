"""
Unit tests for pyvest Lambda handler and Harvest processor.
Tests both handler without event and with S3 event scenarios.
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock, mock_open
from datetime import datetime, timedelta
import os
import sys

# Import the modules to test
from pyvest import lambda_handler
from harvest_processor import handle_no_event, load_config_from_file
from s3_event_handler import process_s3_event, handle_s3_event


class TestLambdaHandler:
    """Test cases for lambda_handler function."""

    @pytest.fixture
    def mock_context(self):
        """Create a mock Lambda context object."""
        context = Mock()
        context.function_name = "test-function"
        context.memory_limit_in_mb = 128
        context.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test-function"
        context.aws_request_id = "test-request-id"
        return context

    @pytest.fixture
    def mock_config(self):
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

    @pytest.fixture
    def mock_time_entries(self):
        """Create mock time entries data."""
        return [
            {
                'id': 1,
                'user': {'name': 'John Doe'},
                'client': {'name': 'Client A'},
                'project': {'name': 'Project 1'},
                'task': {'name': 'Development'},
                'hours': 8.0,
                'spent_date': '2024-01-15',
                'notes': 'Working on feature',
                'updated_at': '2024-01-15T10:00:00Z'
            },
            {
                'id': 2,
                'user': {'name': 'Jane Smith'},
                'client': {'name': 'Client B'},
                'project': {'name': 'Project 2'},
                'task': {'name': 'Design'},
                'hours': 6.0,
                'spent_date': '2024-01-15',
                'notes': 'Design review',
                'updated_at': '2024-01-15T11:00:00Z'
            }
        ]

    @patch.dict(os.environ, {}, clear=True)
    @patch('harvest_processor.load_config_from_file')
    @patch('harvest_processor.get_time_entries')
    @patch('harvest_processor.load_period_entries_from_s3')
    @patch('harvest_processor.identify_changes_and_save')
    @patch('harvest_processor.merge_entries')
    @patch('harvest_processor.save_period_entries_to_s3')
    def test_lambda_handler_no_event(
        self,
        mock_save_s3,
        mock_merge,
        mock_identify_changes,
        mock_load_s3,
        mock_get_entries,
        mock_load_config,
        mock_context,
        mock_config,
        mock_time_entries
    ):
        """Test lambda_handler without S3 event (normal invocation)."""
        # Setup mocks
        mock_load_config.return_value = mock_config
        mock_get_entries.return_value = mock_time_entries
        mock_load_s3.return_value = {}
        mock_identify_changes.return_value = ([], [], [])
        mock_merge.return_value = {1: mock_time_entries[0], 2: mock_time_entries[1]}
        mock_save_s3.return_value = True

        # Call the handler with empty event
        event = {}
        response = lambda_handler(event, mock_context)

        # Assertions
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['message'] == 'Harvest data export completed successfully'
        assert 'summary' in body
        
        # Verify functions were called
        mock_load_config.assert_called_once()
        mock_get_entries.assert_called_once()
        mock_load_s3.assert_called_once()
        mock_identify_changes.assert_called_once()
        mock_merge.assert_called_once()
        mock_save_s3.assert_called_once()

    @patch.dict(os.environ, {}, clear=True)
    @patch('s3_event_handler.handle_s3_event')
    @patch('s3_event_handler.process_s3_event')
    def test_lambda_handler_with_s3_event(
        self,
        mock_process_s3_event,
        mock_handle_s3_event,
        mock_context
    ):
        """Test lambda_handler with S3 event."""
        # Setup S3 event info
        s3_event_info = {
            'bucket': 'test-bucket',
            'key': 'changes/new/20240115-new-120000.json',
            'change_type': 'new',
            'event_name': 'ObjectCreated:Put',
            'event_time': '2024-01-15T12:00:00Z'
        }
        
        mock_process_s3_event.return_value = s3_event_info
        mock_handle_s3_event.return_value = s3_event_info

        # Create S3 event structure
        event = {
            'Records': [
                {
                    'eventSource': 'aws:s3',
                    'eventName': 'ObjectCreated:Put',
                    's3': {
                        'bucket': {'name': 'test-bucket'},
                        'object': {'key': 'changes/new/20240115-new-120000.json'}
                    },
                    'eventTime': '2024-01-15T12:00:00Z'
                }
            ]
        }

        # Call the handler
        response = lambda_handler(event, mock_context)

        # Assertions
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['message'] == 'S3 event processed successfully'
        assert body['s3_event'] == s3_event_info
        
        # Verify S3 event functions were called
        mock_process_s3_event.assert_called_once_with(event)
        mock_handle_s3_event.assert_called_once_with(s3_event_info)

    @patch.dict(os.environ, {}, clear=True)
    @patch('harvest_processor.load_config_from_file')
    def test_lambda_handler_value_error(
        self,
        mock_load_config,
        mock_context
    ):
        """Test lambda_handler with ValueError (missing config)."""
        # Setup mock to raise ValueError
        mock_load_config.side_effect = ValueError("Missing required configuration")

        # Call the handler
        event = {}
        response = lambda_handler(event, mock_context)

        # Assertions
        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert 'error' in body
        assert 'Missing required configuration' in body['error']

    @patch.dict(os.environ, {}, clear=True)
    @patch('harvest_processor.load_config_from_file')
    @patch('harvest_processor.get_time_entries')
    @patch('harvest_processor.load_period_entries_from_s3')
    def test_lambda_handler_general_exception(
        self,
        mock_load_s3,
        mock_get_entries,
        mock_load_config,
        mock_context,
        mock_config
    ):
        """Test lambda_handler with general exception."""
        # Setup mocks to raise exception
        mock_load_config.return_value = mock_config
        mock_load_s3.return_value = {}
        mock_get_entries.side_effect = Exception("Unexpected error")

        # Call the handler
        event = {}
        response = lambda_handler(event, mock_context)

        # Assertions
        assert response['statusCode'] == 500
        body = json.loads(response['body'])
        assert 'error' in body
        assert 'Unexpected error' in body['error']


class TestS3EventProcessing:
    """Test cases for S3 event processing functions."""

    def test_process_s3_event_valid(self):
        """Test process_s3_event with valid S3 event."""
        event = {
            'Records': [
                {
                    'eventSource': 'aws:s3',
                    'eventName': 'ObjectCreated:Put',
                    's3': {
                        'bucket': {'name': 'test-bucket'},
                        'object': {'key': 'changes/new/20240115-new-120000.json'}
                    },
                    'eventTime': '2024-01-15T12:00:00Z'
                }
            ]
        }

        result = process_s3_event(event)

        assert result is not None
        assert result['bucket'] == 'test-bucket'
        assert result['key'] == 'changes/new/20240115-new-120000.json'
        assert result['change_type'] == 'new'
        assert result['event_name'] == 'ObjectCreated:Put'

    def test_process_s3_event_deleted_type(self):
        """Test process_s3_event with deleted change type."""
        event = {
            'Records': [
                {
                    'eventSource': 'aws:s3',
                    'eventName': 'ObjectCreated:Put',
                    's3': {
                        'bucket': {'name': 'test-bucket'},
                        'object': {'key': 'changes/deleted/20240115-deleted-120000.json'}
                    },
                    'eventTime': '2024-01-15T12:00:00Z'
                }
            ]
        }

        result = process_s3_event(event)

        assert result is not None
        assert result['change_type'] == 'deleted'

    def test_process_s3_event_updated_type(self):
        """Test process_s3_event with updated change type."""
        event = {
            'Records': [
                {
                    'eventSource': 'aws:s3',
                    'eventName': 'ObjectCreated:Put',
                    's3': {
                        'bucket': {'name': 'test-bucket'},
                        'object': {'key': 'changes/updated/20240115-updated-120000.json'}
                    },
                    'eventTime': '2024-01-15T12:00:00Z'
                }
            ]
        }

        result = process_s3_event(event)

        assert result is not None
        assert result['change_type'] == 'updated'

    def test_process_s3_event_invalid_source(self):
        """Test process_s3_event with invalid event source."""
        event = {
            'Records': [
                {
                    'eventSource': 'aws:sqs',
                    'eventName': 'ObjectCreated:Put',
                    's3': {
                        'bucket': {'name': 'test-bucket'},
                        'object': {'key': 'changes/new/file.json'}
                    }
                }
            ]
        }

        result = process_s3_event(event)

        assert result is None

    def test_process_s3_event_invalid_name(self):
        """Test process_s3_event with invalid event name."""
        event = {
            'Records': [
                {
                    'eventSource': 'aws:s3',
                    'eventName': 'ObjectDeleted',
                    's3': {
                        'bucket': {'name': 'test-bucket'},
                        'object': {'key': 'changes/new/file.json'}
                    }
                }
            ]
        }

        result = process_s3_event(event)

        assert result is None

    def test_process_s3_event_no_records(self):
        """Test process_s3_event with no records."""
        event = {}

        result = process_s3_event(event)

        assert result is None

    def test_process_s3_event_empty_records(self):
        """Test process_s3_event with empty records."""
        event = {'Records': []}

        result = process_s3_event(event)

        assert result is None

    def test_process_s3_event_filename_based_detection(self):
        """Test process_s3_event detects change type from filename."""
        event = {
            'Records': [
                {
                    'eventSource': 'aws:s3',
                    'eventName': 'ObjectCreated:Put',
                    's3': {
                        'bucket': {'name': 'test-bucket'},
                        'object': {'key': '20240115-new-120000.json'}
                    },
                    'eventTime': '2024-01-15T12:00:00Z'
                }
            ]
        }

        result = process_s3_event(event)

        assert result is not None
        assert result['change_type'] == 'new'

    def test_handle_s3_event_valid(self):
        """Test handle_s3_event with valid event info."""
        s3_event_info = {
            'bucket': 'test-bucket',
            'key': 'changes/new/20240115-new-120000.json',
            'change_type': 'new',
            'event_name': 'ObjectCreated:Put',
            'event_time': '2024-01-15T12:00:00Z'
        }

        result = handle_s3_event(s3_event_info)

        assert result == s3_event_info

    def test_handle_s3_event_none(self):
        """Test handle_s3_event with None."""
        result = handle_s3_event(None)

        assert result is None


class TestHarvestProcessor:
    """Test cases for Harvest processor functions."""

    @pytest.fixture
    def mock_config(self):
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

    @patch.dict(os.environ, {}, clear=True)
    @patch('harvest_processor.load_config_from_file')
    @patch('harvest_processor.get_time_entries')
    @patch('harvest_processor.load_period_entries_from_s3')
    @patch('harvest_processor.identify_changes_and_save')
    @patch('harvest_processor.merge_entries')
    @patch('harvest_processor.save_period_entries_to_s3')
    def test_handle_no_event_success(
        self,
        mock_save_s3,
        mock_merge,
        mock_identify_changes,
        mock_load_s3,
        mock_get_entries,
        mock_load_config,
        mock_config
    ):
        """Test handle_no_event with successful execution."""
        # Setup mocks
        mock_load_config.return_value = mock_config
        mock_time_entries = [
            {
                'id': 1,
                'spent_date': '2024-01-15',
                'updated_at': '2024-01-15T10:00:00Z'
            }
        ]
        mock_get_entries.return_value = mock_time_entries
        mock_load_s3.return_value = {}
        mock_identify_changes.return_value = ([], [], [])
        mock_merged = {1: mock_time_entries[0]}
        mock_merge.return_value = mock_merged
        mock_save_s3.return_value = True

        # Call the function
        result = handle_no_event()

        # Assertions
        assert isinstance(result, dict)
        assert result['loaded'] == 0
        assert result['new'] == 1
        assert result['saved'] == 1
        assert result['success'] is True

        # Verify functions were called
        mock_load_config.assert_called_once()
        mock_get_entries.assert_called_once()
        mock_load_s3.assert_called_once()
        mock_identify_changes.assert_called_once()
        mock_merge.assert_called_once()
        mock_save_s3.assert_called_once()

    @patch.dict(os.environ, {}, clear=True)
    @patch('harvest_processor.load_config_from_file')
    def test_handle_no_event_missing_config(
        self,
        mock_load_config
    ):
        """Test handle_no_event with missing configuration."""
        # Setup mock to raise FileNotFoundError
        mock_load_config.side_effect = FileNotFoundError("config.json not found")

        # Call the function and expect exception
        with pytest.raises(FileNotFoundError):
            handle_no_event()

    @patch.dict(os.environ, {}, clear=True)
    @patch('harvest_processor.load_config_from_file')
    @patch('harvest_processor.get_time_entries')
    @patch('harvest_processor.load_period_entries_from_s3')
    def test_handle_no_event_api_error(
        self,
        mock_load_s3,
        mock_get_entries,
        mock_load_config,
        mock_config
    ):
        """Test handle_no_event with API error."""
        # Setup mocks
        mock_load_config.return_value = mock_config
        mock_load_s3.return_value = {}
        mock_get_entries.side_effect = RuntimeError("API request failed")

        # Call the function and expect exception
        with pytest.raises(RuntimeError):
            handle_no_event()


class TestConfigurationLoading:
    """Test cases for configuration loading."""

    @patch.dict(os.environ, {}, clear=True)
    def test_load_config_from_file_valid(self, tmp_path):
        """Test load_config_from_file with valid config file."""
        # Create a temporary config file
        config_file = tmp_path / "config.json"
        config_data = {
            'account_id': 'test_account_id',
            'access_token': 'test_access_token',
            'harvest_url': 'https://api.harvestapp.com/v2/time_entries',
            'days_back': 90,
            'aws': {
                'access_key_id': 'test_key',
                'secret_access_key': 'test_secret',
                'region': 'us-east-1',
                'bucket_name': 'test-bucket'
            }
        }
        config_file.write_text(json.dumps(config_data))

        # Load config
        config = load_config_from_file(str(config_file))

        # Assertions
        assert config['account_id'] == 'test_account_id'
        assert config['access_token'] == 'test_access_token'
        assert config['days_back'] == 90

    @patch.dict(os.environ, {}, clear=True)
    def test_load_config_from_file_not_found(self):
        """Test load_config_from_file with non-existent file."""
        with pytest.raises(FileNotFoundError):
            load_config_from_file('nonexistent_config.json')

    @patch.dict(os.environ, {}, clear=True)
    def test_load_config_from_file_invalid_json(self, tmp_path):
        """Test load_config_from_file with invalid JSON."""
        # Create a temporary config file with invalid JSON
        config_file = tmp_path / "config.json"
        config_file.write_text("invalid json content")

        # Load config and expect exception
        with pytest.raises(ValueError):
            load_config_from_file(str(config_file))

    @patch.dict(os.environ, {}, clear=True)
    def test_load_config_from_file_missing_required_fields(self, tmp_path):
        """Test load_config_from_file with missing required fields."""
        # Create a temporary config file with missing fields
        config_file = tmp_path / "config.json"
        config_data = {
            'account_id': 'test_account_id'
            # Missing access_token and harvest_url
        }
        config_file.write_text(json.dumps(config_data))

        # Load config and expect exception
        with pytest.raises(ValueError) as exc_info:
            load_config_from_file(str(config_file))
        
        assert 'account_id' in str(exc_info.value) or 'access_token' in str(exc_info.value)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

