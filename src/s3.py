"""S3 client creation and data transfer utilities."""

import json
import os
from datetime import datetime

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from config import S3_HARVEST_DATA_FILE, S3_DAILY_SUBFOLDER, DATE_FORMAT_FILENAME


def create_s3_client(aws_config):
    """Create a boto3 S3 client appropriate for the current runtime environment.

    In Lambda the IAM role credentials are used automatically; locally the
    explicit keys from aws_config are passed.

    Args:
        aws_config (dict): AWS configuration with region, access_key_id,
            and secret_access_key.

    Returns:
        boto3.client: Configured S3 client.
    """
    if os.getenv('AWS_LAMBDA_FUNCTION_NAME'):
        return boto3.client('s3', region_name=aws_config['region'])
    else:
        return boto3.client(
            's3',
            aws_access_key_id=aws_config.get('access_key_id'),
            aws_secret_access_key=aws_config.get('secret_access_key'),
            region_name=aws_config['region']
        )


def download_from_s3(s3_key, aws_config):
    """Download and parse a JSON file from S3.

    Args:
        s3_key (str): S3 object key to download.
        aws_config (dict): AWS configuration with bucket_name and credentials.

    Returns:
        list | dict: Parsed JSON content, or [] if the object does not exist
            or an error occurs.
    """
    try:
        s3_client = create_s3_client(aws_config)
        response = s3_client.get_object(Bucket=aws_config['bucket_name'], Key=s3_key)
        content = response['Body'].read().decode('utf-8')
        return json.loads(content)

    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            print(f"s3://{aws_config['bucket_name']}/{s3_key} does not exist, starting with empty dataset.")
            return []
        else:
            print(f"AWS S3 error during download: {e}")
            return []
    except NoCredentialsError:
        print("AWS credentials not found or invalid.")
        return []
    except Exception as e:
        print(f"Error downloading from S3: {e}")
        return []


def upload_to_s3(data, s3_key, aws_config, s3_client=None):
    """Serialise data as JSON and upload it to S3.

    Args:
        data (list | dict): Data to serialise and upload.
        s3_key (str): Destination S3 object key.
        aws_config (dict): AWS configuration with bucket_name and credentials.
        s3_client: Optional pre-created boto3 S3 client; one is created if omitted.

    Returns:
        bool: True on success, False on any error.
    """
    try:
        if s3_client is None:
            s3_client = create_s3_client(aws_config)
        json_data = json.dumps(data, indent=2, ensure_ascii=False)
        s3_client.put_object(
            Bucket=aws_config['bucket_name'],
            Key=s3_key,
            Body=json_data,
            ContentType='application/json'
        )
        return True

    except NoCredentialsError:
        print("AWS credentials not found or invalid.")
        return False
    except ClientError as e:
        print(f"AWS S3 error: {e}")
        return False
    except Exception as e:
        print(f"Error uploading to S3: {e}")
        return False


def load_period_entries_from_s3(aws_config):
    """Load existing time entries from S3 (harvest-data.json) as an ID-keyed dict.

    Args:
        aws_config (dict): AWS configuration with bucket_name, region, and credentials.

    Returns:
        dict: Mapping of entry ID to entry dict, or {} if unavailable.
    """
    if not aws_config:
        print("AWS configuration not found, cannot load from S3.")
        return {}

    entries = download_from_s3(S3_HARVEST_DATA_FILE, aws_config)

    if not entries:
        print(f"No entries loaded from S3 ({S3_HARVEST_DATA_FILE} is empty or does not exist)")
        return {}

    entries_dict = {entry['id']: entry for entry in entries}
    print(f"{len(entries_dict)} entries loaded from S3 ({S3_HARVEST_DATA_FILE})")
    return entries_dict


def save_period_entries_to_s3(entries_dict, aws_config):
    """Upload all entries to S3 as a dated daily file and as harvest-data.json.

    Args:
        entries_dict (dict): ID-keyed entries to persist.
        aws_config (dict): AWS configuration with bucket_name and region.

    Returns:
        bool: True if both uploads succeeded.
    """
    if not aws_config:
        print("AWS configuration not found, cannot save to S3.")
        return False

    # Sort by spent_date for consistent ordering in the stored file
    entries_list = sorted(entries_dict.values(), key=lambda x: x.get('spent_date', ''))

    today = datetime.now()
    json_filename = f"{today.strftime(DATE_FORMAT_FILENAME)}.json"
    s3_key = f"{S3_DAILY_SUBFOLDER}/{json_filename}"

    client = create_s3_client(aws_config)
    success = upload_to_s3(entries_list, s3_key, aws_config, s3_client=client)
    success_latest = upload_to_s3(entries_list, S3_HARVEST_DATA_FILE, aws_config, s3_client=client)

    if success and success_latest:
        print(f"✓ {len(entries_list)} entry/entries saved to S3 ({s3_key} and {S3_HARVEST_DATA_FILE})")

    return success and success_latest
