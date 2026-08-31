from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer


@dataclass(frozen=True, slots=True)
class RerankItem:
    document_id: str
    text: str


class BGEReranker:
    """BGE cross-encoder adapter independent of FlagEmbedding's unstable wrapper API."""

    def __init__(
        self,
        model_path: Path,
        device: str = "auto",
        batch_size: int = 32,
        max_length: int = 512,
        use_fp16: bool = True,
    ) -> None:
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA reranker requested but torch.cuda.is_available() is false")
        self.device = torch.device(device)
        self.batch_size = batch_size
        self.max_length = max_length
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
        dtype = torch.float16 if use_fp16 and device == "cuda" else torch.float32
        self.model = AutoModelForSequenceClassification.from_pretrained(
            str(model_path), local_files_only=True, dtype=dtype,
        ).to(self.device)
        self.model.eval()

    def rank(self, query: str, candidates: Sequence[RerankItem]) -> list[tuple[str, float]]:
        if not candidates:
            return []
        scores: list[float] = []
        with torch.inference_mode():
            for start in range(0, len(candidates), self.batch_size):
                batch = candidates[start:start + self.batch_size]
                encoded = self.tokenizer(
                    [query] * len(batch), [item.text for item in batch], padding=True,
                    truncation=True, max_length=self.max_length, return_tensors="pt",
                ).to(self.device)
                logits = self.model(**encoded).logits.reshape(-1).float().cpu().tolist()
                scores.extend(float(value) for value in logits)
        if len(scores) != len(candidates):
            raise RuntimeError(f"reranker returned {len(scores)} scores for {len(candidates)} candidates")
        ranked = zip(candidates, scores, strict=True)
        return [(item.document_id, score) for item, score in sorted(ranked, key=lambda pair: pair[1], reverse=True)]
