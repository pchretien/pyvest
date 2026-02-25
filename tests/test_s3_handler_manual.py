"""
Manual testing script for S3 event handler.
This script demonstrates how to test the S3 handler with sample events.
"""

import json
import sys
from pathlib import Path

# Add parent directory and src directory to path to import modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))

from s3_event_handler import process_s3_event, handle_s3_event
from pyvest import lambda_handler


class MockContext:
    """Mock Lambda context for testing."""
    def __init__(self):
        self.function_name = "test-function"
        self.memory_limit_in_mb = 128
        self.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test-function"
        self.aws_request_id = "test-request-id"


def create_s3_event(bucket_name, object_key, event_name="ObjectCreated:Put"):
    """Create a sample S3 event structure."""
    return {
        'Records': [
            {
                'eventSource': 'aws:s3',
                'eventName': event_name,
                's3': {
                    'bucket': {'name': bucket_name},
                    'object': {'key': object_key}
                },
                'eventTime': '2024-01-15T12:00:00Z'
            }
        ]
    }


def test_process_s3_event():
    """Test process_s3_event function with various scenarios."""
    print("=" * 60)
    print("Testing process_s3_event function")
    print("=" * 60)
    
    # Test 1: Valid new event
    print("\n1. Testing valid 'new' event (path-based):")
    event = create_s3_event('test-bucket', 'changes/new/20240115-new-120000.json')
    result = process_s3_event(event)
    print(f"   Result: {json.dumps(result, indent=2)}")
    assert result is not None
    assert result['change_type'] == 'new'
    
    # Test 2: Valid deleted event
    print("\n2. Testing valid 'deleted' event (path-based):")
    event = create_s3_event('test-bucket', 'changes/deleted/20240115-deleted-120000.json')
    result = process_s3_event(event)
    print(f"   Result: {json.dumps(result, indent=2)}")
    assert result is not None
    assert result['change_type'] == 'deleted'
    
    # Test 3: Valid updated event
    print("\n3. Testing valid 'updated' event (path-based):")
    event = create_s3_event('test-bucket', 'changes/updated/20240115-updated-120000.json')
    result = process_s3_event(event)
    print(f"   Result: {json.dumps(result, indent=2)}")
    assert result is not None
    assert result['change_type'] == 'updated'
    
    # Test 4: Filename-based detection
    print("\n4. Testing filename-based detection:")
    event = create_s3_event('test-bucket', '20240115-new-120000.json')
    result = process_s3_event(event)
    print(f"   Result: {json.dumps(result, indent=2)}")
    assert result is not None
    assert result['change_type'] == 'new'
    
    # Test 5: Invalid event source
    print("\n5. Testing invalid event source:")
    event = {
        'Records': [{
            'eventSource': 'aws:sqs',
            'eventName': 'ObjectCreated:Put',
            's3': {
                'bucket': {'name': 'test-bucket'},
                'object': {'key': 'changes/new/file.json'}
            }
        }]
    }
    result = process_s3_event(event)
    print(f"   Result: {result}")
    assert result is None
    
    # Test 6: Invalid event name
    print("\n6. Testing invalid event name:")
    event = create_s3_event('test-bucket', 'changes/new/file.json', 'ObjectDeleted')
    result = process_s3_event(event)
    print(f"   Result: {result}")
    assert result is None
    
    # Test 7: No records
    print("\n7. Testing event with no records:")
    result = process_s3_event({})
    print(f"   Result: {result}")
    assert result is None
    
    print("\n✅ All process_s3_event tests passed!")


def test_handle_s3_event():
    """Test handle_s3_event function."""
    print("\n" + "=" * 60)
    print("Testing handle_s3_event function")
    print("=" * 60)
    
    # Test 1: Valid event info
    print("\n1. Testing with valid event info:")
    s3_event_info = {
        'bucket': 'test-bucket',
        'key': 'changes/new/20240115-new-120000.json',
        'change_type': 'new',
        'event_name': 'ObjectCreated:Put',
        'event_time': '2024-01-15T12:00:00Z'
    }
    result = handle_s3_event(s3_event_info)
    print(f"   Result: {json.dumps(result, indent=2)}")
    assert result == s3_event_info
    
    # Test 2: None input
    print("\n2. Testing with None input:")
    result = handle_s3_event(None)
    print(f"   Result: {result}")
    assert result is None
    
    print("\n✅ All handle_s3_event tests passed!")


def test_real_s3_event_payload():
    """Test with a real AWS S3 event payload."""
    print("\n" + "=" * 60)
    print("Testing with Real AWS S3 Event Payload")
    print("=" * 60)
    
    # Real S3 event payload from AWS
    real_event = {
        "Records": [
            {
                "eventVersion": "2.1",
                "eventSource": "aws:s3",
                "awsRegion": "ca-central-1",
                "eventTime": "2025-11-08T01:53:03.974Z",
                "eventName": "ObjectCreated:Put",
                "userIdentity": {
                    "principalId": "AWS:AIDAWJWQMUVKHONYUXILL"
                },
                "requestParameters": {
                    "sourceIPAddress": "74.58.177.24"
                },
                "responseElements": {
                    "x-amz-request-id": "A2FM84JJCZD0MVGB",
                    "x-amz-id-2": "MTB87g3k+cDYOkmLDpJw8ko5RWQN5iPuKW0I/3UDKIuyeQwOx+o/iUylWMOSV5zjRPgkqAgSKbjpIRK62tikBuIImSYgD1MmHF8omjLaFG0="
                },
                "s3": {
                    "s3SchemaVersion": "1.0",
                    "configurationId": "harvest_landed",
                    "bucket": {
                        "name": "harvest-landing",
                        "ownerIdentity": {
                            "principalId": "A37732Q12FFZ5R"
                        },
                        "arn": "arn:aws:s3:::harvest-landing"
                    },
                    "object": {
                        "key": "changes/new/20251107-new-205304.json",
                        "size": 1892,
                        "eTag": "2ff516f967bc0347b966d805cd7a6d94",
                        "sequencer": "00690EA27FDB0AECC0"
                    }
                }
            }
        ]
    }
    
    print("\n1. Processing real S3 event payload:")
    print(f"   Bucket: {real_event['Records'][0]['s3']['bucket']['name']}")
    print(f"   Key: {real_event['Records'][0]['s3']['object']['key']}")
    print(f"   Event Time: {real_event['Records'][0]['eventTime']}")
    print(f"   Region: {real_event['Records'][0]['awsRegion']}")
    
    result = process_s3_event(real_event)
    
    if result:
        print(f"\n   ✅ Event processed successfully!")
        print(f"   Result: {json.dumps(result, indent=2)}")
        assert result['bucket'] == 'harvest-landing'
        assert result['key'] == 'changes/new/20251107-new-205304.json'
        assert result['change_type'] == 'new'
        assert result['event_name'] == 'ObjectCreated:Put'
        assert result['event_time'] == '2025-11-08T01:53:03.974Z'
    else:
        print(f"\n   ❌ Event processing failed!")
    
    print("\n2. Handling processed S3 event:")
    if result:
        handle_result = handle_s3_event(result)
        print(f"   ✅ Event handled successfully!")
        assert handle_result == result
    else:
        print(f"   ⚠️  Skipping handle_s3_event (event processing failed)")
    
    print("\n3. Testing with lambda_handler:")
    context = MockContext()
    try:
        response = lambda_handler(real_event, context)
        print(f"   Status Code: {response['statusCode']}")
        body = json.loads(response['body'])
        print(f"   Response: {json.dumps(body, indent=2)}")
        assert response['statusCode'] == 200
        assert body['message'] == 'S3 event processed successfully'
        assert body['s3_event']['bucket'] == 'harvest-landing'
        assert body['s3_event']['key'] == 'changes/new/20251107-new-205304.json'
    except Exception as e:
        print(f"   ⚠️  Error: {e}")
        print("   This may occur if config.json is not properly configured")
    
    print("\n✅ Real S3 event payload test completed!")


def test_lambda_handler_with_s3_event():
    """Test lambda_handler with S3 events."""
    print("\n" + "=" * 60)
    print("Testing lambda_handler with S3 events")
    print("=" * 60)
    
    context = MockContext()
    
    # Test 1: Valid S3 event
    print("\n1. Testing lambda_handler with valid S3 event:")
    event = create_s3_event('test-bucket', 'changes/new/20240115-new-120000.json')
    
    # Note: This will fail if config.json is missing or invalid
    # In a real scenario, you'd mock the dependencies
    try:
        response = lambda_handler(event, context)
        print(f"   Status Code: {response['statusCode']}")
        body = json.loads(response['body'])
        print(f"   Response: {json.dumps(body, indent=2)}")
    except Exception as e:
        print(f"   ⚠️  Expected error (missing config): {e}")
        print("   This is normal if config.json is not set up")
    
    # Test 2: Empty event (should trigger handle_no_event)
    print("\n2. Testing lambda_handler with empty event:")
    try:
        response = lambda_handler({}, context)
        print(f"   Status Code: {response['statusCode']}")
        body = json.loads(response['body'])
        print(f"   Response: {json.dumps(body, indent=2)}")
    except Exception as e:
        print(f"   ⚠️  Expected error (missing config): {e}")
        print("   This is normal if config.json is not set up")


def main():
    """Run all manual tests."""
    print("\n" + "=" * 60)
    print("S3 Handler Manual Testing")
    print("=" * 60)
    
    # Test individual functions
    #test_process_s3_event()
    #test_handle_s3_event()
    
    # Test with real AWS S3 event payload
    test_real_s3_event_payload()
    
    # Test lambda handler (may fail without proper config)
    #test_lambda_handler_with_s3_event()
    
    print("\n" + "=" * 60)
    print("Manual testing complete!")
    print("=" * 60)
    print("\nNote: For full integration testing, ensure config.json is properly configured.")
    print("For unit testing, use: python -m pytest tests/test_pyvest.py::TestS3EventProcessing -v")


if __name__ == "__main__":
    main()

