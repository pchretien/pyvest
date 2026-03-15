"""Lambda handler entry point and local execution runner."""

import argparse
import json
from harvest_processor import run_harvest_pipeline
from s3_event_handler import process_s3_event, handle_s3_event


def lambda_handler(event, context):
    """Handle an AWS Lambda invocation with either an S3 event or no event.

    Args:
        event (dict): Lambda event payload — either an S3 ObjectCreated:Put
            record or an empty dict for a direct invocation.
        context (LambdaContext): Lambda runtime context object.

    Returns:
        dict: Response with statusCode and JSON body.
    """
    try:
        s3_event_info = process_s3_event(event)

        if s3_event_info:
            handle_s3_event(s3_event_info)
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'S3 event processed successfully',
                    's3_event': s3_event_info
                })
            }
        else:
            # No S3 event: run the full Harvest data export pipeline
            summary = run_harvest_pipeline()
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Harvest data export completed successfully',
                    'summary': summary
                })
            }
    except ValueError as e:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': str(e)})
        }
    except Exception as e:
        print(f"Error during execution: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--local', action='store_true', help='Read and write from local harvest_landing/ instead of S3')
    args = parser.parse_args()
    result = run_harvest_pipeline(local=args.local)
    print(f"Result: {result}")
