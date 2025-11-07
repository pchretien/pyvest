"""
Module principal pour le handler Lambda et l'exécution locale.
Importe toutes les fonctions depuis harvest_core.
"""

import json
from harvest_processor import main


def lambda_handler(event, context):
    """
    Handler AWS Lambda.
    Peut être invoqué avec un événement S3 (ObjectCreated:Put) ou sans événement.
    
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
        
        if s3_event_info:
            # Traiter l'événement S3
            handle_s3_event(s3_event_info)
            
            # Pour l'instant, on exécute le traitement normal
            # TODO: Implémenter la logique spécifique pour traiter le fichier S3 créé
            result = main()
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'S3 event processed successfully',
                    's3_event': s3_event_info,
                    'summary': result if isinstance(result, dict) and 'statusCode' not in result else {}
                })
            }
        else:
            # Invocation normale (sans événement S3)
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
