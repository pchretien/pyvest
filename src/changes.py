"""Diff, merge, format, and persist Harvest time entry change sets."""

import json
import os
from datetime import datetime, timedelta

from config import (
    DATE_FORMAT_FILENAME, DATE_FORMAT_DISPLAY, TIME_FORMAT_FILENAME,
    CHANGES_FILE_PATTERNS, S3_CHANGES_SUBFOLDER, LOCAL_CHANGES_FOLDER,
    MAX_CHANGES_ENTRIES_DISPLAYED
)
from s3 import upload_to_s3


def calculate_cutoff_date(start_date, days_offset=1):
    """Return start_date minus days_offset as a YYYY-MM-DD string.

    Args:
        start_date (str): Reference date in YYYY-MM-DD format.
        days_offset (int): Number of days to subtract.

    Returns:
        str: Resulting date in YYYY-MM-DD format.
    """
    return (datetime.strptime(start_date, DATE_FORMAT_DISPLAY) -
            timedelta(days=days_offset)).strftime(DATE_FORMAT_DISPLAY)


def get_current_datetime_strings():
    """Return the current date and time formatted for use in filenames.

    Returns:
        tuple[str, str]: (date_str, time_str) as (YYYYMMDD, HHMMSS).
    """
    now = datetime.now()
    return (
        now.strftime(DATE_FORMAT_FILENAME),
        now.strftime(TIME_FORMAT_FILENAME)
    )


def calculate_date_range(days_back):
    """Compute a (from_date, to_date) range ending today.

    Args:
        days_back (int): Number of days to look back from today.

    Returns:
        tuple[str, str]: (from_date, to_date) in YYYY-MM-DD format.
    """
    today = datetime.now()
    from_date = (today - timedelta(days=days_back)).strftime(DATE_FORMAT_DISPLAY)
    to_date = today.strftime(DATE_FORMAT_DISPLAY)
    return from_date, to_date


def safe_get_nested(data, *keys, default='N/A'):
    """Safely traverse a nested dict and return a value or a default.

    Args:
        data (dict): The root data structure to traverse.
        *keys: Sequence of keys to follow into nested dicts.
        default: Value returned when any key is missing or None.

    Returns:
        The value found at the key path, or default.
    """
    value = data
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
            if value is None:
                return default
        else:
            return default
    return value if value is not None else default


def format_time_entry(entry):
    """Format a time entry dict as a human-readable string.

    Args:
        entry (dict): A Harvest time entry.

    Returns:
        str: Formatted line with user, client, project, task, hours, date, and notes.
    """
    user_name = safe_get_nested(entry, 'user', 'name')
    client_name = safe_get_nested(entry, 'client', 'name')
    project_name = safe_get_nested(entry, 'project', 'name')
    task_name = safe_get_nested(entry, 'task', 'name')
    hours = entry.get('hours', 'N/A')
    spent_date = entry.get('spent_date', 'N/A')
    notes = entry.get('notes', '') or '(empty)'

    return (f"  User: {user_name}, Client: {client_name}, Project: {project_name}, "
            f"Task: {task_name}, Hours: {hours}, Date: {spent_date}, Notes: {notes}")


def get_newest_entries(entries, limit=MAX_CHANGES_ENTRIES_DISPLAYED):
    """Return up to limit entries sorted by updated_at descending.

    Args:
        entries (list): List of time entry dicts.
        limit (int): Maximum number of entries to return.

    Returns:
        list: The most recently updated entries.
    """
    sorted_entries = sorted(
        entries,
        key=lambda x: x.get('updated_at', '') or '',
        reverse=True
    )
    return sorted_entries[:limit]


def print_changes_summary(entries_list, label, max_display=MAX_CHANGES_ENTRIES_DISPLAYED):
    """Print a labelled count and the most recent entries in a change list.

    Args:
        entries_list (list): Entries to summarise.
        label (str): Label prefix for the count line.
        max_display (int): Maximum number of individual entries to print.
    """
    print(f"{label}: {len(entries_list)}")
    if entries_list:
        newest = get_newest_entries(entries_list, max_display)
        for entry in newest:
            print(format_time_entry(entry))
        if len(entries_list) > max_display:
            print(f"  ... and {len(entries_list) - max_display} more entry/entries not displayed")


def identify_new_entries(existing_ids, new_entries_dict):
    """Return entries that are present in new_entries_dict but not in existing_ids.

    Args:
        existing_ids (set): IDs of the previously persisted entries.
        new_entries_dict (dict): ID-keyed dict of entries from the latest API fetch.

    Returns:
        list: Entries that did not exist before.
    """
    return [entry for entry_id, entry in new_entries_dict.items()
            if entry_id not in existing_ids]


def identify_deleted_entries(existing_ids, new_entry_ids, existing_entries, start_date):
    """Return entries that were deleted in Harvest within the observed date range.

    Only entries whose spent_date >= start_date are considered, to avoid
    flagging old entries that were simply outside the current fetch window.

    Args:
        existing_ids (set): IDs that were persisted before this run.
        new_entry_ids (set): IDs returned by the latest API fetch.
        existing_entries (dict): Previously persisted ID-keyed entries.
        start_date (str): Lower bound date in YYYY-MM-DD format.

    Returns:
        list: Entries present before but absent from the latest fetch.
    """
    deleted = []
    for entry_id in existing_ids - new_entry_ids:
        entry = existing_entries[entry_id]
        spent_date = entry.get('spent_date', '')
        if spent_date and spent_date >= start_date:
            deleted.append(entry)
    return deleted


def identify_updated_entries(existing_ids, new_entry_ids, existing_entries, new_entries_dict):
    """Return entries that exist in both sets but whose updated_at timestamp changed.

    Args:
        existing_ids (set): IDs that were persisted before this run.
        new_entry_ids (set): IDs returned by the latest API fetch.
        existing_entries (dict): Previously persisted ID-keyed entries.
        new_entries_dict (dict): ID-keyed dict of entries from the latest API fetch.

    Returns:
        list: New versions of entries whose updated_at differs from the stored version.
    """
    updated = []
    for entry_id in existing_ids & new_entry_ids:
        existing_entry = existing_entries[entry_id]
        new_entry = new_entries_dict[entry_id]

        if existing_entry.get('updated_at', '') != new_entry.get('updated_at', ''):
            updated.append(new_entry)
    return updated


def save_changes_file(entries_list, change_type, date_str, time_str, is_local, aws_config, output_folder=None):
    """Write a list of changed entries to disk and/or S3.

    The file is placed under a subfolder named after change_type (new, deleted,
    updated). At least one destination (local or S3) must be active for the
    function to return True.

    Args:
        entries_list (list): Entries to save; nothing is written if this is empty.
        change_type (str): One of 'new', 'deleted', or 'updated'.
        date_str (str): Current date as YYYYMMDD.
        time_str (str): Current time as HHMMSS.
        is_local (bool): True when running outside Lambda.
        aws_config (dict | None): AWS configuration, or None to skip S3 upload.
        output_folder (str | None): Base local folder for change files.

    Returns:
        bool: True if at least one save succeeded, False otherwise.
    """
    if not entries_list:
        return False

    filename = f"{date_str}{CHANGES_FILE_PATTERNS[change_type]}{time_str}.json"
    success = False

    # The subfolder name mirrors the change type (e.g. changes/new/)
    change_subfolder = change_type

    if is_local and output_folder:
        subfolder_path = os.path.join(output_folder, change_subfolder)
        os.makedirs(subfolder_path, exist_ok=True)
        filepath = os.path.join(subfolder_path, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(entries_list, f, indent=2, ensure_ascii=False)
        print(f"✓ File saved: {filepath} ({len(entries_list)} entries)")
        success = True

    if aws_config:
        s3_key = f"{S3_CHANGES_SUBFOLDER}/{change_subfolder}/{filename}"
        if upload_to_s3(entries_list, s3_key, aws_config):
            print(f"✓ File uploaded to S3: s3://{aws_config['bucket_name']}/{s3_key}")
            success = True

    return success


def compute_changes(existing_entries, new_entries, start_date):
    """Return the diff between stored and fetched entries without any I/O.

    Args:
        existing_entries (dict): Previously persisted ID-keyed entries.
        new_entries (list): Entries returned by the latest API fetch.
        start_date (str): Fetch window start date in YYYY-MM-DD format.

    Returns:
        tuple[list, list, list]: (new_entries_list, deleted_entries_list, updated_entries_list)
    """
    new_entries_dict = {entry['id']: entry for entry in new_entries}
    existing_ids = set(existing_entries.keys())
    new_entry_ids = set(new_entries_dict.keys())

    return (
        identify_new_entries(existing_ids, new_entries_dict),
        identify_deleted_entries(existing_ids, new_entry_ids, existing_entries, start_date),
        identify_updated_entries(existing_ids, new_entry_ids, existing_entries, new_entries_dict),
    )


def identify_changes_and_save(existing_entries, new_entries, start_date, aws_config=None, output_folder=None):
    """Compute the diff between stored and fetched entries, then persist each change set.

    Args:
        existing_entries (dict): Previously persisted ID-keyed entries.
        new_entries (list): Entries returned by the latest API fetch.
        start_date (str): Fetch window start date in YYYY-MM-DD format.
        aws_config (dict | None): AWS configuration for S3 uploads.
        output_folder (str | None): Local folder for change files; uses LOCAL_CHANGES_FOLDER if None.

    Returns:
        tuple[list, list, list]: (new_entries_list, deleted_entries_list, updated_entries_list)
    """
    new_entries_list, deleted_entries_list, updated_entries_list = compute_changes(
        existing_entries, new_entries, start_date
    )

    print("="*60)
    print_changes_summary(new_entries_list, "New entries")
    print_changes_summary(deleted_entries_list, "\nDeleted entries")
    print_changes_summary(updated_entries_list, "\nUpdated entries")
    print("="*60 + "\n")

    date_str, time_str = get_current_datetime_strings()

    is_local = not os.getenv('AWS_LAMBDA_FUNCTION_NAME')

    if output_folder is None and is_local:
        output_folder = LOCAL_CHANGES_FOLDER
    if output_folder:
        os.makedirs(output_folder, exist_ok=True)

    save_changes_file(new_entries_list, 'new', date_str, time_str, is_local, aws_config, output_folder)
    save_changes_file(deleted_entries_list, 'deleted', date_str, time_str, is_local, aws_config, output_folder)
    save_changes_file(updated_entries_list, 'updated', date_str, time_str, is_local, aws_config, output_folder)

    if not new_entries_list and not deleted_entries_list and not updated_entries_list:
        print("No changes detected, no files created.")

    return new_entries_list, deleted_entries_list, updated_entries_list


def merge_entries(existing_entries, new_entries, start_date):
    """Merge fetched entries into the stored dict, removing deleted and expired entries.

    Deletions in Harvest (entries missing from the new fetch whose spent_date
    falls within the window) are propagated. Entries older than start_date - 1
    day are pruned to prevent unbounded growth of the stored file.

    Args:
        existing_entries (dict): ID-keyed stored entries, mutated in place.
        new_entries (list): Entries returned by the latest API fetch.
        start_date (str): Fetch window start date in YYYY-MM-DD format.

    Returns:
        dict: The updated existing_entries dict.
    """
    print(f"Starting merge - {len(existing_entries)} existing entries, {len(new_entries)} new entries")

    new_entries_dict = {entry['id']: entry for entry in new_entries}

    # Snapshot IDs before upsert so we can detect genuinely new records later
    existing_ids_before_merge = set(existing_entries.keys())

    # Upsert: add new entries and overwrite changed ones
    for entry_id, new_entry in new_entries_dict.items():
        existing_entries[entry_id] = new_entry

    new_entry_ids = set(new_entries_dict.keys())

    # Remove entries deleted in Harvest (only within the fetch window)
    deleted_ids = []
    for entry_id in existing_ids_before_merge - new_entry_ids:
        entry = existing_entries.get(entry_id)
        if entry:
            spent_date = entry.get('spent_date', '')
            if spent_date and spent_date >= start_date:
                deleted_ids.append(entry_id)
                del existing_entries[entry_id]

    # Prune entries older than start_date - 1 day to cap file size
    start_date_minus_1 = calculate_cutoff_date(start_date, days_offset=1)
    removed_old_ids = []
    for entry_id, entry in list(existing_entries.items()):
        spent_date = entry.get('spent_date', '')
        if spent_date and spent_date < start_date_minus_1:
            removed_old_ids.append(entry_id)
            del existing_entries[entry_id]

    if deleted_ids:
        print(f"✓ {len(deleted_ids)} entry/entries deleted in Harvest (spent_date >= {start_date})")
    if removed_old_ids:
        print(f"✓ {len(removed_old_ids)} old entry/entries removed (spent_date < {start_date_minus_1})")

    print(f"Merge complete - {len(existing_entries)} entries after merge")
    return existing_entries
