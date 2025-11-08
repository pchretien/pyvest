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
# From project root - pytest will automatically discover tests in the tests folder
python -m pytest -v

# Or explicitly specify the tests folder
python -m pytest tests/ -v

# Or specify the test file
python -m pytest tests/test_pyvest.py -v
```

### Run Specific Test Classes

```bash
# Test Lambda handler
python -m pytest tests/test_pyvest.py::TestLambdaHandler -v

# Test S3 event processing
python -m pytest tests/test_pyvest.py::TestS3EventProcessing -v

# Test Harvest processor
python -m pytest tests/test_pyvest.py::TestHarvestProcessor -v

# Test configuration loading
python -m pytest tests/test_pyvest.py::TestConfigurationLoading -v
```

### Run Specific Tests

```bash
# Test handler without event
python -m pytest tests/test_pyvest.py::TestLambdaHandler::test_lambda_handler_no_event -v

# Test handler with S3 event
python -m pytest tests/test_pyvest.py::TestLambdaHandler::test_lambda_handler_with_s3_event -v
```

### Run Tests with Coverage

```bash
pip install pytest-cov
python -m pytest tests/test_pyvest.py --cov=harvest_processor --cov=pyvest --cov=s3_event_handler -v
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

## Manual Testing

### Testing S3 Handler Manually

For interactive testing of the S3 handler, use the manual test script:

```bash
# From project root
python tests/test_s3_handler_manual.py

# Or from the tests directory
cd tests
python test_s3_handler_manual.py
```

This script demonstrates:
- Testing `process_s3_event()` with various event types
- Testing `handle_s3_event()` with different inputs
- Testing `lambda_handler()` with S3 events
- All change types (new, deleted, updated)
- Path-based and filename-based detection
- Invalid event handling

### Testing with Sample S3 Events

You can also test the S3 handler directly in Python:

```python
from s3_event_handler import process_s3_event, handle_s3_event

# Create a sample S3 event
event = {
    'Records': [{
        'eventSource': 'aws:s3',
        'eventName': 'ObjectCreated:Put',
        's3': {
            'bucket': {'name': 'my-bucket'},
            'object': {'key': 'changes/new/20240115-new-120000.json'}
        },
        'eventTime': '2024-01-15T12:00:00Z'
    }]
}

# Process the event
s3_info = process_s3_event(event)
print(s3_info)

# Handle the processed event
result = handle_s3_event(s3_info)
print(result)
```

### Testing Lambda Handler with S3 Events

```python
from pyvest import lambda_handler

class MockContext:
    def __init__(self):
        self.function_name = "test-function"
        self.aws_request_id = "test-request-id"

# Test with S3 event
s3_event = {
    'Records': [{
        'eventSource': 'aws:s3',
        'eventName': 'ObjectCreated:Put',
        's3': {
            'bucket': {'name': 'my-bucket'},
            'object': {'key': 'changes/new/file.json'}
        }
    }]
}

context = MockContext()
response = lambda_handler(s3_event, context)
print(response)
```

## Notes

- Tests are designed to run locally without requiring actual AWS credentials or Harvest API access
- All external API calls and S3 operations are mocked
- Tests use python -m pytest fixtures for reusable test data (mock_config, mock_time_entries, mock_context)
- The tests verify both successful execution and error handling scenarios
- Manual testing scripts can be used for interactive debugging and validation

