"""Change history reader: loads and displays Harvest entry changes from local files or S3."""

import json
from datetime import datetime, timedelta, timezone
from itertools import groupby
from pathlib import Path

from config import (
    DATE_FORMAT_FILENAME, LOCAL_CHANGES_FOLDER, LOCAL_LANDING_FOLDER,
    S3_CHANGES_SUBFOLDER, S3_DAILY_SUBFOLDER,
)
from s3 import create_s3_client, download_from_s3

CHANGE_TYPES = ('new', 'updated', 'deleted')
DIFF_FIELDS = [('hours', 'Hours'), ('notes', 'Notes'), ('spent_date', 'Date')]
DIFF_NESTED = [('project', 'name', 'Project'), ('task', 'name', 'Task')]


def _parse_filename_time(filename):
    """Parse UTC datetime from a change filename like 20260314-new-210722.json."""
    stem = Path(filename).stem          # 20260314-new-210722
    parts = stem.split('-')             # ['20260314', 'new', '210722']
    dt = datetime.strptime(parts[0] + parts[2], '%Y%m%d%H%M%S')
    return dt.replace(tzinfo=timezone.utc)


def _load_daily_seed_local(local_dir, cutoff):
    """Return (entries_dict, seed_datetime) from the most recent daily snapshot predating cutoff.

    Args:
        local_dir (str): Path to local landing folder.
        cutoff (datetime): Window start — only snapshots before this are used.

    Returns:
        tuple[dict, datetime | None]: ID-keyed entries and the snapshot's datetime, or ({}, None).
    """
    daily_dir = Path(local_dir) / S3_DAILY_SUBFOLDER
    if not daily_dir.exists():
        return {}, None
    best_dt, best_file = None, None
    for f in daily_dir.glob('*.json'):
        try:
            dt = datetime.strptime(f.stem, DATE_FORMAT_FILENAME).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if dt < cutoff and (best_dt is None or dt > best_dt):
            best_dt, best_file = dt, f
    if best_file is None:
        return {}, None
    with open(best_file, encoding='utf-8') as fh:
        entries = json.load(fh)
    return {e['id']: e for e in entries}, best_dt


def _load_daily_seed_s3(aws_config, cutoff):
    """Return (entries_dict, seed_datetime) from the most recent S3 daily snapshot predating cutoff.

    Args:
        aws_config (dict): AWS configuration.
        cutoff (datetime): Window start.

    Returns:
        tuple[dict, datetime | None]: ID-keyed entries and the snapshot's datetime, or ({}, None).
    """
    client = create_s3_client(aws_config)
    bucket = aws_config['bucket_name']
    paginator = client.get_paginator('list_objects_v2')
    best_dt, best_key = None, None
    for page in paginator.paginate(Bucket=bucket, Prefix=f'{S3_DAILY_SUBFOLDER}/'):
        for obj in page.get('Contents', []):
            key = obj['Key']
            try:
                dt = datetime.strptime(Path(key).stem, DATE_FORMAT_FILENAME).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if dt < cutoff and (best_dt is None or dt > best_dt):
                best_dt, best_key = dt, key
    if best_key is None:
        return {}, None
    entries = download_from_s3(best_key, aws_config)
    return ({e['id']: e for e in entries} if isinstance(entries, list) else {}), best_dt


def _load_change_files_local(local_dir, since):
    """Return (run_time, change_type, entry) tuples from local change files >= since.

    Args:
        local_dir (str): Path to local landing folder.
        since (datetime): Only load files at or after this datetime.

    Returns:
        list[tuple]: (run_time, change_type, entry) for each entry in matching files.
    """
    events = []
    changes_dir = Path(local_dir) / LOCAL_CHANGES_FOLDER
    for ct in CHANGE_TYPES:
        folder = changes_dir / ct
        if not folder.exists():
            continue
        for f in sorted(folder.glob('*.json')):
            try:
                run_time = _parse_filename_time(f.name)
            except (ValueError, IndexError):
                continue
            if run_time >= since:
                with open(f, encoding='utf-8') as fh:
                    for entry in json.load(fh):
                        events.append((run_time, ct, entry))
    return events


def _load_change_files_s3(aws_config, since):
    """Return (run_time, change_type, entry) tuples from S3 change files >= since.

    Args:
        aws_config (dict): AWS configuration.
        since (datetime): Only load files at or after this datetime.

    Returns:
        list[tuple]: (run_time, change_type, entry) for each entry in matching files.
    """
    client = create_s3_client(aws_config)
    bucket = aws_config['bucket_name']
    events = []
    for ct in CHANGE_TYPES:
        prefix = f'{S3_CHANGES_SUBFOLDER}/{ct}/'
        paginator = client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get('Contents', []):
                key = obj['Key']
                try:
                    run_time = _parse_filename_time(Path(key).name)
                except (ValueError, IndexError):
                    continue
                if run_time >= since:
                    data = download_from_s3(key, aws_config)
                    if isinstance(data, list):
                        for entry in data:
                            events.append((run_time, ct, entry))
    return events


def _build_events_with_diff(events, seed_state):
    """Walk events chronologically and attach the before-state to each for diff computation.

    Entries that were 'new' within the event set are removed from the seed so their
    before-state is correctly empty rather than pointing to a later version.

    Args:
        events (list[tuple]): (run_time, change_type, entry) tuples.
        seed_state (dict): ID-keyed entries representing state before the first event.

    Returns:
        list[tuple]: (run_time, change_type, entry, prev_entry) for each event.
    """
    new_ids = {e['id'] for _, ct, e in events if ct == 'new'}
    state = {k: v for k, v in seed_state.items() if k not in new_ids}

    results = []
    for run_time, batch in groupby(sorted(events, key=lambda x: x[0]), key=lambda x: x[0]):
        batch = list(batch)
        for _, ct, entry in batch:
            results.append((run_time, ct, entry, state.get(entry['id'])))
        for _, ct, entry in batch:
            if ct in ('new', 'updated'):
                state[entry['id']] = entry
            elif ct == 'deleted':
                state.pop(entry['id'], None)
    return results


def _get_diff(old, new):
    """Return human-readable change descriptions between old and new entry versions.

    Args:
        old (dict | None): Previous entry state.
        new (dict): Current entry state.

    Returns:
        list[str]: Each element describes one changed field, e.g. 'Hours: 2.0 → 22.0'.
    """
    if not old:
        return ['(previous version unavailable)']
    diffs = []
    for key, label in DIFF_FIELDS:
        ov, nv = old.get(key), new.get(key)
        if ov != nv:
            diffs.append(f'{label}: {ov!r} → {nv!r}')
    for key, field, label in DIFF_NESTED:
        ov = (old.get(key) or {}).get(field)
        nv = (new.get(key) or {}).get(field)
        if ov != nv:
            diffs.append(f'{label}: {ov!r} → {nv!r}')
    return diffs or ['(no tracked field changed)']


def _print_history(events_with_diff, cutoff):
    """Print formatted change history, showing only events at or after cutoff.

    Args:
        events_with_diff (list[tuple]): (run_time, change_type, entry, prev) tuples.
        cutoff (datetime): Display threshold.
    """
    visible = [(rt, ct, e, prev) for rt, ct, e, prev in events_with_diff if rt >= cutoff]
    if not visible:
        print('No changes found in the requested period.')
        return
    for run_time, ct, entry, prev in visible:
        user    = (entry.get('user') or {}).get('name', '?')
        project = (entry.get('project') or {}).get('name', '?')
        task    = (entry.get('task') or {}).get('name', '?')
        hours   = entry.get('hours', '?')
        notes   = entry.get('notes') or '(empty)'
        date    = entry.get('spent_date', '?')
        action  = {'new': 'ADDED', 'updated': 'UPDATED', 'deleted': 'DELETED'}[ct]
        print(f'\n  [{run_time.strftime("%Y-%m-%d %H:%M UTC")}] {action}')
        print(f'  Person  : {user}')
        print(f'  Project : {project} / {task}')
        print(f'  Hours   : {hours}h on {date}')
        print(f'  Notes   : {notes}')
        if ct == 'updated':
            print(f'  Changes : {"; ".join(_get_diff(prev, entry))}')
    print(f'\n{"=" * 65}')
    print(f'Total: {len(visible)} event(s)')


def show_history(hours_back=24, local=False, local_dir=LOCAL_LANDING_FOLDER, aws_config=None):
    """Display Harvest change history for the last hours_back hours.

    Uses daily snapshots as seed state for accurate before/after diffs on updated entries.

    Args:
        hours_back (int): Number of hours to look back (default 24).
        local (bool): Read from local harvest_landing/ instead of S3.
        local_dir (str): Path to local landing folder.
        aws_config (dict | None): AWS configuration for S3 access.

    Raises:
        ValueError: If S3 mode is requested but aws_config is missing.
    """
    if not local and not aws_config:
        raise ValueError('AWS configuration is required for S3 history')

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    print(f'Change history — last {hours_back}h (since {cutoff.strftime("%Y-%m-%d %H:%M UTC")})')
    print('=' * 65)

    if local:
        seed, seed_dt = _load_daily_seed_local(local_dir, cutoff)
        since = seed_dt if seed_dt else cutoff
        events = _load_change_files_local(local_dir, since)
    else:
        seed, seed_dt = _load_daily_seed_s3(aws_config, cutoff)
        since = seed_dt if seed_dt else cutoff
        events = _load_change_files_s3(aws_config, since)

    events_with_diff = _build_events_with_diff(events, seed)
    _print_history(events_with_diff, cutoff)
