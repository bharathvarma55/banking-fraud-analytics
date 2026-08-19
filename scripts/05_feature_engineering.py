"""
SQL feature engineering against dq_clean_transactions using window functions.
Verifies the burst-fraud fix by checking fraud vs non-fraud separation on velocity features.
"""
import duckdb

con = duckdb.connect("warehouse.db")

con.execute("""
    CREATE OR REPLACE TABLE features_transactions AS
    SELECT
        transaction_id,
        customer_id,
        product_line,
        transaction_dt,
        transaction_amt,
        card_type,
        merchant_category,
        merchant_region,
        customer_home_region,
        merchant_distance_miles,
        is_fraud,

        -- velocity features
        COUNT(*) OVER (
            PARTITION BY customer_id ORDER BY transaction_dt
            RANGE BETWEEN INTERVAL 1 HOUR PRECEDING AND CURRENT ROW
        ) - 1 AS txns_last_1hr,

        COUNT(*) OVER (
            PARTITION BY customer_id ORDER BY transaction_dt
            RANGE BETWEEN INTERVAL 24 HOUR PRECEDING AND CURRENT ROW
        ) - 1 AS txns_last_24hr,

        DATE_DIFF(
            'minute',
            LAG(transaction_dt) OVER (PARTITION BY customer_id ORDER BY transaction_dt),
            transaction_dt
        ) AS minutes_since_last_txn,

        -- rolling spend behavior
        AVG(transaction_amt) OVER (
            PARTITION BY customer_id ORDER BY transaction_dt
            ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
        ) AS rolling_avg_amt_prior_5txns,

        (transaction_amt - AVG(transaction_amt) OVER (PARTITION BY customer_id))
            / NULLIF(STDDEV(transaction_amt) OVER (PARTITION BY customer_id), 0)
            AS amt_zscore_vs_customer_baseline,

        -- binary flags
        CASE WHEN merchant_region != customer_home_region THEN 1 ELSE 0 END AS is_out_of_region,
        CASE WHEN EXTRACT(HOUR FROM transaction_dt) IN (0,1,2,3,4) THEN 1 ELSE 0 END AS is_late_night

    FROM dq_clean_transactions;
""")

print("Velocity feature separation: fraud vs non-fraud (mean values)\n")
result = con.execute("""
    SELECT
        is_fraud,
        COUNT(*) AS n,
        ROUND(AVG(txns_last_1hr), 3) AS avg_txns_last_1hr,
        ROUND(AVG(txns_last_24hr), 3) AS avg_txns_last_24hr,
        ROUND(AVG(minutes_since_last_txn), 1) AS avg_minutes_since_last_txn,
        ROUND(AVG(is_late_night), 3) AS pct_late_night,
        ROUND(AVG(is_out_of_region), 3) AS pct_out_of_region
    FROM features_transactions
    GROUP BY is_fraud
    ORDER BY is_fraud;
""").fetchdf()
print(result.to_string(index=False))

con.close()
