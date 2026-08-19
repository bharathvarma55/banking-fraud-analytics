"""
Data quality checks against stg_transactions, GE-style, implemented as SQL against DuckDB.
Rows failing any check are quarantined (with reason) rather than silently dropped or fixed in place.
"""
import duckdb

con = duckdb.connect("warehouse.db")

con.execute("""
    CREATE OR REPLACE TABLE dq_flagged AS
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY transaction_id ORDER BY transaction_dt) AS dup_rank,
        CASE WHEN merchant_category IS NULL THEN true ELSE false END AS fails_null_check,
        CASE WHEN transaction_amt < 0 THEN true ELSE false END AS fails_negative_amt_check
    FROM stg_transactions;
""")

con.execute("""
    CREATE OR REPLACE TABLE dq_quarantine_transactions AS
    SELECT
        * EXCLUDE (dup_rank, fails_null_check, fails_negative_amt_check),
        list_filter(
            [
                CASE WHEN dup_rank > 1 THEN 'duplicate_transaction_id' END,
                CASE WHEN fails_null_check THEN 'null_merchant_category' END,
                CASE WHEN fails_negative_amt_check THEN 'negative_transaction_amt' END
            ],
            x -> x IS NOT NULL
        ) AS failure_reasons
    FROM dq_flagged
    WHERE dup_rank > 1 OR fails_null_check OR fails_negative_amt_check;
""")

con.execute("""
    CREATE OR REPLACE TABLE dq_clean_transactions AS
    SELECT * EXCLUDE (dup_rank, fails_null_check, fails_negative_amt_check)
    FROM dq_flagged
    WHERE dup_rank = 1 AND NOT fails_null_check AND NOT fails_negative_amt_check;
""")

con.execute("DROP TABLE dq_flagged;")

total = con.execute("SELECT COUNT(*) FROM stg_transactions").fetchone()[0]
clean = con.execute("SELECT COUNT(*) FROM dq_clean_transactions").fetchone()[0]
quarantined = con.execute("SELECT COUNT(*) FROM dq_quarantine_transactions").fetchone()[0]

print(f"Total staged rows: {total:,}")
print(f"Clean: {clean:,}")
print(f"Quarantined: {quarantined:,}")

print("\nQuarantine breakdown by reason:")
breakdown = con.execute("""
    SELECT reason, COUNT(*) AS n
    FROM dq_quarantine_transactions, UNNEST(failure_reasons) AS t(reason)
    GROUP BY reason
    ORDER BY n DESC;
""").fetchall()
for reason, n in breakdown:
    print(f"  {reason}: {n:,}")

con.close()
