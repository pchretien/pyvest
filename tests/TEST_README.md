# Unit Tests for PyVest

This directory contains unit tests for the PyVest Lambda handler and Harvest processor.

## Running Tests

### Prerequisites

Install test dependencies:
```bash
pip install -r requirements-dev.txt
```

### Run All Tests

```bash
python3 -m pytest tests/ -v
```

### Run Specific Test Classes

```bash
python3 -m pytest tests/test_pyvest.py::TestLambdaHandler -v
python3 -m pytest tests/test_pyvest.py::TestS3EventProcessing -v
python3 -m pytest tests/test_pyvest.py::TestHarvestPipeline -v
python3 -m pytest tests/test_pyvest.py::TestLocalFileIO -v
python3 -m pytest tests/test_pyvest.py::TestLocalPipeline -v
python3 -m pytest tests/test_pyvest.py::TestChangesOutputFolder -v
python3 -m pytest tests/test_pyvest.py::TestConfigurationLoading -v
```

### Run with Coverage

```bash
python3 -m pytest tests/test_pyvest.py --cov=src -v
```

## Test Structure

### TestLambdaHandler
Tests for the `lambda_handler` entry point:
- ✅ Handler without event — runs full harvest pipeline via S3
- ✅ Handler with S3 ObjectCreated:Put event — routes to handle_s3_event
- ✅ ValueError (missing config) — returns 400
- ✅ Unexpected exception — returns 500

### TestS3EventProcessing
Tests for S3 event parsing (`process_s3_event`, `handle_s3_event`):
- ✅ Valid S3 event — returns parsed event info
- ✅ Change type detection: deleted and updated (parametrized)
- ✅ Invalid event source — returns None
- ✅ Invalid event name — returns None
- ✅ Missing or empty Records — returns None
- ✅ Filename-based change type detection (fallback)
- ✅ handle_s3_event with valid input — returns unchanged dict
- ✅ handle_s3_event with None — returns None

### TestHarvestPipeline
Tests for `run_harvest_pipeline()` (S3 / default mode):
- ✅ Successful execution — returns correct summary dict
- ✅ Missing config file — FileNotFoundError propagates
- ✅ Harvest API error — RuntimeError propagates
- ✅ Missing AWS config — raises ValueError

### TestLocalFileIO
Tests for local file I/O functions in `s3.py`:
- ✅ `load_period_entries_from_local` — returns `{}` when file does not exist
- ✅ `load_period_entries_from_local` — loads and keys entries by id
- ✅ `save_period_entries_to_local` — creates `harvest_landing/` and `daily/` directories
- ✅ `save_period_entries_to_local` — writes `harvest-data.json` and dated daily file
- ✅ Round-trip: save then load preserves data integrity

### TestLocalPipeline
Tests for `run_harvest_pipeline(local=True)`:
- ✅ Uses local load/save functions, returns correct summary
- ✅ Never calls S3 load or save functions
- ✅ Does not raise when AWS config is absent
- ✅ Passes `harvest_landing/changes` as output_folder to identify_changes_and_save

### TestChangesOutputFolder
Tests for `identify_changes_and_save(..., output_folder=...)`:
- ✅ New entries written to `{output_folder}/new/`
- ✅ No S3 upload when aws_config is None
- ✅ Change file contains the expected entries

### TestConfigurationLoading
Tests for `load_config_from_file()`:
- ✅ Valid config file loads all fields correctly
- ✅ Missing file — FileNotFoundError
- ✅ Malformed JSON — ValueError
- ✅ Missing required fields — ValueError

## Mocking Strategy

All external dependencies are mocked in unit tests:
- **Harvest API** — `@patch('harvest_processor.get_time_entries')`
- **S3 operations** — `@patch('harvest_processor.load_period_entries_from_s3')`, `save_period_entries_to_s3`
- **Local I/O** — `@patch('harvest_processor.load_period_entries_from_local')`, `save_period_entries_to_local`
- **Config loading** — `@patch('config.load_config_from_file')`
- **Environment variables** — `@patch.dict(os.environ, {}, clear=True)`

`TestLocalFileIO` and `TestChangesOutputFolder` use `tmp_path` (pytest built-in) to test actual file I/O against a temporary directory without mocking.

## Manual Testing

For interactive testing of the S3 handler with a real AWS S3 event payload:

```bash
python3 tests/test_s3_handler_manual.py
```

This script tests `process_s3_event()` and `handle_s3_event()` with a real AWS S3 event structure and does not require AWS credentials.

## Notes

- Tests run without AWS credentials or Harvest API access
- `TestLocalFileIO` and `TestChangesOutputFolder` write to `tmp_path` — no cleanup needed
- Running locally with `--local` flag uses `harvest_landing/` — see `src/pyvest.py`
