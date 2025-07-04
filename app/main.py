import os
import boto3
import time
import sys
import json

s3_bucket = os.environ.get("S3_BUCKET")
s3_key = os.environ.get("S3_OBJECT_KEY")
region = os.environ.get("AWS_REGION", "us-east-1")

if not s3_bucket or not s3_key:
    print("Missing S3_BUCKET or S3_OBJECT_KEY environment variables. Exiting.")
    sys.exit(1)

s3 = boto3.client("s3", region_name=region)
textract = boto3.client("textract", region_name=region)

print(f"Starting claim file processing for: s3://{s3_bucket}/{s3_key}")

local_file = "/tmp/claim_file"
try:
    s3.download_file(s3_bucket, s3_key, local_file)
    print(f"File downloaded to {local_file}")
except Exception as e:
    print(f"Error downloading file: {e}")
    sys.exit(1)

if s3_key.lower().endswith(('.pdf', '.png', '.jpg', '.jpeg')):
    print("File type supported. Calling Textract Async API...")

    try:
        response = textract.start_document_text_detection(
            DocumentLocation={"S3Object": {"Bucket": s3_bucket, "Name": s3_key}}
        )
        job_id = response["JobId"]
        print(f"Textract JobId: {job_id}")
    except Exception as e:
        print(f"Textract start error: {e}")
    sys.exit(1)

    while True:
        result = textract.get_document_text_detection(JobId=job_id)
        status = result["JobStatus"]
        print(f"Textract Status: {status}")

        if status in ["SUCCEEDED", "FAILED"]:
            break

        time.sleep(5)

    if status == "SUCCEEDED":
        # Extract only detected lines of text
        lines = []
        for block in result.get("Blocks", []):
            if block.get("BlockType") == "LINE":
                lines.append(block.get("Text", ""))

        cleaned_output = {"ExtractedTextLines": lines}

        output_key = f"processed/claims-extracted-data/{os.path.basename(s3_key)}_extracted.json"
        try:
            s3.put_object(Bucket=s3_bucket, Key=output_key, Body=json.dumps(cleaned_output))
            print(f"Cleaned Textract results saved to s3://{s3_bucket}/{output_key}")
        except Exception as e:
            print(f"Error saving results: {e}")
            sys.exit(1)
    else:
        print("Textract job failed.")
        sys.exit(1)

elif s3_key.lower().endswith('.txt'):
    print("Text file detected. Copying directly to processed folder...")
    output_key = f"processed/claims-extracted-data/{os.path.basename(s3_key)}_extracted.txt"

    try:
        s3.upload_file(local_file, s3_bucket, output_key)
        print(f"Text file saved to s3://{s3_bucket}/{output_key}")
    except Exception as e:
        print(f"Error saving text file: {e}")
        sys.exit(1)

else:
    print("Unsupported file type. Skipping processing.")
    sys.exit(1)

print("Processing completed successfully.")
