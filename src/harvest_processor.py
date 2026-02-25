"""
Module principal contenant toutes les fonctions et constantes pour le traitement des données Harvest.
"""

import requests
import json
import os
from datetime import datetime, timedelta
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

# ============================================================================
# Constants: S3 paths
# ============================================================================
S3_HARVEST_DATA_FILE = "harvest-data.json"
S3_DAILY_SUBFOLDER = "daily"
S3_CHANGES_SUBFOLDER = "changes"

# ============================================================================
# Constants: Local paths
# ============================================================================
LOCAL_CHANGES_FOLDER = "changes"

# ============================================================================
# Constants: Date/Time formats
# ============================================================================
DATE_FORMAT_FILENAME = '%Y%m%d'
DATE_FORMAT_DISPLAY = '%Y-%m-%d'
TIME_FORMAT_FILENAME = '%H%M%S'

# ============================================================================
# Constants: File naming patterns
# ============================================================================
CHANGES_FILE_PATTERNS = {
    'new': '-new-',
    'deleted': '-deleted-',
    'updated': '-updated-'
}

# ============================================================================
# Constants: API settings
# ============================================================================
HARVEST_API_MAX_PER_PAGE = 2000
DEFAULT_DAYS_BACK = 90

# ============================================================================
# Constants: Display settings
# ============================================================================
MAX_CHANGES_ENTRIES_DISPLAYED = 10

def load_config_from_env():
    """
    Charge la configuration depuis les variables d'environnement Lambda.
    Pour une utilisation locale, peut charger depuis config.json si disponible.
    """
    # En Lambda, utiliser les variables d'environnement
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
        
        # Vérifier les variables requises
        if not config['account_id'] or not config['access_token']:
            raise ValueError("Les variables d'environnement HARVEST_ACCOUNT_ID et HARVEST_ACCESS_TOKEN sont requises")
        if not config['aws']['bucket_name']:
            raise ValueError("La variable d'environnement S3_BUCKET_NAME est requise")
        
        return config
    else:
        # Mode local: essayer de charger depuis config.json
        return load_config_from_file()

def load_config_from_file(config_file='config.json'):
    """
    Charge la configuration depuis un fichier JSON (pour usage local).
    """
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        
        if 'account_id' not in config or 'access_token' not in config or 'harvest_url' not in config:
            raise ValueError("Le fichier de configuration doit contenir 'account_id', 'access_token' et 'harvest_url'")
        
        # Vérifier le paramètre days_back (optionnel, défaut DEFAULT_DAYS_BACK)
        if 'days_back' not in config:
            config['days_back'] = DEFAULT_DAYS_BACK
            print(f"Paramètre 'days_back' non trouvé, utilisation de la valeur par défaut: {DEFAULT_DAYS_BACK} jours")
        
        # Vérifier la configuration AWS (optionnelle)
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
    """
    Récupère toutes les entrées de temps depuis l'API Harvest pour une plage de dates donnée.
    Gère la pagination pour récupérer toutes les pages de résultats.
    """
    # Afficher le message de récupération
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
            
            # Vérifier s'il y a une page suivante
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
    """
    Charge les entrées existantes depuis S3.
    Charge depuis harvest-data.json.
    Retourne un dictionnaire avec les IDs comme clés pour faciliter les mises à jour.
    
    Args:
        aws_config: Configuration AWS pour accéder à S3
    
    Returns:
        dict: Dictionnaire des entrées avec l'ID comme clé
    """
    if not aws_config:
        print("Configuration AWS non trouvée, impossible de charger depuis S3.")
        return {}
    
    # Télécharger les données depuis S3 (depuis harvest-data.json)
    entries = download_from_s3(S3_HARVEST_DATA_FILE, aws_config)
    
    if not entries:
        print(f"Aucune entrée chargée depuis S3 (fichier {S3_HARVEST_DATA_FILE} vide ou inexistant)")
        return {}
    
    # Convertir la liste en dictionnaire avec l'ID comme clé
    entries_dict = {entry['id']: entry for entry in entries}
    print(f"{len(entries_dict)} entrées chargées depuis S3 ({S3_HARVEST_DATA_FILE})")
    return entries_dict

def calculate_cutoff_date(start_date, days_offset=1):
    """
    Calcule la date de coupure (start_date - days_offset).
    
    Args:
        start_date: Date de début au format YYYY-MM-DD
        days_offset: Nombre de jours à soustraire (défaut: 1)
    
    Returns:
        str: Date de coupure au format YYYY-MM-DD
    """
    return (datetime.strptime(start_date, DATE_FORMAT_DISPLAY) - 
            timedelta(days=days_offset)).strftime(DATE_FORMAT_DISPLAY)

def get_current_datetime_strings():
    """
    Retourne les chaînes de date et heure formatées pour les noms de fichiers.
    
    Returns:
        tuple: (date_str, time_str) au format (YYYYMMDD, HHMMSS)
    """
    now = datetime.now()
    return (
        now.strftime(DATE_FORMAT_FILENAME),
        now.strftime(TIME_FORMAT_FILENAME)
    )

def calculate_date_range(days_back):
    """
    Calcule la plage de dates pour la récupération des entrées.
    
    Args:
        days_back: Nombre de jours en arrière à partir d'aujourd'hui
    
    Returns:
        tuple: (from_date, to_date) au format YYYY-MM-DD
    """
    today = datetime.now()
    from_date = (today - timedelta(days=days_back)).strftime(DATE_FORMAT_DISPLAY)
    to_date = today.strftime(DATE_FORMAT_DISPLAY)
    return from_date, to_date

def safe_get_nested(data, *keys, default='N/A'):
    """
    Récupère une valeur imbriquée de manière sûre.
    
    Args:
        data: Dictionnaire ou structure de données
        *keys: Clés imbriquées à suivre (par exemple: 'user', 'name')
        default: Valeur par défaut si la clé n'existe pas
    
    Returns:
        La valeur trouvée ou la valeur par défaut
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
    """
    Formate une time entry pour l'affichage en extrayant les champs spécifiés.
    
    Args:
        entry: Dictionnaire représentant une time entry
    
    Returns:
        str: Chaîne formatée avec les champs demandés
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
    """
    Trie les entrées par updated_at (décroissant) et retourne les limit premières.
    
    Args:
        entries: Liste d'entrées à trier
        limit: Nombre maximum d'entrées à retourner
    
    Returns:
        list: Les limit entrées les plus récentes
    """
    sorted_entries = sorted(
        entries,
        key=lambda x: x.get('updated_at', '') or '',
        reverse=True
    )
    return sorted_entries[:limit]

def print_changes_summary(entries_list, label, max_display=MAX_CHANGES_ENTRIES_DISPLAYED):
    """
    Affiche un résumé des changements avec les N plus récentes entrées.
    
    Args:
        entries_list: Liste des entrées à afficher
        label: Libellé pour le type de changements
        max_display: Nombre maximum d'entrées à afficher
    """
    print(f"{label}: {len(entries_list)}")
    if entries_list:
        newest = get_newest_entries(entries_list, max_display)
        for entry in newest:
            print(format_time_entry(entry))
        if len(entries_list) > max_display:
            print(f"  ... et {len(entries_list) - max_display} autre(s) entrée(s) non affichée(s)")

def identify_new_entries(existing_ids, new_entries_dict):
    """
    Identifie les nouvelles entrées (présentes dans new_entries mais pas dans existing).
    
    Args:
        existing_ids: Set des IDs des entrées existantes
        new_entries_dict: Dictionnaire des nouvelles entrées (ID -> entry)
    
    Returns:
        list: Liste des nouvelles entrées
    """
    return [entry for entry_id, entry in new_entries_dict.items() 
            if entry_id not in existing_ids]

def identify_deleted_entries(existing_ids, new_entry_ids, existing_entries, start_date):
    """
    Identifie les entrées supprimées (présentes dans existing mais pas dans new_entries).
    Filtre par spent_date >= start_date.
    
    Args:
        existing_ids: Set des IDs des entrées existantes
        new_entry_ids: Set des IDs des nouvelles entrées
        existing_entries: Dictionnaire des entrées existantes (ID -> entry)
        start_date: Date de début pour filtrer les suppressions
    
    Returns:
        list: Liste des entrées supprimées
    """
    deleted = []
    for entry_id in existing_ids - new_entry_ids:
        entry = existing_entries[entry_id]
        spent_date = entry.get('spent_date', '')
        if spent_date and spent_date >= start_date:
            deleted.append(entry)
    return deleted

def identify_updated_entries(existing_ids, new_entry_ids, existing_entries, new_entries_dict):
    """
    Identifie les entrées mises à jour (présentes dans les deux mais modifiées).
    
    Args:
        existing_ids: Set des IDs des entrées existantes
        new_entry_ids: Set des IDs des nouvelles entrées
        existing_entries: Dictionnaire des entrées existantes (ID -> entry)
        new_entries_dict: Dictionnaire des nouvelles entrées (ID -> entry)
    
    Returns:
        list: Liste des entrées mises à jour
    """
    updated = []
    for entry_id in existing_ids & new_entry_ids:
        existing_entry = existing_entries[entry_id]
        new_entry = new_entries_dict[entry_id]
        
        # Comparer les updated_at pour détecter les changements
        if existing_entry.get('updated_at', '') != new_entry.get('updated_at', ''):
            updated.append(new_entry)
    return updated

def save_changes_file(entries_list, change_type, date_str, time_str, is_local, aws_config, output_folder=None):
    """
    Sauvegarde une liste de changements sur disque et/ou S3.
    
    Args:
        entries_list: Liste des entrées à sauvegarder
        change_type: Type de changement ('new', 'deleted', 'updated')
        date_str: Date au format YYYYMMDD
        time_str: Heure au format HHMMSS
        is_local: True si on est en mode local (pas Lambda)
        aws_config: Configuration AWS optionnelle
        output_folder: Dossier local de base pour la sauvegarde (optionnel)
    
    Returns:
        bool: True si la sauvegarde a réussi (au moins une), False sinon
    """
    if not entries_list:
        return False
    
    filename = f"{date_str}{CHANGES_FILE_PATTERNS[change_type]}{time_str}.json"
    success = False
    
    # Créer le sous-dossier basé sur le type de changement
    change_subfolder = change_type  # 'new', 'deleted', ou 'updated'
    
    # Sauvegarde locale
    if is_local and output_folder:
        # Créer le sous-dossier pour ce type de changement
        subfolder_path = os.path.join(output_folder, change_subfolder)
        os.makedirs(subfolder_path, exist_ok=True)
        filepath = os.path.join(subfolder_path, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(entries_list, f, indent=2, ensure_ascii=False)
        print(f"✓ Fichier sauvegardé: {filepath} ({len(entries_list)} entrées)")
        success = True
    
    # Sauvegarde S3
    if aws_config:
        s3_key = f"{S3_CHANGES_SUBFOLDER}/{change_subfolder}/{filename}"
        if upload_to_s3(entries_list, s3_key, aws_config):
            print(f"✓ Fichier uploadé vers S3: s3://{aws_config['bucket_name']}/{s3_key}")
            success = True
    
    return success

def identify_changes_and_save(existing_entries, new_entries, start_date, aws_config=None):
    """
    Identifie les nouvelles entrées, les entrées supprimées et les entrées mises à jour.
    Affiche les trois listes et les sauvegarde dans des fichiers JSON sur disque et dans S3.
    
    Args:
        existing_entries: Dictionnaire des entrées existantes (ID -> entry)
        new_entries: Liste des nouvelles entrées depuis l'API
        start_date: Date de début pour filtrer les suppressions
        aws_config: Configuration AWS optionnelle pour sauvegarder dans S3
    
    Returns:
        tuple: (new_entries_list, deleted_entries_list, updated_entries_list)
    """
    # Créer un dictionnaire des nouvelles entrées
    new_entries_dict = {entry['id']: entry for entry in new_entries}
    existing_ids = set(existing_entries.keys())
    new_entry_ids = set(new_entries_dict.keys())
    
    # Identifier les différents types de changements
    new_entries_list = identify_new_entries(existing_ids, new_entries_dict)
    deleted_entries_list = identify_deleted_entries(existing_ids, new_entry_ids, existing_entries, start_date)
    updated_entries_list = identify_updated_entries(existing_ids, new_entry_ids, existing_entries, new_entries_dict)
    
    # Afficher les trois listes (seulement les N plus récentes)
    print("="*60)
    print_changes_summary(new_entries_list, "Nouvelles entrées")
    print_changes_summary(deleted_entries_list, "\nEntrées supprimées")
    print_changes_summary(updated_entries_list, "\nEntrées mises à jour")
    print("="*60 + "\n")
    
    # Générer le nom de fichier avec date et heure
    date_str, time_str = get_current_datetime_strings()
    
    # Vérifier si on est en mode local (pas Lambda)
    is_local = not os.getenv('AWS_LAMBDA_FUNCTION_NAME')
    
    # Créer le dossier pour sauvegarder les fichiers (seulement en local)
    output_folder = None
    if is_local:
        output_folder = LOCAL_CHANGES_FOLDER
        os.makedirs(output_folder, exist_ok=True)
    
    # Sauvegarder les trois types de changements
    save_changes_file(new_entries_list, 'new', date_str, time_str, is_local, aws_config, output_folder)
    save_changes_file(deleted_entries_list, 'deleted', date_str, time_str, is_local, aws_config, output_folder)
    save_changes_file(updated_entries_list, 'updated', date_str, time_str, is_local, aws_config, output_folder)
    
    if not new_entries_list and not deleted_entries_list and not updated_entries_list:
        print("Aucun changement détecté, aucun fichier créé.")
    
    return new_entries_list, deleted_entries_list, updated_entries_list

def merge_entries(existing_entries, new_entries, start_date):
    """
    Fusionne les nouvelles entrées avec les existantes.
    Gère les mises à jour et les suppressions.
    Supprime les entrées avec spent_date < start_date - 1 jour pour éviter la croissance indéfinie.
    """
    print(f"Début du merge - {len(existing_entries)} entrées existantes, {len(new_entries)} nouvelles entrées")
    
    # Créer un dictionnaire des nouvelles entrées
    new_entries_dict = {entry['id']: entry for entry in new_entries}
    
    # Sauvegarder les IDs existants avant le merge pour calculer les nouveaux enregistrements
    existing_ids_before_merge = set(existing_entries.keys())
    
    # Mettre à jour les entrées existantes avec les nouvelles
    for entry_id, new_entry in new_entries_dict.items():
        existing_entries[entry_id] = new_entry
    
    # Identifier les entrées supprimées (présentes dans existing mais pas dans les nouvelles)
    new_entry_ids = set(new_entries_dict.keys())
    all_existing_ids = set(existing_entries.keys())
    
    # Supprimer les entrées supprimées dans Harvest (présentes dans existing mais pas dans new_entries)
    # Filtrer par spent_date >= start_date pour ne supprimer que les entrées récentes
    deleted_ids = []
    for entry_id in existing_ids_before_merge - new_entry_ids:
        entry = existing_entries.get(entry_id)
        if entry:
            spent_date = entry.get('spent_date', '')
            # Supprimer seulement si spent_date >= start_date (entrées récentes)
            if spent_date and spent_date >= start_date:
                deleted_ids.append(entry_id)
                del existing_entries[entry_id]
    
    # Supprimer les entrées avec spent_date < start_date pour éviter la croissance indéfinie
    # Calculer start_date moins 1 jour pour la comparaison
    start_date_minus_1 = calculate_cutoff_date(start_date, days_offset=1)
    removed_old_ids = []
    for entry_id, entry in list(existing_entries.items()):
        spent_date = entry.get('spent_date', '')
        # Si la spent_date est vide ou plus ancienne que start_date - 1 jour, supprimer l'entrée
        if spent_date and spent_date < start_date_minus_1:
            removed_old_ids.append(entry_id)
            del existing_entries[entry_id]
    
    # Calculer et afficher le nombre d'enregistrements vraiment nouveaux
    new_record_count = len(new_entry_ids - existing_ids_before_merge)
    
    # Afficher les suppressions
    if deleted_ids:
        print(f"✓ {len(deleted_ids)} entrée(s) supprimée(s) dans Harvest (spent_date >= {start_date})")
    if removed_old_ids:
        print(f"✓ {len(removed_old_ids)} entrée(s) ancienne(s) supprimée(s) (spent_date < {start_date_minus_1})")
    
    print(f"Fin du merge - {len(existing_entries)} entrées après fusion")
    return existing_entries

def save_period_entries_to_s3(entries_dict, aws_config):
    """
    Sauvegarde toutes les entrées vers S3.
    Sauvegarde à la fois dans le fichier avec la date et dans harvest-data.json.
    """
    if not aws_config:
        print("Configuration AWS non trouvée, impossible de sauvegarder vers S3.")
        return False
    
    # Convertir le dictionnaire en liste triée par date de dépense (spent_date)
    entries_list = sorted(entries_dict.values(), key=lambda x: x.get('spent_date', ''))
    
    # Construire la clé S3 pour le fichier quotidien (dans le sous-dossier daily)
    today = datetime.now()
    json_filename = f"{today.strftime(DATE_FORMAT_FILENAME)}.json"
    s3_key = f"{S3_DAILY_SUBFOLDER}/{json_filename}"
    
    # Upload vers S3 avec le nom de fichier basé sur la date
    success = upload_to_s3(entries_list, s3_key, aws_config)
    
    # Upload vers S3 avec le nom harvest-data.json
    success_latest = upload_to_s3(entries_list, S3_HARVEST_DATA_FILE, aws_config)
    
    if success and success_latest:
        print(f"✓ {len(entries_list)} entrée(s) sauvegardée(s) vers S3 ({s3_key} et {S3_HARVEST_DATA_FILE})")
    
    return success and success_latest

def create_s3_client(aws_config):
    """
    Crée un client S3 selon l'environnement (Lambda ou local).
    
    Args:
        aws_config: Configuration AWS avec region, access_key_id, secret_access_key
    
    Returns:
        boto3.client: Client S3 configuré
    """
    if os.getenv('AWS_LAMBDA_FUNCTION_NAME'):
        # En Lambda, utiliser les credentials IAM du rôle (pas besoin d'access keys)
        return boto3.client('s3', region_name=aws_config['region'])
    else:
        # Mode local: utiliser les credentials fournies dans config
        return boto3.client(
            's3',
            aws_access_key_id=aws_config.get('access_key_id'),
            aws_secret_access_key=aws_config.get('secret_access_key'),
            region_name=aws_config['region']
        )

def download_from_s3(s3_key, aws_config):
    """
    Télécharge un fichier JSON depuis AWS S3.
    Retourne les données JSON ou une liste vide si le fichier n'existe pas.
    """
    try:
        # Créer le client S3
        s3_client = create_s3_client(aws_config)
        
        # Télécharger le fichier depuis S3
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
    """
    Upload des données JSON vers AWS S3.
    """
    try:
        # Créer le client S3
        s3_client = create_s3_client(aws_config)
        
        # Convertir les données en JSON
        json_data = json.dumps(data, indent=2, ensure_ascii=False)
        
        # Upload des données vers S3
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
    """
    Fonction principale pour exécuter le script.
    Peut être appelée directement ou via le handler Lambda.
    """
    # Charger la configuration
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
    
    # Calculer la plage de dates (nombre de jours configurable)
    from_date_display, to_date_display = calculate_date_range(days_back)
    
    # Récupérer les entrées de temps
    time_entries = get_time_entries(account_id, access_token, harvest_url, from_date_display, to_date_display, days_back)
        
    # Charger les entrées existantes depuis S3
    period_entries = load_period_entries_from_s3(aws_config)
    
    # Identifier et sauvegarder les changements (nouvelles, supprimées, mises à jour)
    identify_changes_and_save( period_entries.copy(), time_entries, from_date_display, aws_config )
    
    # Fusionner avec les nouvelles entrées (en passant la date de début pour la détection des suppressions)
    updated_period_entries = merge_entries(period_entries, time_entries, from_date_display)

    # Sauvegarder vers S3
    success = save_period_entries_to_s3(updated_period_entries, aws_config)
    
    # Résumé final
    summary = {
        'loaded': len(period_entries),
        'new': len(time_entries),
        'saved': len(updated_period_entries),
        'success': success
    }

    # print(f"✓ RÉSUMÉ FINAL - Chargées: {summary['loaded']}, Nouvelles: {summary['new']}, Sauvegardées: {summary['saved']}")
    return summary

