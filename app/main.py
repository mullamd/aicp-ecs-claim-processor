import os
import boto3
import time
import sys
import json
import re

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
                parts = line.split(":", 1)
                if len(parts) > 1 and parts[1].strip():
                    return parts[1].strip()
                elif i + 1 < len(lines):
                    return lines[i + 1].strip()
        return "N/A"

    claim_id = extract_value("Claim ID:")
    if not claim_id or claim_id == "N/A":
        print("Error: Claim ID is missing or invalid. Skipping file.")
        sys.exit(1)

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
        "additional_notes": extract_value("Additional Notes:")
    }

    # Multi-line extraction: Damage Description and Supporting Documents
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

    clean_data["description_of_damage"] = " ".join(desc_lines) if desc_lines else "N/A"
    clean_data["supporting_documents"] = " ".join(docs_lines) if docs_lines else "N/A"

    # ✅ Step 1: Extract vehicle_year, make, model, license_plate from vehicle_details
    vehicle_details = clean_data.get("vehicle_details", "")

    vehicle_year_match = re.search(r"\b(19|20)\d{2}\b", vehicle_details)
    vehicle_make_match = re.search(r"\b\d{4}\s+(\w+)", vehicle_details)
    vehicle_model_match = re.search(r"\b\d{4}\s+\w+\s+([A-Za-z0-9\-]+)", vehicle_details)
    license_plate_match = re.search(r"License Plate\s+([A-Z0-9\-]+)", vehicle_details)

    clean_data["vehicle_year"] = vehicle_year_match.group(0) if vehicle_year_match else "N/A"
    clean_data["vehicle_make"] = vehicle_make_match.group(1) if vehicle_make_match else "N/A"
    clean_data["vehicle_model"] = vehicle_model_match.group(1) if vehicle_model_match else "N/A"
    clean_data["license_plate"] = license_plate_match.group(1) if license_plate_match else "N/A"

    # Upload clean JSON to S3
    output_key = f"processed/claims-extracted-data/clean-claim-{claim_id}.json"
    try:
        s3.put_object(Bucket=s3_bucket, Key=output_key, Body=json.dumps(clean_data))
        print(f"✅ Clean claim data uploaded to s3://{s3_bucket}/{output_key}")
    except Exception as e:
        print(f"Error uploading cleaned JSON: {e}")
else:
    print("Unsupported file type.")
