"""
Module principal pour le handler Lambda et l'exécution locale.
Importe toutes les fonctions depuis harvest_core.
"""

import json
from harvest_processor import handle_no_event


def lambda_handler(event, context):
    """
    Handler AWS Lambda.
    Peut être invoqué avec un événement S3 (ObjectCreated:Put) ou sans événement.

    Contextes d'invocation :
      1. Événement S3 (ObjectCreated:Put) : déclenché automatiquement par AWS lorsqu'un
         fichier de changements est déposé dans le bucket S3 (ex. changes/new/...,
         changes/deleted/..., changes/updated/...). Dans ce cas, process_s3_event extrait
         les informations du fichier déposé et handle_s3_event traite l'événement.
      2. Invocation directe sans événement S3 : déclenché manuellement (console AWS, CLI,
         test) ou sur planification (EventBridge/CloudWatch). Dans ce cas, handle_no_event
         interroge l'API Harvest, détecte les changements par rapport aux données S3 et
         met à jour harvest-data.json dans S3.

    Args:
        event: Event dict (peut être un événement S3 ou vide pour une invocation simple)
        context: Lambda context object

    Returns:
        dict: Response avec statusCode et body
    """
    # Import ici pour éviter les imports circulaires
    from s3_event_handler import process_s3_event, handle_s3_event
    
    try:
        # Vérifier si c'est un événement S3
        s3_event_info = process_s3_event(event)
        
        if s3_event_info:  # Endpoint S3 : fichier déposé dans le bucket, traitement de l'événement ObjectCreated
            # Traiter l'événement S3
            handle_s3_event(s3_event_info)
            
            # Retourner une réponse indiquant que l'événement S3 a été traité
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'S3 event processed successfully',
                    's3_event': s3_event_info
                })
            }
        else:  # Endpoint direct : invocation manuelle, planifiée ou locale, interrogation de l'API Harvest
            # Invocation normale (sans événement S3)
            result = handle_no_event()
            
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


# Point d'entrée pour l'exécution locale (python pyvest.py).
# Utilisé en développement ou pour tester le script hors de l'environnement Lambda.
# La configuration est lue depuis config.json (au lieu des variables d'environnement Lambda).
# Le comportement est identique à une invocation Lambda sans événement S3 :
# interrogation de l'API Harvest, détection des changements et mise à jour de S3.
if __name__ == "__main__":
    result = handle_no_event()
    if isinstance(result, dict) and 'statusCode' not in result:
        print(f"Résultat: {result}")
