import requests
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

# Global constants for file paths and naming
S3_HARVEST_DATA_FILE = "harvest-data.json"
S3_DAILY_SUBFOLDER = "daily"
S3_CHANGES_SUBFOLDER = "changes"
LOCAL_CHANGES_FOLDER = "changes"
DATE_FORMAT_FILENAME = '%Y%m%d'
TIME_FORMAT_FILENAME = '%H%M%S'
CHANGES_FILE_PATTERNS = {
    'new': '-new-',
    'deleted': '-deleted-',
    'updated': '-updated-'
}
MAX_CHANGES_ENTRIES_DISPLAYED = 100

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
            'days_back': int(os.getenv('DAYS_BACK', '90')),
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
        
        # Vérifier le paramètre days_back (optionnel, défaut 90)
        if 'days_back' not in config:
            config['days_back'] = 90
            print("Paramètre 'days_back' non trouvé, utilisation de la valeur par défaut: 90 jours")
        
        # Vérifier la configuration AWS (optionnelle)
        if 'aws' in config:
            aws_config = config['aws']
            required_aws_fields = ['access_key_id', 'secret_access_key', 'region', 'bucket_name']
            for field in required_aws_fields:
                if field not in aws_config:
                    print(f"Attention: Configuration AWS incomplète. Le champ '{field}' est manquant.")
        
        return config
    except FileNotFoundError:
        print(f"Erreur: Le fichier {config_file} n'existe pas.")
        print("Créez un fichier config.json avec le format suivant:")
        print(json.dumps({
            "account_id": "VOTRE_ACCOUNT_ID",
            "access_token": "VOTRE_ACCESS_TOKEN",
            "harvest_url": "https://api.harvestapp.com/v2/time_entries",
            "days_back": 90,
            "aws": {
                "access_key_id": "VOTRE_ACCESS_KEY_ID",
                "secret_access_key": "VOTRE_SECRET_ACCESS_KEY",
                "region": "us-east-1",
                "bucket_name": "votre-bucket-name"
            }
        }, indent=2))
        exit(1)
    except json.JSONDecodeError:
        print(f"Erreur: Le fichier {config_file} n'est pas un JSON valide.")
        exit(1)

def get_time_entries(account_id, access_token, harvest_url, from_date, to_date):
    """
    Récupère toutes les entrées de temps depuis l'API Harvest pour une plage de dates donnée.
    Gère la pagination pour récupérer toutes les pages de résultats.
    """
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
        "per_page": 2000  # Maximum entries per page
    }
    
    try:
        while True:
            # print(f"Récupération de la page {page}...")
            
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            time_entries = data.get('time_entries', [])
            
            if not time_entries:
                break
            
            all_entries.extend(time_entries)
            # print(f"✓ {len(time_entries)} entrées récupérées de la page {page}")
            
            # Vérifier s'il y a une page suivante
            total_pages = data.get('total_pages', 1)
            if page >= total_pages:
                break
            
            page += 1
            params['page'] = page
        
        print(f"✓ Total: {len(all_entries)} entrées récupérées sur {page} page(s)")
        return all_entries
    
    except requests.exceptions.RequestException as e:
        print(f"Erreur lors de la requête API: {e}")
        exit(1)

def load_period_entries_from_s3(s3_key, aws_config):
    """
    Charge les entrées existantes depuis S3.
    Charge depuis harvest-data.json.
    Retourne un dictionnaire avec les IDs comme clés pour faciliter les mises à jour.
    """
    if not aws_config:
        print("Configuration AWS non trouvée, impossible de charger depuis S3.")
        return {}
    
    # Télécharger les données depuis S3 (depuis harvest-data.json)
    entries = download_from_s3(S3_HARVEST_DATA_FILE, aws_config)
    
    if not entries:
        print(f"✓ Aucune entrée chargée depuis S3 (fichier {S3_HARVEST_DATA_FILE} vide ou inexistant)")
        return {}
    
    # Convertir la liste en dictionnaire avec l'ID comme clé
    entries_dict = {entry['id']: entry for entry in entries}
    print(f"✓ {len(entries_dict)} entrées chargées depuis S3 ({S3_HARVEST_DATA_FILE})")
    return entries_dict

def format_time_entry(entry):
    """
    Formate une time entry pour l'affichage en extrayant les champs spécifiés.
    
    Args:
        entry: Dictionnaire représentant une time entry
    
    Returns:
        str: Chaîne formatée avec les champs demandés
    """
    user_name = entry.get('user', {}).get('name', 'N/A') if entry.get('user') else 'N/A'
    client_name = entry.get('client', {}).get('name', 'N/A') if entry.get('client') else 'N/A'
    project_name = entry.get('project', {}).get('name', 'N/A') if entry.get('project') else 'N/A'
    task_name = entry.get('task', {}).get('name', 'N/A') if entry.get('task') else 'N/A'
    hours = entry.get('hours', 'N/A')
    spent_date = entry.get('spent_date', 'N/A')
    notes = entry.get('notes', '') or '(vide)'
    
    return (f"  User: {user_name}, Client: {client_name}, Project: {project_name}, "
            f"Task: {task_name}, Hours: {hours}, Date: {spent_date}, Notes: {notes}")

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
    
    # Identifier les nouvelles entrées (présentes dans new_entries mais pas dans existing)
    new_entries_list = [entry for entry_id, entry in new_entries_dict.items() 
                       if entry_id not in existing_ids]
    
    # Identifier les entrées supprimées (présentes dans existing mais pas dans new_entries)
    # Filtrer par spent_date >= start_date
    deleted_entries_list = []
    for entry_id in existing_ids - new_entry_ids:
        entry = existing_entries[entry_id]
        spent_date = entry.get('spent_date', '')
        if spent_date and spent_date >= start_date:
            deleted_entries_list.append(entry)
    
    # Identifier les entrées mises à jour (présentes dans les deux mais modifiées)
    updated_entries_list = []
    for entry_id in existing_ids & new_entry_ids:
        existing_entry = existing_entries[entry_id]
        new_entry = new_entries_dict[entry_id]
        
        # Comparer les updated_at pour détecter les changements
        existing_updated = existing_entry.get('updated_at', '')
        new_updated = new_entry.get('updated_at', '')
        
        # Si updated_at a changé, c'est une mise à jour
        if existing_updated != new_updated:
            updated_entries_list.append(new_entry)
    
    # Fonction pour trier par updated_at (plus récent en premier) et prendre les N premiers
    def get_newest_entries(entries, limit=MAX_CHANGES_ENTRIES_DISPLAYED):
        """Trie les entrées par updated_at (décroissant) et retourne les limit premières."""
        # Trier par updated_at en ordre décroissant (plus récent en premier)
        # Les entrées sans updated_at sont placées en dernier
        sorted_entries = sorted(
            entries,
            key=lambda x: x.get('updated_at', '') or '',
            reverse=True
        )
        return sorted_entries[:limit]
    
    # Afficher les trois listes (seulement les N plus récentes)
    print("\n" + "="*60)
    print("RÉSUMÉ DES CHANGEMENTS")
    print("="*60)
    print(f"Nouvelles entrées: {len(new_entries_list)}")
    if new_entries_list:
        newest_new = get_newest_entries(new_entries_list, MAX_CHANGES_ENTRIES_DISPLAYED)
        for entry in newest_new:
            print(format_time_entry(entry))
        if len(new_entries_list) > MAX_CHANGES_ENTRIES_DISPLAYED:
            print(f"  ... et {len(new_entries_list) - MAX_CHANGES_ENTRIES_DISPLAYED} autre(s) entrée(s) non affichée(s)")
    
    print(f"\nEntrées supprimées: {len(deleted_entries_list)}")
    if deleted_entries_list:
        newest_deleted = get_newest_entries(deleted_entries_list, MAX_CHANGES_ENTRIES_DISPLAYED)
        for entry in newest_deleted:
            print(format_time_entry(entry))
        if len(deleted_entries_list) > MAX_CHANGES_ENTRIES_DISPLAYED:
            print(f"  ... et {len(deleted_entries_list) - MAX_CHANGES_ENTRIES_DISPLAYED} autre(s) entrée(s) non affichée(s)")
    
    print(f"\nEntrées mises à jour: {len(updated_entries_list)}")
    if updated_entries_list:
        newest_updated = get_newest_entries(updated_entries_list, MAX_CHANGES_ENTRIES_DISPLAYED)
        for entry in newest_updated:
            print(format_time_entry(entry))
        if len(updated_entries_list) > MAX_CHANGES_ENTRIES_DISPLAYED:
            print(f"  ... et {len(updated_entries_list) - MAX_CHANGES_ENTRIES_DISPLAYED} autre(s) entrée(s) non affichée(s)")
    print("="*60 + "\n")
    
    # Générer le nom de fichier avec date et heure
    now = datetime.now()
    date_str = now.strftime(DATE_FORMAT_FILENAME)
    time_str = now.strftime(TIME_FORMAT_FILENAME)
    
    # Vérifier si on est en mode local (pas Lambda)
    is_local = not os.getenv('AWS_LAMBDA_FUNCTION_NAME')
    
    # Créer le dossier pour sauvegarder les fichiers (seulement en local)
    if is_local:
        output_folder = LOCAL_CHANGES_FOLDER
        os.makedirs(output_folder, exist_ok=True)
    
    # Sauvegarder les nouvelles entrées
    if new_entries_list:
        # Sauvegarder sur disque seulement en local
        if is_local:
            new_filename = os.path.join(output_folder, f"{date_str}{CHANGES_FILE_PATTERNS['new']}{time_str}.json")
            with open(new_filename, 'w', encoding='utf-8') as f:
                json.dump(new_entries_list, f, indent=2, ensure_ascii=False)
            print(f"✓ Fichier sauvegardé: {new_filename} ({len(new_entries_list)} entrées)")
        
        # Sauvegarder dans S3
        if aws_config:
            s3_key = f"{S3_CHANGES_SUBFOLDER}/{date_str}{CHANGES_FILE_PATTERNS['new']}{time_str}.json"
            if upload_to_s3(new_entries_list, s3_key, aws_config):
                print(f"✓ Fichier uploadé vers S3: s3://{aws_config['bucket_name']}/{s3_key}")
    
    # Sauvegarder les entrées supprimées
    if deleted_entries_list:
        # Sauvegarder sur disque seulement en local
        if is_local:
            deleted_filename = os.path.join(output_folder, f"{date_str}{CHANGES_FILE_PATTERNS['deleted']}{time_str}.json")
            with open(deleted_filename, 'w', encoding='utf-8') as f:
                json.dump(deleted_entries_list, f, indent=2, ensure_ascii=False)
            print(f"✓ Fichier sauvegardé: {deleted_filename} ({len(deleted_entries_list)} entrées)")
        
        # Sauvegarder dans S3
        if aws_config:
            s3_key = f"{S3_CHANGES_SUBFOLDER}/{date_str}{CHANGES_FILE_PATTERNS['deleted']}{time_str}.json"
            if upload_to_s3(deleted_entries_list, s3_key, aws_config):
                print(f"✓ Fichier uploadé vers S3: s3://{aws_config['bucket_name']}/{s3_key}")
    
    # Sauvegarder les entrées mises à jour
    if updated_entries_list:
        # Sauvegarder sur disque seulement en local
        if is_local:
            updated_filename = os.path.join(output_folder, f"{date_str}{CHANGES_FILE_PATTERNS['updated']}{time_str}.json")
            with open(updated_filename, 'w', encoding='utf-8') as f:
                json.dump(updated_entries_list, f, indent=2, ensure_ascii=False)
            print(f"✓ Fichier sauvegardé: {updated_filename} ({len(updated_entries_list)} entrées)")
        
        # Sauvegarder dans S3
        if aws_config:
            s3_key = f"{S3_CHANGES_SUBFOLDER}/{date_str}{CHANGES_FILE_PATTERNS['updated']}{time_str}.json"
            if upload_to_s3(updated_entries_list, s3_key, aws_config):
                print(f"✓ Fichier uploadé vers S3: s3://{aws_config['bucket_name']}/{s3_key}")
    
    if not new_entries_list and not deleted_entries_list and not updated_entries_list:
        print("ℹ Aucun changement détecté, aucun fichier créé.")
    
    return new_entries_list, deleted_entries_list, updated_entries_list

def merge_entries(existing_entries, new_entries, start_date):
    """
    Fusionne les nouvelles entrées avec les existantes.
    Gère les mises à jour et les suppressions.
    Les suppressions ne sont détectées que pour les entrées avec spent_date >= date de début.
    Supprime également les entrées avec spent_date < start_date pour éviter la croissance indéfinie.
    """
    print(f"✓ Début du merge - {len(existing_entries)} entrées existantes, {len(new_entries)} nouvelles entrées")
    
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
    potentially_deleted_ids = all_existing_ids - new_entry_ids
    
    # Filtrer les suppressions : seulement les entrées avec spent_date >= date de début
    deleted_ids = []
    for entry_id in potentially_deleted_ids:
        entry = existing_entries[entry_id]
        spent_date = entry.get('spent_date', '')
        
        # Vérifier si l'entrée a une spent_date >= date de début
        if spent_date and spent_date >= start_date:
            deleted_ids.append(entry_id)
            del existing_entries[entry_id]
    
    # Supprimer les entrées avec spent_date < start_date pour éviter la croissance indéfinie
    # Calculer start_date moins 2 jours pour la comparaison
    start_date_minus_1 = (datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
    removed_old_ids = []
    for entry_id, entry in list(existing_entries.items()):
        spent_date = entry.get('spent_date', '')
        # Si la spent_date est vide ou plus ancienne que start_date - 2 jours, supprimer l'entrée
        if spent_date and spent_date < start_date_minus_1:
            removed_old_ids.append(entry_id)
            del existing_entries[entry_id]
    
    # Calculer et afficher le nombre d'enregistrements vraiment nouveaux
    new_record_count = len(new_entry_ids - existing_ids_before_merge)
    print(f"✓ {new_record_count} nouveau(x) enregistrement(s) dans les nouvelles entrées")
    
    # print(f"✓ {len(new_entries)} nouvelle(s) entrée(s) traitée(s)")
    if deleted_ids:
        print(f"✓ {len(deleted_ids)} entrée(s) supprimée(s) (spent_date >= {start_date})")
    else:
        print(f"✓ Aucune entrée supprimée (toutes les entrées manquantes ont une spent_date < {start_date})")
    
    if removed_old_ids:
        print(f"✓ {len(removed_old_ids)} entrée(s) ancienne(s) supprimée(s) (spent_date < {start_date_minus_1})")
    
    print(f"✓ Fin du merge - {len(existing_entries)} entrées après fusion")
    return existing_entries

def save_period_entries_to_s3(entries_dict, s3_key, aws_config):
    """
    Sauvegarde toutes les entrées vers S3.
    Sauvegarde à la fois dans le fichier avec la date et dans harvest-data.json.
    """
    if not aws_config:
        print("Configuration AWS non trouvée, impossible de sauvegarder vers S3.")
        return False
    
    print(f"✓ Sauvegarde de {len(entries_dict)} entrées vers S3")
    
    # Convertir le dictionnaire en liste triée par date de dépense (spent_date)
    entries_list = sorted(entries_dict.values(), key=lambda x: x.get('spent_date', ''))
    
    # Upload vers S3 avec le nom de fichier basé sur la date
    success = upload_to_s3(entries_list, s3_key, aws_config)
    
    # Upload vers S3 avec le nom harvest-data.json
    success_latest = upload_to_s3(entries_list, S3_HARVEST_DATA_FILE, aws_config)
    
    if success and success_latest:
        print(f"✓ {len(entries_list)} entrée(s) sauvegardée(s) vers S3 ({s3_key} et {S3_HARVEST_DATA_FILE})")
        print(f"✓ Sauvegarde terminée - {len(entries_list)} entrées confirmées en S3")
    
    return success and success_latest

def download_from_s3(s3_key, aws_config):
    """
    Télécharge un fichier JSON depuis AWS S3.
    Retourne les données JSON ou une liste vide si le fichier n'existe pas.
    """
    try:
        # Créer le client S3
        # En Lambda, utiliser les credentials IAM du rôle (pas besoin d'access keys)
        if os.getenv('AWS_LAMBDA_FUNCTION_NAME'):
            s3_client = boto3.client('s3', region_name=aws_config['region'])
        else:
            # Mode local: utiliser les credentials fournies dans config
            s3_client = boto3.client(
                's3',
                aws_access_key_id=aws_config.get('access_key_id'),
                aws_secret_access_key=aws_config.get('secret_access_key'),
                region_name=aws_config['region']
            )
        
        # Télécharger le fichier depuis S3
        response = s3_client.get_object(Bucket=aws_config['bucket_name'], Key=s3_key)
        content = response['Body'].read().decode('utf-8')
        data = json.loads(content)
        
        print(f"✓ Fichier téléchargé depuis S3: s3://{aws_config['bucket_name']}/{s3_key}")
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
        # En Lambda, utiliser les credentials IAM du rôle (pas besoin d'access keys)
        if os.getenv('AWS_LAMBDA_FUNCTION_NAME'):
            s3_client = boto3.client('s3', region_name=aws_config['region'])
        else:
            # Mode local: utiliser les credentials fournies dans config
            s3_client = boto3.client(
                's3',
                aws_access_key_id=aws_config.get('access_key_id'),
                aws_secret_access_key=aws_config.get('secret_access_key'),
                region_name=aws_config['region']
            )
        
        # Convertir les données en JSON
        json_data = json.dumps(data, indent=2, ensure_ascii=False)
        
        # Upload des données vers S3
        s3_client.put_object(
            Bucket=aws_config['bucket_name'],
            Key=s3_key,
            Body=json_data,
            ContentType='application/json'
        )
        
        print(f"✓ Données uploadées vers S3: s3://{aws_config['bucket_name']}/{s3_key}")
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


def main():
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
    
    # Calculer la plage de dates (nombre de jours configurable)
    today = datetime.now()
    from_date_display = (today - timedelta(days=days_back)).strftime('%Y-%m-%d')
    to_date_display = today.strftime('%Y-%m-%d')
    
    # Nom du fichier JSON (format YYYYMMDD)
    json_filename = f"{today.strftime(DATE_FORMAT_FILENAME)}.json"
    
    print(f"Récupération des entrées de temps du {from_date_display} au {to_date_display} ({days_back} derniers jours)...")
    
    # Récupérer les entrées de temps
    time_entries = get_time_entries(account_id, access_token, harvest_url, from_date_display, to_date_display)
    
    # Configuration AWS requise
    aws_config = config.get('aws')
    if not aws_config:
        print("Configuration AWS requise pour le fonctionnement du script.")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Configuration AWS requise'})
        }
    
    # Clé S3 pour le fichier (dans le sous-dossier daily)
    s3_key = f"{S3_DAILY_SUBFOLDER}/{json_filename}"
    
    # Charger les entrées existantes depuis S3
    period_entries = load_period_entries_from_s3(s3_key, aws_config)
    
    # Identifier et sauvegarder les changements (nouvelles, supprimées, mises à jour)
    new_entries_list, deleted_entries_list, updated_entries_list = identify_changes_and_save(
        period_entries.copy(), time_entries, from_date_display, aws_config
    )
    
    # Fusionner avec les nouvelles entrées (en passant la date de début pour la détection des suppressions)
    updated_period_entries = merge_entries(period_entries, time_entries, from_date_display)
    
    # Sauvegarder vers S3
    success = save_period_entries_to_s3(updated_period_entries, s3_key, aws_config)
    
    # Résumé final
    summary = {
        'loaded': len(period_entries),
        'new': len(time_entries),
        'saved': len(updated_period_entries),
        'success': success
    }
    print(f"✓ RÉSUMÉ FINAL - Chargées: {summary['loaded']}, Nouvelles: {summary['new']}, Sauvegardées: {summary['saved']}")
    
    return summary

def lambda_handler(event, context):
    """
    Handler AWS Lambda.
    
    Args:
        event: Event dict (peut être vide pour une invocation simple)
        context: Lambda context object
    
    Returns:
        dict: Response avec statusCode et body
    """
    try:
        result = main()
        
        if isinstance(result, dict) and 'statusCode' in result:
            return result
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Harvest data export completed successfully',
                'summary': result if isinstance(result, dict) else {}
            })
        }
    except ValueError as e:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': str(e)})
        }
    except Exception as e:
        print(f"Erreur lors de l'exécution: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

if __name__ == "__main__":
    result = main()
    if isinstance(result, dict) and 'statusCode' not in result:
        print(f"Résultat: {result}")