from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lawagent_ingestion.cases.validation import validate_cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only integrity, privacy, leakage and traceability validation for cases-v0.1")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data" / "cases")
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_ROOT / "data" / "processed" / "cases_v0_1")
    parser.add_argument("--evaluation-dir", type=Path, default=PROJECT_ROOT / "data" / "evaluation" / "cases_v0_1")
    parser.add_argument("--report-dir", type=Path, default=PROJECT_ROOT / "data" / "manifests" / "cases_v0_1")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--collection", default=os.getenv("CASES_COLLECTION", "cases_collection"))
    parser.add_argument("--vector-sample-size", type=int, default=1024)
    args = parser.parse_args()
    report = validate_cases(args.data_dir, args.processed_dir, args.evaluation_dir, args.report_dir, args.qdrant_url, args.collection, args.vector_sample_size)
    print(json.dumps({key: report[key] for key in ("status", "privacy_review_status", "counts", "deterministic_failures", "pii_regex_counts")}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
