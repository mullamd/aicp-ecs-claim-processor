import os
import boto3
import sys

# Step 1: Read environment variables
s3_bucket = os.environ.get("S3_BUCKET")
s3_key = os.environ.get("S3_OBJECT_KEY")
region = os.environ.get("AWS_REGION", "us-east-1")

if not s3_bucket or not s3_key:
    print("❌ Missing required env vars. Exiting.")
    sys.exit(1)

# Step 2: Generate claim ID from filename
claim_id = os.path.splitext(os.path.basename(s3_key))[0].replace("claim_", "CLM-")

# Step 3: Initialize Textract client
textract = boto3.client("textract", region_name=region)

# Step 4: Start Textract async job with SNS callback
try:
    response = textract.start_document_text_detection(
        DocumentLocation={
            "S3Object": {
                "Bucket": s3_bucket,
                "Name": s3_key
            }
        },
        NotificationChannel={
            "SNSTopicArn": "arn:aws:sns:us-east-1:461512246753:aicp-textract-callback-topic",  # 🔁 REPLACE
            "RoleArn": "RoleArn": "arn:aws:iam::461512246753:role/TextractSNSRole"                        # 🔁 REPLACE
        },
        JobTag=claim_id
    )

    print(f"✅ Textract job started for: s3://{s3_bucket}/{s3_key}")
    print(f"📌 Job ID: {response['JobId']}")
    print("🚪 ECS exiting — Textract will send result via SNS")

except Exception as e:
    print(f"❌ Textract start failed: {str(e)}")
    sys.exit(1)
