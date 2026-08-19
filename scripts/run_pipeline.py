"""
Orchestrates the recurring pipeline steps (upload -> stage -> DQ -> features -> mart),
standing in for a scheduled trigger (AWS EventBridge -> Lambda / Airflow DAG in production).

Data generation (01_generate_data.py) is intentionally excluded - it's a one-time synthetic
seed, not part of an ongoing refresh. A real deployment's trigger is new data arriving,
not the pipeline fabricating it.
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PIPELINE_STEPS = [
    "scripts/02_upload_to_minio.py",
    "scripts/03_load_to_duckdb.py",
    "scripts/04_data_quality_checks.py",
    "scripts/05_feature_engineering.py",
    "scripts/06_modeling.py",
    "scripts/07_build_mart.py",
]

LOG_FILE = Path("pipeline_run.log")


def log(msg):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    log(f"=== Pipeline run started ({len(PIPELINE_STEPS)} steps) ===")
    run_start = time.time()

    for step in PIPELINE_STEPS:
        log(f"Running {step} ...")
        step_start = time.time()
        result = subprocess.run([sys.executable, step], capture_output=True, text=True)
        duration = time.time() - step_start

        if result.returncode != 0:
            log(f"FAILED: {step} (after {duration:.1f}s)")
            log(f"--- stderr ---\n{result.stderr}")
            log("=== Pipeline run aborted ===")
            sys.exit(1)

        log(f"OK: {step} ({duration:.1f}s)")

    total = time.time() - run_start
    log(f"=== Pipeline run completed successfully in {total:.1f}s ===")


if __name__ == "__main__":
    main()
