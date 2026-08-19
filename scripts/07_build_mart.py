"""
Builds fraud_mart: a curated, business-ready table combining transaction features,
descriptive attributes, and the trained model's fraud score - the only table Power BI reads from.

Threshold 0.90 chosen from the threshold sweep in 06_modeling.py: at that cutoff LR delivers
~81% precision / 83% recall, a reasonable starting operating point (revisit with real cost data).
"""
import duckdb
import pandas as pd
import numpy as np
import joblib
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression

FLAG_THRESHOLD = 0.90

con = duckdb.connect("warehouse.db")
df = con.execute("SELECT * FROM features_transactions").fetchdf()

# --- same feature prep as 06_modeling.py ---
df["minutes_since_last_txn"] = df["minutes_since_last_txn"].fillna(df["minutes_since_last_txn"].max())
df["rolling_avg_amt_prior_5txns"] = df["rolling_avg_amt_prior_5txns"].fillna(df["transaction_amt"])
df["amt_zscore_vs_customer_baseline"] = df["amt_zscore_vs_customer_baseline"].fillna(0)

numeric_features = [
    "transaction_amt", "merchant_distance_miles", "txns_last_1hr", "txns_last_24hr",
    "minutes_since_last_txn", "rolling_avg_amt_prior_5txns",
    "amt_zscore_vs_customer_baseline", "is_out_of_region", "is_late_night"
]
categorical_features = ["card_type", "merchant_category", "product_line"]

X = pd.get_dummies(df[numeric_features + categorical_features], columns=categorical_features)
y = df["is_fraud"]

# final model refit on all clean data - this is the model that ships, not the train/test split model
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)
lr = LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42)
lr.fit(X_scaled, y)

joblib.dump({"model": lr, "scaler": scaler, "columns": list(X.columns)}, "fraud_model.joblib")

df["lr_fraud_score"] = lr.predict_proba(X_scaled)[:, 1]
df["lr_flagged"] = (df["lr_fraud_score"] >= FLAG_THRESHOLD).astype(int)

df["transaction_date"] = pd.to_datetime(df["transaction_dt"]).dt.date
df["transaction_hour"] = pd.to_datetime(df["transaction_dt"]).dt.hour

mart_columns = [
    "transaction_id", "customer_id", "product_line", "transaction_dt",
    "transaction_date", "transaction_hour", "transaction_amt", "card_type",
    "merchant_category", "merchant_region", "customer_home_region",
    "merchant_distance_miles", "is_out_of_region", "is_late_night",
    "txns_last_1hr", "txns_last_24hr", "is_fraud", "lr_fraud_score", "lr_flagged"
]
mart = df[mart_columns]

con.execute("CREATE OR REPLACE TABLE fraud_mart AS SELECT * FROM mart")
con.close()

import os
os.makedirs("exports", exist_ok=True)
mart.to_csv("exports/fraud_mart.csv", index=False)

print(f"fraud_mart: {len(mart):,} rows written to warehouse.db and exports/fraud_mart.csv")
print(f"Flagged at threshold {FLAG_THRESHOLD}: {mart['lr_flagged'].sum():,} ({mart['lr_flagged'].mean():.2%})")
print(f"Actual fraud: {mart['is_fraud'].sum():,} ({mart['is_fraud'].mean():.2%})")
