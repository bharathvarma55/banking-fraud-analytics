"""
Loads raw parquet files from MinIO (S3-compatible) into DuckDB as the staging layer.
Mirrors a Snowflake `COPY INTO ... FROM @stage` pattern: warehouse ingests only through
the raw zone, never from local files directly.
"""
import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

con = duckdb.connect("warehouse.db")

con.execute("INSTALL httpfs;")
con.execute("LOAD httpfs;")

con.execute(f"""
    SET s3_endpoint='{os.environ["S3_ENDPOINT_URL"].replace("http://", "").replace("https://", "")}';
    SET s3_access_key_id='{os.environ["AWS_ACCESS_KEY_ID"]}';
    SET s3_secret_access_key='{os.environ["AWS_SECRET_ACCESS_KEY"]}';
    SET s3_region='{os.environ["AWS_REGION"]}';
    SET s3_use_ssl=false;
    SET s3_url_style='path';
""")

con.execute("""
    CREATE OR REPLACE TABLE stg_transactions AS
    SELECT * FROM read_parquet('s3://fraud-analytics-raw/raw/transactions/2026_06/transactions_2026_06.parquet');
""")

con.execute("""
    CREATE OR REPLACE TABLE stg_customers AS
    SELECT * FROM read_parquet('s3://fraud-analytics-raw/raw/customers/customers.parquet');
""")

txn_count = con.execute("SELECT COUNT(*) FROM stg_transactions").fetchone()[0]
cust_count = con.execute("SELECT COUNT(*) FROM stg_customers").fetchone()[0]
fraud_rate = con.execute("SELECT AVG(is_fraud) FROM stg_transactions").fetchone()[0]

print(f"stg_transactions: {txn_count:,} rows")
print(f"stg_customers: {cust_count:,} rows")
print(f"fraud rate in staging: {fraud_rate:.2%}")

con.close()
