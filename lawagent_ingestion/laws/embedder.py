from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(slots=True)
class EmbeddedBatch:
    dense: list[list[float]]
    sparse_indices: list[list[int]]
    sparse_values: list[list[float]]


class BGEM3Embedder:
    """Lazy BGE-M3 adapter for the FlagEmbedding 1.4 lexical_weights API."""

    def __init__(self, model_path: Path, device: str = "auto", batch_size: int = 32):
        import torch
        from FlagEmbedding import BGEM3FlagModel

        if device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device must be auto, cpu, or cuda")
        cuda_available = torch.cuda.is_available()
        if device == "cuda" and not cuda_available:
            raise RuntimeError("CUDA was required but no CUDA device is visible")
        self.device = "cuda" if device == "cuda" or (device == "auto" and cuda_available) else "cpu"
        self.batch_size = batch_size
        self.model = BGEM3FlagModel(
            str(model_path),
            use_fp16=self.device == "cuda",
            devices=self.device,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
            batch_size=batch_size,
            passage_max_length=512,
        )

    def encode(self, texts: Sequence[str]) -> EmbeddedBatch:
        output = self.model.encode(
            list(texts),
            batch_size=self.batch_size,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense_array = output["dense_vecs"]
        lexical_weights = output["lexical_weights"]
        if len(texts) == 1 and isinstance(lexical_weights, dict):
            lexical_weights = [lexical_weights]

        dense = [row.tolist() if hasattr(row, "tolist") else list(row) for row in dense_array]
        sparse_indices: list[list[int]] = []
        sparse_values: list[list[float]] = []
        for weights in lexical_weights:
            pairs = sorted((int(token_id), float(weight)) for token_id, weight in weights.items())
            sparse_indices.append([token_id for token_id, _ in pairs])
            sparse_values.append([weight for _, weight in pairs])
        return EmbeddedBatch(dense, sparse_indices, sparse_values)

