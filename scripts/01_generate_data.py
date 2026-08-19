"""
Generates ~500K synthetic banking transactions across 3 product lines.

Fraud is NOT random noise - it's built from real fraud signal patterns:
  - Geography: fraud transactions have higher merchant-customer distance
  - Timing: fraud skews toward late-night hours (12am-4am)
  - Amount: fraud amounts cluster at round numbers + occasional high outliers
  - Burst velocity: fraud accounts fire several transactions in quick succession
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

np.random.seed(42)

N_CUSTOMERS = 45_000
N_LEGIT_TRANSACTIONS = 483_000
N_FRAUD_BURSTS = 3_500       # each burst = one fraud "event" with multiple transactions
FRAUD_BURST_SIZE_RANGE = (2, 6)  # a burst fires 2-6 transactions rapidly

PRODUCT_LINES = ["Retail Checking", "Credit Card", "Personal Loan"]
REGIONS = ["Northeast", "Midwest", "South", "West"]
MERCHANT_CATEGORIES = [
    "Grocery", "Gas Station", "Restaurant", "Online Retail", "Electronics",
    "Travel", "Utilities", "Healthcare", "Entertainment", "ATM Withdrawal"
]
CARD_TYPES = ["Visa Debit", "Visa Credit", "Mastercard Debit", "Mastercard Credit", "Amex"]

customers = pd.DataFrame({
    "customer_id": [f"CUST{100000+i}" for i in range(N_CUSTOMERS)],
    "home_region": np.random.choice(REGIONS, N_CUSTOMERS, p=[0.22, 0.21, 0.35, 0.22]),
    "product_line": np.random.choice(PRODUCT_LINES, N_CUSTOMERS, p=[0.5, 0.35, 0.15]),
    "avg_txn_amt": np.round(np.random.gamma(3, 40, N_CUSTOMERS), 2),
})

start_date = datetime(2026, 6, 1)
rows = []
txn_counter = 1_000_000

# ---- legitimate transactions ----
for i in range(N_LEGIT_TRANSACTIONS):
    cust = customers.iloc[np.random.randint(0, N_CUSTOMERS)]
    day_offset = np.random.randint(0, 30)
    hour_weights = np.array([3.0 if 8 <= h <= 21 else 0.5 for h in range(24)])
    hour = np.random.choice(range(24), p=hour_weights / hour_weights.sum())
    minute = np.random.randint(0, 60)
    txn_dt = start_date + timedelta(days=int(day_offset), hours=int(hour), minutes=int(minute))

    amt = round(max(1, np.random.normal(cust.avg_txn_amt, cust.avg_txn_amt * 0.3)), 2)
    merchant_region = cust.home_region if np.random.random() < 0.85 else np.random.choice(REGIONS)
    merchant_cat = np.random.choice(MERCHANT_CATEGORIES, p=[0.2,0.15,0.15,0.15,0.08,0.05,0.1,0.05,0.05,0.02])
    dist = 0 if merchant_region == cust.home_region else round(np.random.uniform(200, 2500), 1)

    txn_counter += 1
    rows.append((f"TXN{txn_counter}", cust.customer_id, cust.product_line, txn_dt, amt,
                 np.random.choice(CARD_TYPES), merchant_cat, merchant_region, cust.home_region, dist, 0))

# ---- fraud bursts: this is what gives velocity features real signal ----
for i in range(N_FRAUD_BURSTS):
    cust = customers.iloc[np.random.randint(0, N_CUSTOMERS)]
    burst_size = np.random.randint(*FRAUD_BURST_SIZE_RANGE)
    day_offset = np.random.randint(0, 30)
    hour = np.random.choice(range(24), p=(lambda w: w/w.sum())(np.array([3.0 if h in [0,1,2,3,4] else 1.0 for h in range(24)])))
    burst_start = start_date + timedelta(days=int(day_offset), hours=int(hour), minutes=int(np.random.randint(0,60)))

    for j in range(burst_size):
        txn_dt = burst_start + timedelta(minutes=int(np.random.randint(1, 15)) * j)
        pattern = np.random.choice(["micro", "outlier", "round"], p=[0.3, 0.4, 0.3])
        if pattern == "micro":
            amt = round(np.random.uniform(1, 5), 2)
        elif pattern == "outlier":
            amt = round(np.random.uniform(cust.avg_txn_amt*3, cust.avg_txn_amt*8), 2)
        else:
            amt = float(np.random.choice([100, 200, 500, 1000, 1500]))

        merchant_region = np.random.choice(REGIONS)
        merchant_cat = np.random.choice(MERCHANT_CATEGORIES, p=[0.05,0.05,0.05,0.35,0.15,0.15,0.02,0.03,0.1,0.05])
        dist = 0 if merchant_region == cust.home_region else round(np.random.uniform(200, 2500), 1)

        txn_counter += 1
        rows.append((f"TXN{txn_counter}", cust.customer_id, cust.product_line, txn_dt, amt,
                     np.random.choice(CARD_TYPES), merchant_cat, merchant_region, cust.home_region, dist, 1))

df = pd.DataFrame(rows, columns=[
    "transaction_id", "customer_id", "product_line", "transaction_dt", "transaction_amt",
    "card_type", "merchant_category", "merchant_region", "customer_home_region",
    "merchant_distance_miles", "is_fraud"
])

# inject realistic data quality issues on purpose - so our quality checks later have something to catch
dupe_idx = np.random.choice(df.index, 250, replace=False)
df = pd.concat([df, df.loc[dupe_idx]], ignore_index=True)
null_idx = np.random.choice(df.index, 400, replace=False)
df.loc[null_idx, "merchant_category"] = None
neg_idx = np.random.choice(df.index, 60, replace=False)
df.loc[neg_idx, "transaction_amt"] = -df.loc[neg_idx, "transaction_amt"]

df = df.sample(frac=1, random_state=1).reset_index(drop=True)

import os
os.makedirs("data_local", exist_ok=True)
df.to_parquet("data_local/transactions_2026_06.parquet", index=False)
customers.to_parquet("data_local/customers.parquet", index=False)

print(f"Generated {len(df):,} transactions for {N_CUSTOMERS:,} customers")
print(f"Fraud rate: {df['is_fraud'].mean():.2%}")
print(f"Fraud bursts created: {N_FRAUD_BURSTS:,}")