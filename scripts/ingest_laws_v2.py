from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lawagent_ingestion.laws.pipeline import index_chunks, parse_and_write, write_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Profile and ingest versioned Chinese law documents")
    parser.add_argument("--mode", choices=("profile", "index"), default="profile")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data" / "laws")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "processed" / "laws_v0_1")
    parser.add_argument("--report-dir", type=Path, default=PROJECT_ROOT / "data" / "manifests" / "laws_v0_1")
    parser.add_argument("--model-path", type=Path, default=PROJECT_ROOT / "models" / "bge-m3")
    parser.add_argument("--collection", default=os.getenv("LAWS_COLLECTION", "laws_collection"))
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default=os.getenv("DEVICE", "auto"))
    parser.add_argument("--parse-workers", type=int, default=min(16, os.cpu_count() or 4))
    parser.add_argument("--upload-workers", type=int, default=2)
    parser.add_argument("--embed-batch-size", type=int, default=32)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    _, chunks, manifest = parse_and_write(
        args.data_dir,
        args.output_dir,
        args.report_dir,
        parse_workers=args.parse_workers,
    )
    print(json.dumps(manifest["profile"], ensure_ascii=False, indent=2))
    if args.mode == "profile":
        print("PROFILE_ONLY: no model loaded and no Qdrant writes performed")
        return 0

    result = index_chunks(
        chunks=chunks,
        collection_name=args.collection,
        qdrant_url=args.qdrant_url,
        model_path=args.model_path,
        device=args.device,
        embed_batch_size=args.embed_batch_size,
        upload_workers=args.upload_workers,
        checkpoint_path=args.report_dir / "index_checkpoint.json",
    )
    write_json(args.report_dir / "index_result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
