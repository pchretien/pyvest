"""Core processing logic for fetching, diffing, merging, and persisting Harvest time entries."""

import requests
import json
import os
from datetime import datetime, timedelta
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

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
            raise ValueError("Les variables d'environnement HARVEST_ACCOUNT_ID et HARVEST_ACCESS_TOKEN sont requises")
        if not config['aws']['bucket_name']:
            raise ValueError("La variable d'environnement S3_BUCKET_NAME est requise")

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
            raise ValueError("Le fichier de configuration doit contenir 'account_id', 'access_token' et 'harvest_url'")

        if 'days_back' not in config:
            config['days_back'] = DEFAULT_DAYS_BACK
            print(f"Paramètre 'days_back' non trouvé, utilisation de la valeur par défaut: {DEFAULT_DAYS_BACK} jours")

        if 'aws' in config:
            aws_config = config['aws']
            required_aws_fields = ['access_key_id', 'secret_access_key', 'region', 'bucket_name']
            for field in required_aws_fields:
                if field not in aws_config:
                    print(f"Attention: Configuration AWS incomplète. Le champ '{field}' est manquant.")

        return config
    except FileNotFoundError:
        sample_config = {
            'account_id': 'VOTRE_ACCOUNT_ID',
            'access_token': 'VOTRE_ACCESS_TOKEN',
            'harvest_url': 'https://api.harvestapp.com/v2/time_entries',
            'days_back': DEFAULT_DAYS_BACK,
            'aws': {
                'access_key_id': 'VOTRE_ACCESS_KEY_ID',
                'secret_access_key': 'VOTRE_SECRET_ACCESS_KEY',
                'region': 'us-east-1',
                'bucket_name': 'votre-bucket-name'
            }
        }
        error_msg = (
            f"Le fichier {config_file} n'existe pas.\n"
            "Créez un fichier config.json avec le format suivant:\n"
            f"{json.dumps(sample_config, indent=2)}"
        )
        raise FileNotFoundError(error_msg)
    except json.JSONDecodeError as e:
        raise ValueError(f"Le fichier {config_file} n'est pas un JSON valide: {e}") from e


def get_time_entries(account_id, access_token, harvest_url, from_date, to_date, days_back=None):
    """Fetch all time entries from the Harvest API for a given date range.

    Iterates through all pages of results until the last page is reached.

    Args:
        account_id (str): Harvest account identifier.
        access_token (str): Harvest API bearer token.
        harvest_url (str): Base URL for the Harvest time-entries endpoint.
        from_date (str): Start date in YYYY-MM-DD format.
        to_date (str): End date in YYYY-MM-DD format.
        days_back (int, optional): Number of days back, used only for display.

    Returns:
        list: All time entry dicts returned by the API.

    Raises:
        RuntimeError: On timeout, HTTP error, or invalid JSON response.
    """
    if days_back:
        print(f"Récupération des entrées de temps du {from_date} au {to_date} ({days_back} derniers jours)...")
    else:
        print(f"Récupération des entrées de temps du {from_date} au {to_date}...")

    url = harvest_url
    all_entries = []
    page = 1

    headers = {
        "Harvest-Account-ID": account_id,
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "Python Harvest Script"
    }

    params = {
        "from": from_date,
        "to": to_date,
        "page": page,
        "per_page": HARVEST_API_MAX_PER_PAGE
    }

    try:
        while True:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            try:
                data = response.json()
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"Erreur: La réponse de l'API Harvest n'est pas un JSON valide. "
                    f"Status code: {response.status_code}, URL: {url}"
                ) from e

            time_entries = data.get('time_entries', [])

            if not time_entries:
                break

            all_entries.extend(time_entries)

            # Stop when we have consumed the last page
            total_pages = data.get('total_pages', 1)
            if page >= total_pages:
                break

            page += 1
            params['page'] = page

        print(f"Total: {len(all_entries)} entrées récupérées sur {page} page(s)")
        return all_entries

    except requests.exceptions.Timeout as e:
        raise RuntimeError(
            f"Erreur: Timeout lors de la requête API Harvest (URL: {url}). "
            f"La requête a pris plus de 30 secondes."
        ) from e
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response else "unknown"
        raise RuntimeError(
            f"Erreur HTTP {status_code} lors de la requête API Harvest (URL: {url}). "
            f"Vérifiez vos credentials et l'URL de l'API."
        ) from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(
            f"Erreur lors de la requête API Harvest (URL: {url}): {e}"
        ) from e


def load_period_entries_from_s3(aws_config):
    """Load existing time entries from S3 (harvest-data.json) as an ID-keyed dict.

    Args:
        aws_config (dict): AWS configuration with bucket_name, region, and credentials.

    Returns:
        dict: Mapping of entry ID to entry dict, or {} if unavailable.
    """
    if not aws_config:
        print("Configuration AWS non trouvée, impossible de charger depuis S3.")
        return {}

    entries = download_from_s3(S3_HARVEST_DATA_FILE, aws_config)

    if not entries:
        print(f"Aucune entrée chargée depuis S3 (fichier {S3_HARVEST_DATA_FILE} vide ou inexistant)")
        return {}

    entries_dict = {entry['id']: entry for entry in entries}
    print(f"{len(entries_dict)} entrées chargées depuis S3 ({S3_HARVEST_DATA_FILE})")
    return entries_dict


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
    return value if value else default


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
    notes = entry.get('notes', '') or '(vide)'

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
            print(f"  ... et {len(entries_list) - max_display} autre(s) entrée(s) non affichée(s)")


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
        print(f"✓ Fichier sauvegardé: {filepath} ({len(entries_list)} entrées)")
        success = True

    if aws_config:
        s3_key = f"{S3_CHANGES_SUBFOLDER}/{change_subfolder}/{filename}"
        if upload_to_s3(entries_list, s3_key, aws_config):
            print(f"✓ Fichier uploadé vers S3: s3://{aws_config['bucket_name']}/{s3_key}")
            success = True

    return success


def identify_changes_and_save(existing_entries, new_entries, start_date, aws_config=None):
    """Compute the diff between stored and fetched entries, then persist each change set.

    Args:
        existing_entries (dict): Previously persisted ID-keyed entries.
        new_entries (list): Entries returned by the latest API fetch.
        start_date (str): Fetch window start date in YYYY-MM-DD format.
        aws_config (dict | None): AWS configuration for S3 uploads.

    Returns:
        tuple[list, list, list]: (new_entries_list, deleted_entries_list, updated_entries_list)
    """
    new_entries_dict = {entry['id']: entry for entry in new_entries}
    existing_ids = set(existing_entries.keys())
    new_entry_ids = set(new_entries_dict.keys())

    new_entries_list = identify_new_entries(existing_ids, new_entries_dict)
    deleted_entries_list = identify_deleted_entries(existing_ids, new_entry_ids, existing_entries, start_date)
    updated_entries_list = identify_updated_entries(existing_ids, new_entry_ids, existing_entries, new_entries_dict)

    print("="*60)
    print_changes_summary(new_entries_list, "Nouvelles entrées")
    print_changes_summary(deleted_entries_list, "\nEntrées supprimées")
    print_changes_summary(updated_entries_list, "\nEntrées mises à jour")
    print("="*60 + "\n")

    date_str, time_str = get_current_datetime_strings()

    is_local = not os.getenv('AWS_LAMBDA_FUNCTION_NAME')

    output_folder = None
    if is_local:
        output_folder = LOCAL_CHANGES_FOLDER
        os.makedirs(output_folder, exist_ok=True)

    save_changes_file(new_entries_list, 'new', date_str, time_str, is_local, aws_config, output_folder)
    save_changes_file(deleted_entries_list, 'deleted', date_str, time_str, is_local, aws_config, output_folder)
    save_changes_file(updated_entries_list, 'updated', date_str, time_str, is_local, aws_config, output_folder)

    if not new_entries_list and not deleted_entries_list and not updated_entries_list:
        print("Aucun changement détecté, aucun fichier créé.")

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
    print(f"Début du merge - {len(existing_entries)} entrées existantes, {len(new_entries)} nouvelles entrées")

    new_entries_dict = {entry['id']: entry for entry in new_entries}

    # Snapshot IDs before upsert so we can detect genuinely new records later
    existing_ids_before_merge = set(existing_entries.keys())

    # Upsert: add new entries and overwrite changed ones
    for entry_id, new_entry in new_entries_dict.items():
        existing_entries[entry_id] = new_entry

    new_entry_ids = set(new_entries_dict.keys())
    all_existing_ids = set(existing_entries.keys())

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

    new_record_count = len(new_entry_ids - existing_ids_before_merge)

    if deleted_ids:
        print(f"✓ {len(deleted_ids)} entrée(s) supprimée(s) dans Harvest (spent_date >= {start_date})")
    if removed_old_ids:
        print(f"✓ {len(removed_old_ids)} entrée(s) ancienne(s) supprimée(s) (spent_date < {start_date_minus_1})")

    print(f"Fin du merge - {len(existing_entries)} entrées après fusion")
    return existing_entries


def save_period_entries_to_s3(entries_dict, aws_config):
    """Upload all entries to S3 as a dated daily file and as harvest-data.json.

    Args:
        entries_dict (dict): ID-keyed entries to persist.
        aws_config (dict): AWS configuration with bucket_name and region.

    Returns:
        bool: True if both uploads succeeded.
    """
    if not aws_config:
        print("Configuration AWS non trouvée, impossible de sauvegarder vers S3.")
        return False

    # Sort by spent_date for consistent ordering in the stored file
    entries_list = sorted(entries_dict.values(), key=lambda x: x.get('spent_date', ''))

    today = datetime.now()
    json_filename = f"{today.strftime(DATE_FORMAT_FILENAME)}.json"
    s3_key = f"{S3_DAILY_SUBFOLDER}/{json_filename}"

    success = upload_to_s3(entries_list, s3_key, aws_config)
    success_latest = upload_to_s3(entries_list, S3_HARVEST_DATA_FILE, aws_config)

    if success and success_latest:
        print(f"✓ {len(entries_list)} entrée(s) sauvegardée(s) vers S3 ({s3_key} et {S3_HARVEST_DATA_FILE})")

    return success and success_latest


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
        data = json.loads(content)

        return data

    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            print(f"Fichier s3://{aws_config['bucket_name']}/{s3_key} n'existe pas, création d'un nouveau fichier.")
            return []
        else:
            print(f"Erreur AWS S3 lors du téléchargement: {e}")
            return []
    except NoCredentialsError:
        print("Erreur: Credentials AWS non trouvées ou invalides.")
        return []
    except Exception as e:
        print(f"Erreur lors du téléchargement depuis AWS: {e}")
        return []


def upload_to_s3(data, s3_key, aws_config):
    """Serialise data as JSON and upload it to S3.

    Args:
        data (list | dict): Data to serialise and upload.
        s3_key (str): Destination S3 object key.
        aws_config (dict): AWS configuration with bucket_name and credentials.

    Returns:
        bool: True on success, False on any error.
    """
    try:
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
        print("Erreur: Credentials AWS non trouvées ou invalides.")
        return False
    except ClientError as e:
        print(f"Erreur AWS S3: {e}")
        return False
    except Exception as e:
        print(f"Erreur lors de l'upload vers AWS: {e}")
        return False


def handle_no_event():
    """Run the full Harvest export pipeline: fetch, diff, merge, and save to S3.

    Returns:
        dict: Summary with keys loaded, new, saved, and success, or an error
            response dict with statusCode 500 if AWS config is missing.
    """
    config = load_config_from_env()
    account_id = config['account_id']
    access_token = config['access_token']
    harvest_url = config['harvest_url']
    days_back = config['days_back']
    aws_config = config.get('aws')
    if not aws_config:
        print("Configuration AWS requise pour le fonctionnement du script.")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Configuration AWS requise'})
        }

    from_date_display, to_date_display = calculate_date_range(days_back)

    time_entries = get_time_entries(account_id, access_token, harvest_url, from_date_display, to_date_display, days_back)

    period_entries = load_period_entries_from_s3(aws_config)

    # Diff against a copy so the original is unmodified when passed to merge
    identify_changes_and_save( period_entries.copy(), time_entries, from_date_display, aws_config )

    updated_period_entries = merge_entries(period_entries, time_entries, from_date_display)

    success = save_period_entries_to_s3(updated_period_entries, aws_config)

    summary = {
        'loaded': len(period_entries),
        'new': len(time_entries),
        'saved': len(updated_period_entries),
        'success': success
    }

    return summary
