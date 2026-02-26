"""Parsing and dispatch logic for S3 ObjectCreated:Put events."""


def process_s3_event(event):
    """Extract structured information from an S3 ObjectCreated:Put event payload.

    Args:
        event (dict): Raw Lambda event dict that may or may not be an S3 event.

    Returns:
        dict | None: Extracted fields (bucket, key, change_type, event_name,
            event_time) if the event is a valid S3 ObjectCreated:Put, else None.
    """
    try:
        if 'Records' not in event or not event['Records']:
            return None

        record = event['Records'][0]

        if record.get('eventSource') != 'aws:s3':
            return None

        if record.get('eventName') != 'ObjectCreated:Put':
            return None

        s3_info = record.get('s3', {})
        bucket_name = s3_info.get('bucket', {}).get('name')
        object_key = s3_info.get('object', {}).get('key')

        if not bucket_name or not object_key:
            return None

        # Infer change type from the S3 path first, then fall back to the filename
        change_type = None
        if '/new/' in object_key:
            change_type = 'new'
        elif '/deleted/' in object_key:
            change_type = 'deleted'
        elif '/updated/' in object_key:
            change_type = 'updated'
        else:
            # Filename format: YYYYMMDD-<change_type>-HHMMSS.json
            filename = object_key.split('/')[-1]
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
    """Handle a parsed S3 event by logging its details.

    Args:
        s3_event_info (dict | None): Structured event info as returned by
            process_s3_event, or None.

    Returns:
        dict | None: The same s3_event_info dict, or None if input was None.
    """
    if not s3_event_info:
        return None

    print(f"Événement S3 détecté: {s3_event_info['event_name']}")
    print(f"Bucket: {s3_event_info['bucket']}, Key: {s3_event_info['key']}")
    if s3_event_info['change_type']:
        print(f"Type de changement: {s3_event_info['change_type']}")

    return s3_event_info
