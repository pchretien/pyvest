"""
Unit tests for pyvest Lambda handler and Harvest processor.
Tests both handler without event and with S3 event scenarios.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Add src directory to path to import modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))

from changes import identify_changes_and_save
from config import load_config_from_file
from harvest_processor import run_harvest_pipeline
from pyvest import lambda_handler
from s3 import load_period_entries_from_local, save_period_entries_to_local
from s3_event_handler import handle_s3_event, process_s3_event


class TestLambdaHandler:
    """Test cases for lambda_handler function."""

    @pytest.fixture
    def mock_context(self):
        context = Mock()
        context.function_name = "test-function"
        context.memory_limit_in_mb = 128
        context.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test-function"
        context.aws_request_id = "test-request-id"
        return context

    @pytest.fixture
    def mock_time_entries(self):
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
    @patch('config.load_config_from_file')
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
        """Handler without S3 event runs the full harvest pipeline."""
        mock_load_config.return_value = mock_config
        mock_get_entries.return_value = mock_time_entries
        mock_load_s3.return_value = {}
        mock_identify_changes.return_value = ([], [], [])
        mock_merge.return_value = {1: mock_time_entries[0], 2: mock_time_entries[1]}
        mock_save_s3.return_value = True

        response = lambda_handler({}, mock_context)

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['message'] == 'Harvest data export completed successfully'
        assert 'summary' in body
        mock_load_config.assert_called_once()
        mock_get_entries.assert_called_once()
        mock_load_s3.assert_called_once()
        mock_identify_changes.assert_called_once()
        mock_merge.assert_called_once()
        mock_save_s3.assert_called_once()

    @patch.dict(os.environ, {}, clear=True)
    @patch('pyvest.handle_s3_event')
    @patch('pyvest.process_s3_event')
    def test_lambda_handler_with_s3_event(
        self,
        mock_process_s3_event,
        mock_handle_s3_event,
        mock_context
    ):
        """Handler with S3 event routes to handle_s3_event."""
        s3_event_info = {
            'bucket': 'test-bucket',
            'key': 'changes/new/20240115-new-120000.json',
            'change_type': 'new',
            'event_name': 'ObjectCreated:Put',
            'event_time': '2024-01-15T12:00:00Z'
        }
        mock_process_s3_event.return_value = s3_event_info
        mock_handle_s3_event.return_value = s3_event_info

        event = {
            'Records': [{
                'eventSource': 'aws:s3',
                'eventName': 'ObjectCreated:Put',
                's3': {
                    'bucket': {'name': 'test-bucket'},
                    'object': {'key': 'changes/new/20240115-new-120000.json'}
                },
                'eventTime': '2024-01-15T12:00:00Z'
            }]
        }

        response = lambda_handler(event, mock_context)

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['message'] == 'S3 event processed successfully'
        assert body['s3_event'] == s3_event_info
        mock_process_s3_event.assert_called_once_with(event)
        mock_handle_s3_event.assert_called_once_with(s3_event_info)

    @patch.dict(os.environ, {}, clear=True)
    @patch('config.load_config_from_file')
    def test_lambda_handler_value_error(self, mock_load_config, mock_context):
        """Handler returns 400 on ValueError."""
        mock_load_config.side_effect = ValueError("Missing required configuration")

        response = lambda_handler({}, mock_context)

        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert 'Missing required configuration' in body['error']

    @patch.dict(os.environ, {}, clear=True)
    @patch('config.load_config_from_file')
    @patch('harvest_processor.get_time_entries')
    def test_lambda_handler_general_exception(
        self,
        mock_get_entries,
        mock_load_config,
        mock_context,
        mock_config
    ):
        """Handler returns 500 on unexpected exception."""
        mock_load_config.return_value = mock_config
        mock_get_entries.side_effect = Exception("Unexpected error")

        response = lambda_handler({}, mock_context)

        assert response['statusCode'] == 500
        body = json.loads(response['body'])
        assert 'Unexpected error' in body['error']


class TestS3EventProcessing:
    """Test cases for S3 event processing functions."""

    def test_process_s3_event_valid(self):
        """Valid S3 event returns parsed event info."""
        event = {
            'Records': [{
                'eventSource': 'aws:s3',
                'eventName': 'ObjectCreated:Put',
                's3': {
                    'bucket': {'name': 'test-bucket'},
                    'object': {'key': 'changes/new/20240115-new-120000.json'}
                },
                'eventTime': '2024-01-15T12:00:00Z'
            }]
        }

        result = process_s3_event(event)

        assert result is not None
        assert result['bucket'] == 'test-bucket'
        assert result['key'] == 'changes/new/20240115-new-120000.json'
        assert result['change_type'] == 'new'
        assert result['event_name'] == 'ObjectCreated:Put'

    @pytest.mark.parametrize("key,expected_type", [
        ('changes/deleted/20240115-deleted-120000.json', 'deleted'),
        ('changes/updated/20240115-updated-120000.json', 'updated'),
    ])
    def test_process_s3_event_change_types(self, key, expected_type):
        """change_type is correctly detected from the S3 object key path."""
        event = {
            'Records': [{
                'eventSource': 'aws:s3',
                'eventName': 'ObjectCreated:Put',
                's3': {
                    'bucket': {'name': 'test-bucket'},
                    'object': {'key': key}
                },
                'eventTime': '2024-01-15T12:00:00Z'
            }]
        }

        result = process_s3_event(event)

        assert result is not None
        assert result['change_type'] == expected_type

    def test_process_s3_event_invalid_source(self):
        """Non-S3 event source returns None."""
        event = {
            'Records': [{
                'eventSource': 'aws:sqs',
                'eventName': 'ObjectCreated:Put',
                's3': {'bucket': {'name': 'test-bucket'}, 'object': {'key': 'file.json'}}
            }]
        }
        assert process_s3_event(event) is None

    def test_process_s3_event_invalid_name(self):
        """Non-Put event name returns None."""
        event = {
            'Records': [{
                'eventSource': 'aws:s3',
                'eventName': 'ObjectDeleted',
                's3': {'bucket': {'name': 'test-bucket'}, 'object': {'key': 'file.json'}}
            }]
        }
        assert process_s3_event(event) is None

    def test_process_s3_event_no_records(self):
        """Empty event dict returns None."""
        assert process_s3_event({}) is None

    def test_process_s3_event_empty_records(self):
        """Event with empty Records list returns None."""
        assert process_s3_event({'Records': []}) is None

    def test_process_s3_event_filename_based_detection(self):
        """change_type is detected from filename when path has no subfolder."""
        event = {
            'Records': [{
                'eventSource': 'aws:s3',
                'eventName': 'ObjectCreated:Put',
                's3': {
                    'bucket': {'name': 'test-bucket'},
                    'object': {'key': '20240115-new-120000.json'}
                },
                'eventTime': '2024-01-15T12:00:00Z'
            }]
        }

        result = process_s3_event(event)

        assert result is not None
        assert result['change_type'] == 'new'

    def test_handle_s3_event_valid(self):
        """handle_s3_event returns the event info dict unchanged."""
        s3_event_info = {
            'bucket': 'test-bucket',
            'key': 'changes/new/20240115-new-120000.json',
            'change_type': 'new',
            'event_name': 'ObjectCreated:Put',
            'event_time': '2024-01-15T12:00:00Z'
        }
        assert handle_s3_event(s3_event_info) == s3_event_info

    def test_handle_s3_event_none(self):
        """handle_s3_event with None returns None."""
        assert handle_s3_event(None) is None


class TestHarvestPipeline:
    """Test cases for the Harvest export pipeline."""

    @patch.dict(os.environ, {}, clear=True)
    @patch('config.load_config_from_file')
    @patch('harvest_processor.get_time_entries')
    @patch('harvest_processor.load_period_entries_from_s3')
    @patch('harvest_processor.identify_changes_and_save')
    @patch('harvest_processor.merge_entries')
    @patch('harvest_processor.save_period_entries_to_s3')
    def test_run_harvest_pipeline_success(
        self,
        mock_save_s3,
        mock_merge,
        mock_identify_changes,
        mock_load_s3,
        mock_get_entries,
        mock_load_config,
        mock_config
    ):
        """Pipeline returns correct summary on successful S3 execution."""
        mock_load_config.return_value = mock_config
        mock_time_entries = [{'id': 1, 'spent_date': '2024-01-15', 'updated_at': '2024-01-15T10:00:00Z'}]
        mock_get_entries.return_value = mock_time_entries
        mock_load_s3.return_value = {}
        mock_identify_changes.return_value = ([], [], [])
        mock_merge.return_value = {1: mock_time_entries[0]}
        mock_save_s3.return_value = True

        result = run_harvest_pipeline()

        assert result == {'loaded': 0, 'new': 1, 'saved': 1, 'success': True}
        mock_load_s3.assert_called_once()
        mock_save_s3.assert_called_once()

    @patch.dict(os.environ, {}, clear=True)
    @patch('config.load_config_from_file')
    def test_run_harvest_pipeline_missing_config(self, mock_load_config):
        """FileNotFoundError from config loading propagates."""
        mock_load_config.side_effect = FileNotFoundError("config.json not found")

        with pytest.raises(FileNotFoundError):
            run_harvest_pipeline()

    @patch.dict(os.environ, {}, clear=True)
    @patch('config.load_config_from_file')
    @patch('harvest_processor.get_time_entries')
    def test_run_harvest_pipeline_api_error(self, mock_get_entries, mock_load_config, mock_config):
        """RuntimeError from the Harvest API propagates."""
        mock_load_config.return_value = mock_config
        mock_get_entries.side_effect = RuntimeError("API request failed")

        with pytest.raises(RuntimeError):
            run_harvest_pipeline()

    @patch.dict(os.environ, {}, clear=True)
    @patch('config.load_config_from_file')
    def test_run_harvest_pipeline_missing_aws_config(self, mock_load_config):
        """ValueError raised when AWS config is absent and local=False."""
        mock_load_config.return_value = {
            'account_id': 'test_account_id',
            'access_token': 'test_access_token',
            'harvest_url': 'https://api.harvestapp.com/v2/time_entries',
            'days_back': 90,
        }

        with pytest.raises(ValueError, match="AWS configuration is required"):
            run_harvest_pipeline()


class TestLocalFileIO:
    """Test cases for local file I/O functions (load/save to harvest_landing/)."""

    def test_load_from_local_file_not_found(self, tmp_path):
        """Returns empty dict when harvest-data.json does not exist."""
        result = load_period_entries_from_local(local_dir=str(tmp_path))
        assert result == {}

    def test_load_from_local_file_exists(self, tmp_path):
        """Loads entries from harvest-data.json and keys them by id."""
        entries = [
            {'id': 1, 'spent_date': '2024-01-15', 'hours': 8.0},
            {'id': 2, 'spent_date': '2024-01-15', 'hours': 6.0},
        ]
        (tmp_path / "harvest-data.json").write_text(json.dumps(entries))

        result = load_period_entries_from_local(local_dir=str(tmp_path))

        assert len(result) == 2
        assert result[1]['hours'] == 8.0
        assert result[2]['hours'] == 6.0

    def test_save_to_local_creates_directories(self, tmp_path):
        """Creates harvest_landing/ and daily/ directories."""
        local_dir = str(tmp_path / "harvest_landing")

        save_period_entries_to_local({1: {'id': 1, 'spent_date': '2024-01-15'}}, local_dir=local_dir)

        assert os.path.isdir(local_dir)
        assert os.path.isdir(os.path.join(local_dir, "daily"))

    def test_save_to_local_creates_files(self, tmp_path):
        """Creates harvest-data.json and one dated file in daily/."""
        local_dir = str(tmp_path / "harvest_landing")

        save_period_entries_to_local({1: {'id': 1, 'spent_date': '2024-01-15'}}, local_dir=local_dir)

        assert os.path.exists(os.path.join(local_dir, "harvest-data.json"))
        assert len(list(Path(local_dir, "daily").glob("*.json"))) == 1

    def test_save_and_load_round_trip(self, tmp_path):
        """Data saved with save_period_entries_to_local reloads correctly."""
        entries_dict = {
            1: {'id': 1, 'spent_date': '2024-01-15', 'hours': 8.0, 'notes': 'test'},
            2: {'id': 2, 'spent_date': '2024-01-16', 'hours': 4.0, 'notes': 'test2'},
        }
        local_dir = str(tmp_path / "harvest_landing")

        save_period_entries_to_local(entries_dict, local_dir=local_dir)
        loaded = load_period_entries_from_local(local_dir=local_dir)

        assert len(loaded) == 2
        assert loaded[1]['hours'] == 8.0
        assert loaded[2]['notes'] == 'test2'


class TestLocalPipeline:
    """Test cases for run_harvest_pipeline(local=True)."""

    @pytest.fixture
    def mock_config_no_aws(self):
        return {
            'account_id': 'test_account_id',
            'access_token': 'test_access_token',
            'harvest_url': 'https://api.harvestapp.com/v2/time_entries',
            'days_back': 90,
        }

    @patch.dict(os.environ, {}, clear=True)
    @patch('config.load_config_from_file')
    @patch('harvest_processor.get_time_entries')
    @patch('harvest_processor.load_period_entries_from_local')
    @patch('harvest_processor.identify_changes_and_save')
    @patch('harvest_processor.merge_entries')
    @patch('harvest_processor.save_period_entries_to_local')
    def test_run_harvest_pipeline_local_mode(
        self,
        mock_save_local,
        mock_merge,
        mock_identify_changes,
        mock_load_local,
        mock_get_entries,
        mock_load_config,
        mock_config
    ):
        """local=True uses local load/save functions and returns correct summary."""
        mock_load_config.return_value = mock_config
        mock_time_entries = [{'id': 1, 'spent_date': '2024-01-15', 'updated_at': '2024-01-15T10:00:00Z'}]
        mock_get_entries.return_value = mock_time_entries
        mock_load_local.return_value = {}
        mock_identify_changes.return_value = ([], [], [])
        mock_merge.return_value = {1: mock_time_entries[0]}
        mock_save_local.return_value = True

        result = run_harvest_pipeline(local=True)

        assert result == {'loaded': 0, 'new': 1, 'saved': 1, 'success': True}
        mock_load_local.assert_called_once()
        mock_save_local.assert_called_once()

    @patch.dict(os.environ, {}, clear=True)
    @patch('config.load_config_from_file')
    @patch('harvest_processor.get_time_entries')
    @patch('harvest_processor.load_period_entries_from_local')
    @patch('harvest_processor.identify_changes_and_save')
    @patch('harvest_processor.merge_entries')
    @patch('harvest_processor.save_period_entries_to_local')
    def test_run_harvest_pipeline_local_does_not_use_s3(
        self,
        mock_save_local,
        mock_merge,
        mock_identify_changes,
        mock_load_local,
        mock_get_entries,
        mock_load_config,
        mock_config
    ):
        """local=True never calls S3 load or save functions."""
        mock_load_config.return_value = mock_config
        mock_get_entries.return_value = []
        mock_load_local.return_value = {}
        mock_identify_changes.return_value = ([], [], [])
        mock_merge.return_value = {}
        mock_save_local.return_value = True

        with patch('harvest_processor.load_period_entries_from_s3') as mock_load_s3, \
             patch('harvest_processor.save_period_entries_to_s3') as mock_save_s3:
            run_harvest_pipeline(local=True)
            mock_load_s3.assert_not_called()
            mock_save_s3.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    @patch('config.load_config_from_file')
    @patch('harvest_processor.get_time_entries')
    @patch('harvest_processor.load_period_entries_from_local')
    @patch('harvest_processor.identify_changes_and_save')
    @patch('harvest_processor.merge_entries')
    @patch('harvest_processor.save_period_entries_to_local')
    def test_run_harvest_pipeline_local_no_aws_required(
        self,
        mock_save_local,
        mock_merge,
        mock_identify_changes,
        mock_load_local,
        mock_get_entries,
        mock_load_config,
        mock_config_no_aws
    ):
        """local=True does not raise when AWS config is absent."""
        mock_load_config.return_value = mock_config_no_aws
        mock_get_entries.return_value = []
        mock_load_local.return_value = {}
        mock_identify_changes.return_value = ([], [], [])
        mock_merge.return_value = {}
        mock_save_local.return_value = True

        result = run_harvest_pipeline(local=True)
        assert result['success'] is True

    @patch.dict(os.environ, {}, clear=True)
    @patch('config.load_config_from_file')
    @patch('harvest_processor.get_time_entries')
    @patch('harvest_processor.load_period_entries_from_local')
    @patch('harvest_processor.identify_changes_and_save')
    @patch('harvest_processor.merge_entries')
    @patch('harvest_processor.save_period_entries_to_local')
    def test_run_harvest_pipeline_local_passes_changes_folder(
        self,
        mock_save_local,
        mock_merge,
        mock_identify_changes,
        mock_load_local,
        mock_get_entries,
        mock_load_config,
        mock_config
    ):
        """local=True passes harvest_landing/changes as output_folder to identify_changes_and_save."""
        mock_load_config.return_value = mock_config
        mock_get_entries.return_value = []
        mock_load_local.return_value = {}
        mock_identify_changes.return_value = ([], [], [])
        mock_merge.return_value = {}
        mock_save_local.return_value = True

        run_harvest_pipeline(local=True)

        call_args = mock_identify_changes.call_args[0]
        assert call_args[4] == os.path.join("harvest_landing", "changes")


class TestChangesOutputFolder:
    """Test cases for identify_changes_and_save with a custom output_folder."""

    @patch.dict(os.environ, {}, clear=True)
    def test_new_entries_saved_to_custom_folder(self, tmp_path):
        """New entries are written to {output_folder}/new/."""
        output_folder = str(tmp_path / "custom_changes")

        identify_changes_and_save(
            {}, [{'id': 1, 'spent_date': '2024-01-15', 'hours': 8.0, 'updated_at': '2024-01-15T10:00:00Z'}],
            '2024-01-01', aws_config=None, output_folder=output_folder
        )

        assert len(list(Path(output_folder, "new").glob("*.json"))) == 1

    @patch.dict(os.environ, {}, clear=True)
    def test_no_s3_upload_without_aws_config(self, tmp_path):
        """No S3 upload when aws_config is None."""
        output_folder = str(tmp_path / "custom_changes")

        with patch('changes.upload_to_s3') as mock_upload:
            identify_changes_and_save(
                {}, [{'id': 1, 'spent_date': '2024-01-15', 'hours': 8.0, 'updated_at': '2024-01-15T10:00:00Z'}],
                '2024-01-01', aws_config=None, output_folder=output_folder
            )
            mock_upload.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    def test_change_file_content(self, tmp_path):
        """Change file contains the expected entries."""
        output_folder = str(tmp_path / "custom_changes")
        entry = {'id': 42, 'spent_date': '2024-01-15', 'hours': 5.0,
                 'updated_at': '2024-01-15T10:00:00Z', 'notes': 'test'}

        identify_changes_and_save({}, [entry], '2024-01-01',
                                  aws_config=None, output_folder=output_folder)

        new_files = list(Path(output_folder, "new").glob("*.json"))
        saved = json.loads(new_files[0].read_text())
        assert len(saved) == 1
        assert saved[0]['id'] == 42


class TestConfigurationLoading:
    """Test cases for configuration loading."""

    @patch.dict(os.environ, {}, clear=True)
    def test_load_config_from_file_valid(self, tmp_path):
        """Valid config file loads all fields correctly."""
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
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config_from_file(str(config_file))

        assert config['account_id'] == 'test_account_id'
        assert config['access_token'] == 'test_access_token'
        assert config['days_back'] == 90

    @patch.dict(os.environ, {}, clear=True)
    def test_load_config_from_file_not_found(self):
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_config_from_file('nonexistent_config.json')

    @patch.dict(os.environ, {}, clear=True)
    def test_load_config_from_file_invalid_json(self, tmp_path):
        """Malformed JSON raises ValueError."""
        config_file = tmp_path / "config.json"
        config_file.write_text("invalid json content")

        with pytest.raises(ValueError):
            load_config_from_file(str(config_file))

    @patch.dict(os.environ, {}, clear=True)
    def test_load_config_from_file_missing_required_fields(self, tmp_path):
        """Config missing required keys raises ValueError."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({'account_id': 'only_this'}))

        with pytest.raises(ValueError):
            load_config_from_file(str(config_file))


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
