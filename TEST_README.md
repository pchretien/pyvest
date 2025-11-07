# Unit Tests for pyVest

This directory contains unit tests for the pyVest Lambda handler and Harvest processor.

## Running Tests

### Prerequisites

Install test dependencies:
```bash
pip install -r requirements.txt
```

### Run All Tests

```bash
pytest test_pyvest.py -v
```

### Run Specific Test Classes

```bash
# Test Lambda handler
pytest test_pyvest.py::TestLambdaHandler -v

# Test S3 event processing
pytest test_pyvest.py::TestS3EventProcessing -v

# Test Harvest processor
pytest test_pyvest.py::TestHarvestProcessor -v

# Test configuration loading
pytest test_pyvest.py::TestConfigurationLoading -v
```

### Run Specific Tests

```bash
# Test handler without event
pytest test_pyvest.py::TestLambdaHandler::test_lambda_handler_no_event -v

# Test handler with S3 event
pytest test_pyvest.py::TestLambdaHandler::test_lambda_handler_with_s3_event -v
```

### Run Tests with Coverage

```bash
pip install pytest-cov
pytest test_pyvest.py --cov=harvest_processor --cov=pyvest --cov=s3_event_handler -v
```

## Test Structure

### TestLambdaHandler
Tests for the `lambda_handler` function:
- ✅ Handler without event (normal invocation)
- ✅ Handler with S3 event
- ✅ Handler with ValueError (missing config)
- ✅ Handler with general exception

### TestS3EventProcessing
Tests for S3 event processing functions:
- ✅ Valid S3 event processing
- ✅ Detection of change types (new, deleted, updated)
- ✅ Invalid event sources
- ✅ Invalid event names
- ✅ Missing or empty records
- ✅ Filename-based change type detection

### TestHarvestProcessor
Tests for the `handle_no_event` function:
- ✅ Successful execution
- ✅ Missing configuration
- ✅ API errors

### TestConfigurationLoading
Tests for configuration loading:
- ✅ Valid configuration file
- ✅ Missing configuration file
- ✅ Invalid JSON
- ✅ Missing required fields

## Mocking

All external dependencies are mocked:
- **Harvest API calls** - Mocked using `@patch('harvest_processor.get_time_entries')`
- **S3 operations** - Mocked using `@patch('harvest_processor.load_period_entries_from_s3')` and related functions
- **File operations** - Mocked using `@patch('harvest_processor.load_config_from_file')`
- **Environment variables** - Cleared using `@patch.dict(os.environ, {}, clear=True)`

## Notes

- Tests are designed to run locally without requiring actual AWS credentials or Harvest API access
- All external API calls and S3 operations are mocked
- Tests use pytest fixtures for reusable test data (mock_config, mock_time_entries, mock_context)
- The tests verify both successful execution and error handling scenarios

