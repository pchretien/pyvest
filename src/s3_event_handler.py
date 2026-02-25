"""
Module pour la gestion des événements S3.
Contient la logique de traitement des événements S3 ObjectCreated:Put.
"""


def process_s3_event(event):
    """
    Traite un événement S3 ObjectCreated:Put.
    
    Args:
        event: Event dict contenant les informations S3
    
    Returns:
        dict: Informations extraites (bucket, key, change_type, event_name, event_time) 
              ou None si l'événement n'est pas valide
    """
    try:
        # Vérifier si c'est un événement S3
        if 'Records' not in event or not event['Records']:
            return None
        
        record = event['Records'][0]
        
        # Vérifier que c'est un événement S3
        if record.get('eventSource') != 'aws:s3':
            return None
        
        # Vérifier que c'est un événement ObjectCreated:Put
        if record.get('eventName') != 'ObjectCreated:Put':
            return None
        
        # Extraire les informations S3
        s3_info = record.get('s3', {})
        bucket_name = s3_info.get('bucket', {}).get('name')
        object_key = s3_info.get('object', {}).get('key')
        
        if not bucket_name or not object_key:
            return None
        
        # Extraire le type de changement depuis le chemin ou le nom du fichier
        change_type = None
        # D'abord, essayer de détecter depuis le chemin (changes/new/, changes/deleted/, changes/updated/)
        if '/new/' in object_key:
            change_type = 'new'
        elif '/deleted/' in object_key:
            change_type = 'deleted'
        elif '/updated/' in object_key:
            change_type = 'updated'
        else:
            # Sinon, extraire depuis le nom du fichier (format: YYYYMMDD-new-HHMMSS.json)
            filename = object_key.split('/')[-1]  # Prendre le dernier segment du chemin
            if '-new-' in filename:
                change_type = 'new'
            elif '-deleted-' in filename:
                change_type = 'deleted'
            elif '-updated-' in filename:
                change_type = 'updated'
        
        return {
            'bucket': bucket_name,
            'key': object_key,
            'change_type': change_type,
            'event_name': record.get('eventName'),
            'event_time': record.get('eventTime')
        }
    except Exception as e:
        print(f"Erreur lors du traitement de l'événement S3: {str(e)}")
        return None


def handle_s3_event(s3_event_info):
    """
    Gère un événement S3 après extraction des informations.
    
    Args:
        s3_event_info: Dict contenant les informations de l'événement S3 (bucket, key, change_type, etc.)
    
    Returns:
        dict: Résultat du traitement ou None si aucune action n'est nécessaire
    """
    if not s3_event_info:
        return None
    
    # Afficher les informations de l'événement
    print(f"Événement S3 détecté: {s3_event_info['event_name']}")
    print(f"Bucket: {s3_event_info['bucket']}, Key: {s3_event_info['key']}")
    if s3_event_info['change_type']:
        print(f"Type de changement: {s3_event_info['change_type']}")
    
    # TODO: Implémenter la logique spécifique pour traiter le fichier S3 créé
    # Par exemple : télécharger le fichier, le traiter, etc.
    
    return s3_event_info

