from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lawagent_ingestion.cases.pipeline import build_dry_run, index_points
from lawagent_ingestion.laws.pipeline import write_json


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Build case corpus/evaluation sets and ingest deduplicated retrieval points")
    result.add_argument("--mode", choices=("profile", "index"), default="profile")
    result.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data" / "cases")
    result.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "processed" / "cases_v0_1")
    result.add_argument("--evaluation-dir", type=Path, default=PROJECT_ROOT / "data" / "evaluation" / "cases_v0_1")
    result.add_argument("--report-dir", type=Path, default=PROJECT_ROOT / "data" / "manifests" / "cases_v0_1")
    result.add_argument("--model-path", type=Path, default=PROJECT_ROOT / "models" / "bge-m3")
    result.add_argument("--collection", default=os.getenv("CASES_COLLECTION", "cases_collection"))
    result.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"))
    result.add_argument("--device", choices=("auto", "cpu", "cuda"), default=os.getenv("DEVICE", "auto"))
    result.add_argument("--parse-workers", type=int, default=min(16, os.cpu_count() or 4))
    result.add_argument("--upload-workers", type=int, default=2)
    result.add_argument("--embed-batch-size", type=int, default=32)
    return result


def main() -> int:
    args = parser().parse_args()
    points, manifest = build_dry_run(args.data_dir, args.output_dir, args.evaluation_dir, args.report_dir, args.parse_workers)
    print(json.dumps(manifest["profile"], ensure_ascii=False, indent=2))
    if args.mode == "profile":
        print("PROFILE_ONLY: no model loaded and no Qdrant writes performed")
        return 0
    result = index_points(points, args.collection, args.qdrant_url, args.model_path, args.device, args.embed_batch_size, args.upload_workers, args.report_dir / "index_checkpoint.json")
    write_json(args.report_dir / "index_result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
