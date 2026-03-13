"""Pipeline orchestration: fetch, diff, merge, and persist Harvest time entries."""

from config import load_config_from_env
from harvest_client import get_time_entries
from s3 import load_period_entries_from_s3, save_period_entries_to_s3
from changes import identify_changes_and_save, merge_entries, calculate_date_range


def run_harvest_pipeline():
    """Run the full Harvest export pipeline: fetch, diff, merge, and save to S3.

    Returns:
        dict: Summary with keys loaded, new, saved, and success.

    Raises:
        ValueError: If AWS configuration is missing.
    """
    config = load_config_from_env()
    account_id = config['account_id']
    access_token = config['access_token']
    harvest_url = config['harvest_url']
    days_back = config['days_back']
    aws_config = config.get('aws')

    if not aws_config:
        raise ValueError("AWS configuration is required")

    from_date_display, to_date_display = calculate_date_range(days_back)

    time_entries = get_time_entries(account_id, access_token, harvest_url, from_date_display, to_date_display, days_back)

    period_entries = load_period_entries_from_s3(aws_config)

    # Diff against a copy so the original is unmodified when passed to merge
    identify_changes_and_save(period_entries.copy(), time_entries, from_date_display, aws_config)

    updated_period_entries = merge_entries(period_entries, time_entries, from_date_display)

    success = save_period_entries_to_s3(updated_period_entries, aws_config)

    return {
        'loaded': len(period_entries),
        'new': len(time_entries),
        'saved': len(updated_period_entries),
        'success': success
    }
