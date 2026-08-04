from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lawagent_evaluation.cases import CaseRetrievalEvaluator, TRACK_FILES, run_tracks


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Case-to-Case, Template-to-Case and User-to-Case retrieval")
    parser.add_argument("--evaluation-dir", type=Path, default=PROJECT_ROOT / "data" / "evaluation" / "cases_v0_1")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "evaluation" / "cases_v0_1" / "runs" / "bge_m3_v0_1")
    parser.add_argument("--model-path", type=Path, default=PROJECT_ROOT / "models" / "bge-m3")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--collection", default=os.getenv("CASES_COLLECTION", "cases_collection"))
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default=os.getenv("DEVICE", "auto"))
    parser.add_argument("--tracks", nargs="+", choices=tuple(TRACK_FILES), default=list(TRACK_FILES))
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument("--ks", type=int, nargs="+", default=[5, 10])
    parser.add_argument("--embed-batch-size", type=int, default=32)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    evaluator = CaseRetrievalEvaluator(args.qdrant_url, args.collection, args.model_path, args.device, args.embed_batch_size)
    summary = run_tracks(args.evaluation_dir, args.output_dir, args.tracks, evaluator, args.candidate_k, args.ks, args.limit)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
