# Data Lineage & Governance

## Purpose

This document traces every metric in the fraud analytics dashboard back to its raw source,
and records what happens to a transaction at each stage of the pipeline. In a regulated
banking context, this is what an auditor or compliance reviewer asks for first: "show me
where this number comes from and what was done to it."

## Pipeline stages

| Stage | Location | What happens | Script |
|---|---|---|---|
| 1. Source | `data_local/*.parquet` | Synthetic transaction + customer data generated with documented fraud-signal design (bursts, timing, amount patterns, geography). Not real customer data. | `scripts/01_generate_data.py` |
| 2. Raw zone | MinIO bucket `fraud-analytics-raw` (`s3://fraud-analytics-raw/raw/...`) | Immutable landing zone. Files are written once and never modified in place — this is the permanent record of what arrived. | `scripts/02_upload_to_minio.py` |
| 3. Staging | DuckDB `warehouse.db`, tables `stg_transactions` / `stg_customers` | Straight, untransformed load from the raw zone via `read_parquet()` over S3. No cleaning applied — staging is a faithful mirror of raw, including bad rows, so the quality gate has a true baseline to check against. | `scripts/03_load_to_duckdb.py` |
| 4. Quality gate | DuckDB tables `dq_clean_transactions` / `dq_quarantine_transactions` | Every row is checked against 3 rules (duplicate `transaction_id`, null `merchant_category`, negative `transaction_amt`). Rows failing any rule are **quarantined with a reason**, not silently dropped — nothing disappears without an audit trail. Only rows passing all checks proceed downstream. | `scripts/04_data_quality_checks.py` |
| 5. Features | DuckDB table `features_transactions` | SQL window functions derive velocity (`txns_last_1hr`, `txns_last_24hr`), recency (`minutes_since_last_txn`), spend behavior (`rolling_avg_amt_prior_5txns`, `amt_zscore_vs_customer_baseline`), and binary flags (`is_out_of_region`, `is_late_night`) — computed only from `dq_clean_transactions`, so features never derive from quarantined rows. | `scripts/05_feature_engineering.py` |
| 6. Model scoring | `fraud_model.joblib` (persisted model + scaler), scores computed in-memory | Logistic Regression trained on labeled features; every clean transaction receives `lr_fraud_score` (continuous) and `lr_flagged` (binary, threshold 0.90 — chosen from the precision/recall trade-off documented in `scripts/06_modeling.py`). | `scripts/06_modeling.py`, `scripts/07_build_mart.py` |
| 7. Mart | DuckDB table `fraud_mart`, exported to `exports/fraud_mart.csv` | Curated, business-ready table — the only layer downstream consumers (Power BI) are allowed to read. Combines descriptive attributes, engineered features, and model output in business-friendly column names. | `scripts/07_build_mart.py` |
| 8. Dashboard | Power BI Desktop (`.pbix`) | Reads `fraud_mart.csv`. DAX measures compute headline metrics (fraud rate, precision, recall) live, so they recalculate correctly under any filter rather than being hardcoded snapshots. Row-Level Security restricts region-level access (see below). | Power BI Desktop |

## Row-Level Security (access control)

A static RLS role (`SouthRegionAnalyst`) restricts visibility to `customer_home_region = "South"`,
validated via Power BI Desktop's "View As Role." This demonstrates the RLS mechanism, but **it is
not a full production access-control system**: real dynamic RLS maps a signed-in user's identity
(via `USERPRINCIPALNAME()`) to a permissions table, and only actually enforces once published to
the Power BI Service under a real tenant. That publish step was intentionally not done here (no
Power BI Service tenant / cost was in scope for this project) — worth stating plainly rather than
implying full production-grade access control exists.

## What's simulated vs. what would differ in a real deployment

- **No real PII**: `customer_id` values (`CUST100000`, etc.) are synthetic and carry no personal
  data. A real GDPR-scoped lineage doc would additionally need: a data subject access/erasure
  process, a documented retention period per table, and encryption-at-rest/in-transit details for
  each storage layer. None of that is implemented here since there's no real personal data to
  protect — but the pipeline's stage boundaries (raw → staging → quality-gated → mart) are exactly
  where those controls would attach in a real system.
- **Raw zone is MinIO, not AWS S3**: functionally equivalent via the same `boto3` API, but lacks
  S3's actual durability guarantees (11 nines), versioning, and lifecycle policies — those are
  managed-service features MinIO-on-a-laptop doesn't replicate.
- **Warehouse is DuckDB, not Snowflake**: same SQL dialect family, but no multi-user concurrency,
  no role-based access control at the warehouse layer (Snowflake has this natively; this project's
  only access control is the Power BI RLS layer, one level higher in the stack), and no separate
  compute/storage billing model to reason about.
- **Automation is a local Task Scheduler pattern, not cloud-native**: documented in
  `scripts/run_pipeline.py`, standing in for an EventBridge-triggered Lambda or Airflow DAG. Not
  deployed as a live recurring job (see the automation step for reasoning).

## Quarantine audit trail

Every quarantined row is preserved (not deleted) in `dq_quarantine_transactions` with a
`failure_reasons` array explaining exactly which check(s) it failed. To inspect it:

```sql
SELECT failure_reasons, COUNT(*) 
FROM dq_quarantine_transactions, UNNEST(failure_reasons) AS t(reason)
GROUP BY failure_reasons;
```
