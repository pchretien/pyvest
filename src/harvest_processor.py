"""Pipeline orchestration: fetch, diff, merge, and persist Harvest time entries."""

import os

from config import load_config_from_env, LOCAL_LANDING_FOLDER, LOCAL_CHANGES_FOLDER
from harvest_client import get_time_entries
from s3 import (load_period_entries_from_s3, save_period_entries_to_s3,
                load_period_entries_from_local, save_period_entries_to_local)
from changes import identify_changes_and_save, merge_entries, calculate_date_range


def run_harvest_pipeline(local=False):
    """Run the full Harvest export pipeline: fetch, diff, merge, and persist entries.

    Uses local files under harvest_landing/ when running outside Lambda,
    and S3 when running inside Lambda.

    Returns:
        dict: Summary with keys loaded, new, saved, and success.

    Raises:
        ValueError: If AWS configuration is missing when running in Lambda.
    """
    config = load_config_from_env()
    account_id = config['account_id']
    access_token = config['access_token']
    harvest_url = config['harvest_url']
    days_back = config['days_back']

    is_lambda = bool(os.getenv('AWS_LAMBDA_FUNCTION_NAME'))
    use_local = local and not is_lambda
    aws_config = config.get('aws') if not use_local else None

    if not use_local and not aws_config:
        raise ValueError("AWS configuration is required")

    from_date_display, to_date_display = calculate_date_range(days_back)

    time_entries = get_time_entries(account_id, access_token, harvest_url, from_date_display, to_date_display, days_back)

    if use_local:
        period_entries = load_period_entries_from_local()
    else:
        period_entries = load_period_entries_from_s3(aws_config)

    changes_folder = os.path.join(LOCAL_LANDING_FOLDER, LOCAL_CHANGES_FOLDER) if use_local else None

    # Diff against a copy so the original is unmodified when passed to merge
    identify_changes_and_save(period_entries.copy(), time_entries, from_date_display, aws_config, changes_folder)

    updated_period_entries = merge_entries(period_entries, time_entries, from_date_display)

    if use_local:
        success = save_period_entries_to_local(updated_period_entries)
    else:
        success = save_period_entries_to_s3(updated_period_entries, aws_config)

    return {
        'loaded': len(period_entries),
        'new': len(time_entries),
        'saved': len(updated_period_entries),
        'success': success
    }
