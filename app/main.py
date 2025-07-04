import os
import boto3
import time
import sys
import json

# Read environment variables
s3_bucket = os.environ.get("S3_BUCKET")
s3_key = os.environ.get("S3_OBJECT_KEY")
region = os.environ.get("AWS_REGION", "us-east-1")

if not s3_bucket or not s3_key:
    print("Missing S3_BUCKET or S3_OBJECT_KEY environment variables. Exiting.")
    sys.exit(1)

# Initialize AWS clients
s3 = boto3.client("s3", region_name=region)
textract = boto3.client("textract", region_name=region)

print(f"Starting claim file processing for: s3://{s3_bucket}/{s3_key}")

# Download the claim file
local_file = "/tmp/claim_file"
try:
    s3.download_file(s3_bucket, s3_key, local_file)
    print(f"File downloaded to {local_file}")
except Exception as e:
    print(f"Error downloading file: {e}")
    sys.exit(1)

# Check file type
if s3_key.lower().endswith(('.pdf', '.png', '.jpg', '.jpeg')):
    print("File type supported. Calling Textract Async API...")

    try:
        response = textract.start_document_text_detection(
            DocumentLocation={"S3Object": {"Bucket": s3_bucket, "Name": s3_key}}
        )
        job_id = response['JobId']
        print(f"Textract JobId: {job_id}")
    except Exception as e:
        print(f"Textract start error: {e}")
        sys.exit(1)

    # Poll for job completion
    while True:
        result = textract.get_document_text_detection(JobId=job_id)
        status = result['JobStatus']

        if status == 'SUCCEEDED':
            print("Textract job completed successfully.")
            break
        elif status == 'FAILED':
            print("Textract job failed.")
            sys.exit(1)
        else:
            time.sleep(5)

    # Process Textract result
    lines = [block['Text'] for block in result['Blocks'] if block['BlockType'] == 'LINE']

    def extract_value(keyword):
        for i, line in enumerate(lines):
            if keyword.lower() in line.lower():
                parts = line.split(":")
                if len(parts) > 1 and parts[1].strip():
                    return parts[1].strip()
                elif i + 1 < len(lines):
                    return lines[i + 1].strip()
        return ""

    claim_id = extract_value("Claim ID:")
    clean_data = {
        "claim_id": claim_id,
        "policy_number": extract_value("Policy Number:"),
        "claimant_name": extract_value("Claimant Name:"),
        "date_of_loss": extract_value("Date of Loss:"),
        "type_of_claim": extract_value("Type of Claim:"),
        "accident_location": extract_value("Accident Location:"),
        "vehicle_details": extract_value("Vehicle Details:"),
        "estimated_damage_cost": extract_value("Estimated Damage Cost:"),
        "claim_amount_requested": extract_value("Claim Amount Requested:"),
        "additional_notes": ""
    }

    # Supporting Documents and Description of Damage (multi-line)
    desc_lines = []
    docs_lines = []
    capture_desc = capture_docs = False
    for line in lines:
        if "Description of Damage:" in line:
            capture_desc = True
            continue
        if "Estimated Damage Cost:" in line:
            capture_desc = False
        if capture_desc and line.startswith("-"):
            desc_lines.append(line)

        if "Supporting Documents:" in line:
            capture_docs = True
            continue
        if "Additional Notes:" in line:
            capture_docs = False
        if capture_docs and line.startswith("-"):
            docs_lines.append(line)

    clean_data["description_of_damage"] = " ".join(desc_lines)
    clean_data["supporting_documents"] = " ".join(docs_lines)

    # Additional Notes (on second page)
    for line in lines:
        if "The insured party" in line:
            clean_data["additional_notes"] = line
            break

    # Upload clean JSON to S3 (correct path)
    output_key = f"processed/claims-extracted-data/clean-claim-{claim_id}.json"
    s3.put_object(Bucket=s3_bucket, Key=output_key, Body=json.dumps(clean_data))
    print(f"Clean claim data uploaded to s3://{s3_bucket}/{output_key}")
else:
    print("Unsupported file type.")
