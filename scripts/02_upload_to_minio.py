"""
Uploads locally generated parquet files to the MinIO "raw zone" bucket.
This mirrors the S3 raw-landing-zone pattern: ingestion and transformation stay decoupled.
"""
import os
import boto3
from dotenv import load_dotenv

load_dotenv()

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT_URL"],
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    region_name=os.environ["AWS_REGION"],
)

BUCKET = "fraud-analytics-raw"

files_to_upload = {
    "data_local/transactions_2026_06.parquet": "raw/transactions/2026_06/transactions_2026_06.parquet",
    "data_local/customers.parquet": "raw/customers/customers.parquet",
}

for local_path, s3_key in files_to_upload.items():
    s3.upload_file(local_path, BUCKET, s3_key)
    print(f"Uploaded {local_path} -> s3://{BUCKET}/{s3_key}")

print("\nBucket contents:")
resp = s3.list_objects_v2(Bucket=BUCKET)
for obj in resp.get("Contents", []):
    print(f"  {obj['Key']}  ({obj['Size']:,} bytes)")
