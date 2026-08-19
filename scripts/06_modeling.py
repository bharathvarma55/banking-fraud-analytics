"""
Fraud modeling: Isolation Forest (unsupervised) vs Logistic Regression (supervised).
Evaluated on the same held-out labels for precision/recall/PR-AUC comparison.
"""
import duckdb
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    precision_score, recall_score, f1_score,
    average_precision_score, classification_report, confusion_matrix
)

con = duckdb.connect("warehouse.db")
df = con.execute("SELECT * FROM features_transactions").fetchdf()
con.close()

# --- feature prep ---
# minutes_since_last_txn is NULL for a customer's first transaction (no prior txn exists) -
# treat "no prior activity" as a very large gap, not zero.
df["minutes_since_last_txn"] = df["minutes_since_last_txn"].fillna(df["minutes_since_last_txn"].max())

# rolling_avg_amt_prior_5txns is NULL when a customer has no prior transactions yet -
# fall back to their own current amount (no signal available, avoid inventing one).
df["rolling_avg_amt_prior_5txns"] = df["rolling_avg_amt_prior_5txns"].fillna(df["transaction_amt"])

# amt_zscore is NULL when a customer has only one transaction (stddev undefined) -
# no deviation is measurable, so treat as baseline (0).
df["amt_zscore_vs_customer_baseline"] = df["amt_zscore_vs_customer_baseline"].fillna(0)

numeric_features = [
    "transaction_amt", "merchant_distance_miles", "txns_last_1hr", "txns_last_24hr",
    "minutes_since_last_txn", "rolling_avg_amt_prior_5txns",
    "amt_zscore_vs_customer_baseline", "is_out_of_region", "is_late_night"
]
categorical_features = ["card_type", "merchant_category", "product_line"]

X = pd.get_dummies(df[numeric_features + categorical_features], columns=categorical_features)
y = df["is_fraud"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.3, stratify=y, random_state=42
)

scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

print(f"Train: {len(X_train):,} rows ({y_train.mean():.2%} fraud)")
print(f"Test:  {len(X_test):,} rows ({y_test.mean():.2%} fraud)")

# --- Logistic Regression (supervised) ---
lr = LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42)
lr.fit(X_train_scaled, y_train)
lr_proba = lr.predict_proba(X_test_scaled)[:, 1]
lr_pred = (lr_proba >= 0.5).astype(int)

print("\n=== Logistic Regression (supervised) ===")
print(f"PR-AUC: {average_precision_score(y_test, lr_proba):.3f}")
print(classification_report(y_test, lr_pred, digits=3))
print("Confusion matrix [[TN FP] [FN TP]]:")
print(confusion_matrix(y_test, lr_pred))

# --- Isolation Forest (unsupervised, trained with NO labels) ---
fraud_rate_train = y_train.mean()
iso = IsolationForest(contamination=fraud_rate_train, random_state=42, n_estimators=200)
iso.fit(X_train_scaled)  # labels never passed in
iso_pred_raw = iso.predict(X_test_scaled)  # -1 = anomaly, 1 = normal
iso_pred = (iso_pred_raw == -1).astype(int)

print("\n=== Isolation Forest (unsupervised) ===")
print(classification_report(y_test, iso_pred, digits=3))
print("Confusion matrix [[TN FP] [FN TP]]:")
print(confusion_matrix(y_test, iso_pred))

print("\n=== Side-by-side summary (LR @ 0.5 threshold, unmatched operating points) ===")
summary = pd.DataFrame({
    "model": ["Logistic Regression", "Isolation Forest"],
    "precision": [precision_score(y_test, lr_pred), precision_score(y_test, iso_pred)],
    "recall": [recall_score(y_test, lr_pred), recall_score(y_test, iso_pred)],
    "f1": [f1_score(y_test, lr_pred), f1_score(y_test, iso_pred)],
})
print(summary.round(3).to_string(index=False))

# --- fair comparison: match LR's threshold to flag the same % as Isolation Forest ---
iso_flag_rate = iso_pred.mean()
lr_threshold_matched = np.quantile(lr_proba, 1 - iso_flag_rate)
lr_pred_matched = (lr_proba >= lr_threshold_matched).astype(int)

print(f"\n=== Fair comparison: LR threshold moved to flag same {iso_flag_rate:.2%} rate as Isolation Forest ===")
print(f"LR threshold: {lr_threshold_matched:.4f} (was 0.5)")
summary_matched = pd.DataFrame({
    "model": ["Logistic Regression (matched)", "Isolation Forest"],
    "flag_rate": [lr_pred_matched.mean(), iso_pred.mean()],
    "precision": [precision_score(y_test, lr_pred_matched), precision_score(y_test, iso_pred)],
    "recall": [recall_score(y_test, lr_pred_matched), recall_score(y_test, iso_pred)],
    "f1": [f1_score(y_test, lr_pred_matched), f1_score(y_test, iso_pred)],
})
print(summary_matched.round(3).to_string(index=False))

# --- threshold sweep: business trade-off curve for Logistic Regression ---
# In production, the threshold isn't chosen to match another model's flag rate -
# it's chosen based on the relative cost of a false positive (blocked legitimate
# transaction, customer friction, review team hours) vs a false negative (fraud loss).
print("\n=== Threshold sweep (Logistic Regression) ===")
thresholds = [0.10, 0.25, 0.40, 0.50, 0.60, 0.75, 0.90, 0.95]
rows = []
for t in thresholds:
    pred_t = (lr_proba >= t).astype(int)
    rows.append({
        "threshold": t,
        "flag_rate": pred_t.mean(),
        "precision": precision_score(y_test, pred_t, zero_division=0),
        "recall": recall_score(y_test, pred_t, zero_division=0),
        "f1": f1_score(y_test, pred_t, zero_division=0),
    })
sweep = pd.DataFrame(rows)
print(sweep.round(3).to_string(index=False))
