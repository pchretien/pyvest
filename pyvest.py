import requests
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

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
    Retourne un dictionnaire avec les IDs comme clés pour faciliter les mises à jour.
    """
    if not aws_config:
        print("Configuration AWS non trouvée, impossible de charger depuis S3.")
        return {}
    
    # Télécharger les données depuis S3
    entries = download_from_s3(s3_key, aws_config)
    
    if not entries:
        print("✓ Aucune entrée chargée depuis S3 (fichier vide ou inexistant)")
        return {}
    
    # Convertir la liste en dictionnaire avec l'ID comme clé
    entries_dict = {entry['id']: entry for entry in entries}
    print(f"✓ {len(entries_dict)} entrées chargées depuis S3")
    return entries_dict

def merge_entries(existing_entries, new_entries, start_date):
    """
    Fusionne les nouvelles entrées avec les existantes.
    Gère les mises à jour et les suppressions.
    Les suppressions ne sont détectées que pour les entrées avec spent_date >= date de début.
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
    
    # Calculer et afficher le nombre d'enregistrements vraiment nouveaux
    new_record_count = len(new_entry_ids - existing_ids_before_merge)
    print(f"✓ {new_record_count} nouveau(x) enregistrement(s) dans les nouvelles entrées")
    
    # print(f"✓ {len(new_entries)} nouvelle(s) entrée(s) traitée(s)")
    if deleted_ids:
        print(f"✓ {len(deleted_ids)} entrée(s) supprimée(s) (spent_date >= {start_date})")
    else:
        print(f"✓ Aucune entrée supprimée (toutes les entrées manquantes ont une spent_date < {start_date})")
    
    print(f"✓ Fin du merge - {len(existing_entries)} entrées après fusion")
    return existing_entries

def save_period_entries_to_s3(entries_dict, s3_key, aws_config):
    """
    Sauvegarde toutes les entrées vers S3.
    """
    if not aws_config:
        print("Configuration AWS non trouvée, impossible de sauvegarder vers S3.")
        return False
    
    print(f"✓ Sauvegarde de {len(entries_dict)} entrées vers S3")
    
    # Convertir le dictionnaire en liste triée par date de dépense (spent_date)
    entries_list = sorted(entries_dict.values(), key=lambda x: x.get('spent_date', ''))
    
    # Upload vers S3
    success = upload_to_s3(entries_list, s3_key, aws_config)
    
    if success:
        print(f"✓ {len(entries_list)} entrée(s) sauvegardée(s) vers S3")
        print(f"✓ Sauvegarde terminée - {len(entries_list)} entrées confirmées en S3")
    
    return success

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
    json_filename = f"{today.strftime('%Y%m%d')}.json"
    
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
    
    # Clé S3 pour le fichier
    s3_key = json_filename
    
    # Charger les entrées existantes depuis S3
    period_entries = load_period_entries_from_s3(s3_key, aws_config)
    
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