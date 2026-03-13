"""Configuration loading from environment variables or a local JSON file."""

import json
import os

# --- S3 paths ---
S3_HARVEST_DATA_FILE = "harvest-data.json"
S3_DAILY_SUBFOLDER = "daily"
S3_CHANGES_SUBFOLDER = "changes"

# --- Local paths ---
LOCAL_CHANGES_FOLDER = "changes"

# --- Date / time format strings ---
DATE_FORMAT_FILENAME = '%Y%m%d'
DATE_FORMAT_DISPLAY = '%Y-%m-%d'
TIME_FORMAT_FILENAME = '%H%M%S'

# --- Change-file naming patterns ---
CHANGES_FILE_PATTERNS = {
    'new': '-new-',
    'deleted': '-deleted-',
    'updated': '-updated-'
}

# --- API settings ---
HARVEST_API_MAX_PER_PAGE = 2000
DEFAULT_DAYS_BACK = 90

# --- Display settings ---
MAX_CHANGES_ENTRIES_DISPLAYED = 10


def load_config_from_env():
    """Load configuration from environment variables (Lambda) or a local config file.

    Returns:
        dict: Configuration with keys account_id, access_token, harvest_url,
            days_back, and aws.
    """
    if os.getenv('AWS_LAMBDA_FUNCTION_NAME'):
        config = {
            'account_id': os.getenv('HARVEST_ACCOUNT_ID'),
            'access_token': os.getenv('HARVEST_ACCESS_TOKEN'),
            'harvest_url': os.getenv('HARVEST_URL', 'https://api.harvestapp.com/v2/time_entries'),
            'days_back': int(os.getenv('DAYS_BACK', str(DEFAULT_DAYS_BACK))),
            'aws': {
                'region': os.getenv('AWS_REGION', os.getenv('AWS_DEFAULT_REGION', 'us-east-1')),
                'bucket_name': os.getenv('S3_BUCKET_NAME')
            }
        }

        if not config['account_id'] or not config['access_token']:
            raise ValueError("HARVEST_ACCOUNT_ID and HARVEST_ACCESS_TOKEN environment variables are required")
        if not config['aws']['bucket_name']:
            raise ValueError("S3_BUCKET_NAME environment variable is required")

        return config
    else:
        return load_config_from_file()


def load_config_from_file(config_file='config.json'):
    """Load configuration from a local JSON file.

    Args:
        config_file (str): Path to the JSON configuration file.

    Returns:
        dict: Parsed configuration.

    Raises:
        FileNotFoundError: If the file does not exist (includes a usage example).
        ValueError: If the file is not valid JSON or missing required keys.
    """
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)

        if 'account_id' not in config or 'access_token' not in config or 'harvest_url' not in config:
            raise ValueError("Config file must contain 'account_id', 'access_token', and 'harvest_url'")

        if 'days_back' not in config:
            config['days_back'] = DEFAULT_DAYS_BACK
            print(f"'days_back' not found in config, using default: {DEFAULT_DAYS_BACK} days")

        if 'aws' in config:
            aws_config = config['aws']
            required_aws_fields = ['access_key_id', 'secret_access_key', 'region', 'bucket_name']
            for field in required_aws_fields:
                if field not in aws_config:
                    print(f"Warning: Incomplete AWS configuration. Field '{field}' is missing.")

        return config
    except FileNotFoundError:
        sample_config = {
            'account_id': 'YOUR_ACCOUNT_ID',
            'access_token': 'YOUR_ACCESS_TOKEN',
            'harvest_url': 'https://api.harvestapp.com/v2/time_entries',
            'days_back': DEFAULT_DAYS_BACK,
            'aws': {
                'access_key_id': 'YOUR_ACCESS_KEY_ID',
                'secret_access_key': 'YOUR_SECRET_ACCESS_KEY',
                'region': 'us-east-1',
                'bucket_name': 'your-bucket-name'
            }
        }
        error_msg = (
            f"File {config_file} does not exist.\n"
            "Create a config.json file with the following format:\n"
            f"{json.dumps(sample_config, indent=2)}"
        )
        raise FileNotFoundError(error_msg)
    except json.JSONDecodeError as e:
        raise ValueError(f"File {config_file} is not valid JSON: {e}") from e
