# PyVest - Harvest Time Tracking Exporter

Exports Harvest time entries and saves them to AWS S3. Runs locally or as an AWS Lambda function.

## Features

- Fetches time entries from the Harvest API for a configurable number of days back (default: 90)
- Detects new, updated, and deleted entries by comparing against existing S3 data
- Saves daily snapshots and a rolling `harvest-data.json` to S3
- Saves change files (`new`, `deleted`, `updated`) to `changes/` locally and in S3
- Supports S3-triggered events (`ObjectCreated:Put`)
- Uses IAM role credentials in Lambda; explicit AWS keys locally

## Project Structure

```
pyvest.py               # Lambda handler entry point + local runner
harvest_processor.py    # Core logic: API fetch, merge, S3 read/write, change detection
s3_event_handler.py     # Handles S3 ObjectCreated:Put events
create-lambda-package.py # Builds the Lambda deployment ZIP
config-sample.json      # Configuration template for local usage
config.json             # Local configuration (not committed)
requirements.txt        # Python dependencies
```

## Local Usage

### Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Copy and fill in `config.json`:
```json
{
    "account_id": "YOUR_HARVEST_ACCOUNT_ID",
    "access_token": "YOUR_HARVEST_ACCESS_TOKEN",
    "harvest_url": "https://api.harvestapp.com/v2/time_entries",
    "days_back": 21,
    "aws": {
        "access_key_id": "YOUR_AWS_ACCESS_KEY_ID",
        "secret_access_key": "YOUR_AWS_SECRET_ACCESS_KEY",
        "region": "us-east-1",
        "bucket_name": "your-bucket-name"
    }
}
```

3. Run:
```bash
python pyvest.py
```

## AWS Lambda Deployment

### Prerequisites

- AWS account with access to Lambda, S3, and IAM
- Harvest Account ID and Personal Access Token

### Step 1: Create S3 Bucket

Create a bucket in your preferred region (e.g., `harvest-dump`).

### Step 2: Create IAM Role

Create a Lambda execution role (`PyVestLambdaRole`) with:
- `AWSLambdaBasicExecutionRole` (AWS managed)
- A custom policy granting S3 access to your bucket:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["s3:PutObject", "s3:GetObject"],
            "Resource": "arn:aws:s3:::your-bucket-name/*"
        },
        {
            "Effect": "Allow",
            "Action": ["s3:ListBucket"],
            "Resource": "arn:aws:s3:::your-bucket-name"
        }
    ]
}
```

### Step 3: Build the Deployment Package

```bash
python create-lambda-package.py
```

This creates `pyvest-lambda.zip` containing the code and dependencies.

### Step 4: Create the Lambda Function

In AWS Console > Lambda > Create function:
- **Runtime**: Python 3.11+
- **Execution role**: `PyVestLambdaRole`
- **Handler**: `pyvest.lambda_handler`
- Upload `pyvest-lambda.zip`

### Step 5: Set Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `HARVEST_ACCOUNT_ID` | Yes | — | Harvest Account ID |
| `HARVEST_ACCESS_TOKEN` | Yes | — | Harvest Personal Access Token |
| `S3_BUCKET_NAME` | Yes | — | S3 bucket name |
| `HARVEST_URL` | No | `https://api.harvestapp.com/v2/time_entries` | Harvest API URL |
| `DAYS_BACK` | No | `90` | Days of history to fetch |

To find your Harvest credentials: Harvest Dashboard > Settings > Personal API Access.

### Step 6: Configure Runtime Settings

- **Timeout**: 5 minutes (300s)
- **Memory**: 512 MB

### Step 7: Schedule with EventBridge (optional)

Add an EventBridge trigger with schedule expression `cron(0 2 * * ? *)` to run daily at 2am UTC.

### Test

Invoke with an empty event `{}` via the Lambda console Test tab, or via CLI:
```bash
aws lambda invoke --function-name pyvest-harvest-export --payload '{}' response.json
```

## S3 Data Structure

```
harvest-data.json           # Latest full export (rolling, sorted by spent_date)
daily/YYYYMMDD.json         # Daily snapshot
changes/new/YYYYMMDD-new-HHMMSS.json
changes/deleted/YYYYMMDD-deleted-HHMMSS.json
changes/updated/YYYYMMDD-updated-HHMMSS.json
```

## Updating Lambda Code

```bash
python create-lambda-package.py
aws lambda update-function-code --function-name pyvest-harvest-export --zip-file fileb://pyvest-lambda.zip
```

## Monitoring

Lambda logs are available in CloudWatch Logs under `/aws/lambda/pyvest-harvest-export`.
