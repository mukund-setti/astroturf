"""EmbeddingAgent — silver.parsed_comments -> silver.comment_embeddings.

Reads substantive parsed comments, computes dense vector embeddings via a
pluggable ``EmbeddingBackend``, and MERGEs them into the embeddings Delta table
keyed by the compound PK ``(comment_id, embedding_model)``. See ADR-0005 for
model selection, backend abstraction, and the variable-size vector column.

Cache semantics: a candidate is re-embedded only when no row exists for its
``(comment_id, embedding_model)`` or when its ``text_hash`` differs from the
stored row. This makes re-runs cheap and lets parser updates flow through.
"""

from __future__ import annotations

import hashlib
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import mlflow
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from deltalake import DeltaTable

from shared.delta_utils.silver import ensure_schema, merge_comment_embeddings
from shared.schemas.comment_embeddings import (
    CommentEmbedding,
    comment_embedding_arrow_schema,
)

log = logging.getLogger(__name__)

DEFAULT_PARSED_PATH = "./data/silver/parsed_comments"
DEFAULT_EMBEDDINGS_PATH = "./data/silver/comment_embeddings"
DEFAULT_MODEL = "BAAI/bge-large-en-v1.5"
DEFAULT_BATCH_SIZE = 32

# text_source values that the EmbeddingAgent considers substantive (Q1 of the
# planning round). Cover notes / title-only / missing are deliberately excluded.
SUBSTANTIVE_TEXT_SOURCES: tuple[str, ...] = ("detail_comment_text", "comment_text")


@dataclass
class EmbeddingInput:
    docket_id: str
    parsed_path: str = DEFAULT_PARSED_PATH
    embeddings_path: str = DEFAULT_EMBEDDINGS_PATH
    model_name: str = DEFAULT_MODEL
    batch_size: int = DEFAULT_BATCH_SIZE
    max_rows: int | None = None
    force_reembed: bool = False


@dataclass
class EmbeddingOutput:
    docket_id: str
    rows_written: int
    metadata: dict[str, Any] = field(default_factory=dict)


class EmbeddingBackend(ABC):
    """Pluggable embedding backend. Concrete subclasses set model_name + dimension."""

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @property
    @abstractmethod
    def backend_name(self) -> str: ...

    @abstractmethod
    def encode(self, texts: list[str]) -> list[list[float]]:
        """Return one unit-norm float32 vector per input string."""


class LocalSentenceTransformerBackend(EmbeddingBackend):
    """Local PyTorch / Hugging Face backend via ``sentence-transformers``.

    The model is loaded lazily on first ``encode`` so module import stays cheap
    and tests that only touch the ABC don't pull in torch.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model: Any = None
        self._dimension: int | None = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer

        log.info("Loading SentenceTransformer model: %s", self._model_name)
        self._model = SentenceTransformer(self._model_name)
        self._dimension = int(self._model.get_sentence_embedding_dimension())
        log.info("Loaded model %s with dimension=%d", self._model_name, self._dimension)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        self._ensure_loaded()
        assert self._dimension is not None
        return self._dimension

    @property
    def backend_name(self) -> str:
        return "local_sentence_transformer"

    def encode(self, texts: list[str]) -> list[list[float]]:
        self._ensure_loaded()
        vectors = self._model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [v.astype(np.float32).tolist() for v in vectors]


class DatabricksFoundationModelBackend(EmbeddingBackend):
    """Production stub for Databricks Foundation Model API routing (ADR-0005).

    Constructor takes ``dimension`` so the stub is constructible in environments
    without a live endpoint. ``encode`` is unimplemented until Databricks
    deployment.
    """

    def __init__(
        self,
        model_name: str = "databricks-bge-large-en",
        dimension: int = 1024,
    ) -> None:
        self._model_name = model_name
        self._dimension = dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def backend_name(self) -> str:
        return "databricks_foundation_model"

    def encode(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            "DatabricksFoundationModelBackend.encode is a stub; implement during "
            "Databricks deployment per ADR-0005."
        )


class MockBackend(EmbeddingBackend):
    """Deterministic unit-norm mock backend for tests.

    Per ADR-0005: hash text -> seed numpy.random.default_rng -> standard normal
    -> L2-normalize. Output dimension is fully configurable so tests can verify
    that nothing hardcodes 1024.
    """

    def __init__(
        self,
        model_name: str = "mock-bge-large",
        dimension: int = 1024,
    ) -> None:
        self._model_name = model_name
        self._dimension = dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def backend_name(self) -> str:
        return "mock"

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [self._encode_one(t) for t in texts]

    def _encode_one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], "big", signed=False)
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self._dimension).astype(np.float32)
        norm = float(np.linalg.norm(v))
        if norm == 0.0:
            return v.tolist()
        return (v / norm).tolist()


class EmbeddingAgent:
    """Compute embeddings for substantive parsed comments and MERGE to silver."""

    def __init__(
        self,
        backend: EmbeddingBackend,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.backend = backend
        self.config = config or {}

    def run(self, inputs: EmbeddingInput) -> EmbeddingOutput:
        start_time = time.monotonic()

        log.info(
            "Starting EmbeddingAgent for docket=%s, parsed=%s, embeddings=%s, model=%s",
            inputs.docket_id,
            inputs.parsed_path,
            inputs.embeddings_path,
            self.backend.model_name,
        )

        if not DeltaTable.is_deltatable(inputs.parsed_path):
            raise FileNotFoundError(
                f"Parsed-comments Delta table not found at {inputs.parsed_path}. "
                "Run the parser first."
            )

        # Migrate the embeddings table to the current schema before any read or
        # MERGE so older runs without optional columns still work.
        ensure_schema(
            inputs.embeddings_path,
            comment_embedding_arrow_schema(),
            allow_destructive=True,
        )

        candidates = self._load_candidates(inputs)
        candidate_count = len(candidates)
        log.info("Loaded %d substantive candidates", candidate_count)

        if inputs.max_rows is not None:
            candidates = candidates[: inputs.max_rows]
            log.info(
                "Truncated to max_rows=%d (was %d)", inputs.max_rows, candidate_count
            )

        existing_hash_by_id = self._load_existing_hashes(
            inputs.embeddings_path, self.backend.model_name
        )

        skipped_corrupt = 0
        skipped_cache_hit = 0
        to_embed: list[dict[str, Any]] = []
        for row in candidates:
            comment_id = row.get("comment_id")
            raw_text = row.get("raw_text")
            text_hash = row.get("normalized_text_hash")

            if (
                raw_text is None
                or not isinstance(raw_text, str)
                or raw_text.strip() == ""
                or text_hash is None
            ):
                log.warning(
                    "Skipping comment_id=%s: parse_status='parsed' but raw_text/hash "
                    "is empty or None (text_source=%s)",
                    comment_id,
                    row.get("text_source"),
                )
                skipped_corrupt += 1
                continue

            if not inputs.force_reembed:
                existing = existing_hash_by_id.get(comment_id)
                if existing == text_hash:
                    skipped_cache_hit += 1
                    continue

            to_embed.append(row)

        log.info(
            "After cache + corruption filtering: %d to embed (%d cache hits, %d corrupt)",
            len(to_embed),
            skipped_cache_hit,
            skipped_corrupt,
        )

        rows_written = 0
        new_count = 0
        stale_count = 0
        now = datetime.now(timezone.utc)
        embedded_count = 0

        if to_embed:
            for batch_start in range(0, len(to_embed), inputs.batch_size):
                batch = to_embed[batch_start : batch_start + inputs.batch_size]
                texts = [r["raw_text"] for r in batch]
                vectors = self.backend.encode(texts)
                if len(vectors) != len(batch):
                    raise RuntimeError(
                        f"Backend returned {len(vectors)} vectors for "
                        f"{len(batch)} inputs"
                    )

                embed_rows: list[CommentEmbedding] = []
                for row, vector in zip(batch, vectors):
                    if len(vector) != self.backend.dimension:
                        raise RuntimeError(
                            f"Backend returned vector of length {len(vector)} "
                            f"but reports dimension={self.backend.dimension}"
                        )
                    is_stale = row["comment_id"] in existing_hash_by_id
                    if is_stale:
                        stale_count += 1
                    else:
                        new_count += 1
                    embed_rows.append(
                        CommentEmbedding(
                            comment_id=row["comment_id"],
                            docket_id=row["docket_id"],
                            embedding_model=self.backend.model_name,
                            embedding_dim=self.backend.dimension,
                            text_hash=row["normalized_text_hash"],
                            text_source=row["text_source"],
                            embedding_vector=vector,
                            embedded_at=now,
                            backend=self.backend.backend_name,
                        )
                    )

                arrow_batch = _rows_to_arrow(embed_rows)
                metrics = merge_comment_embeddings(inputs.embeddings_path, arrow_batch)
                rows_written += metrics["inserted"] + metrics["updated"]
                embedded_count += len(embed_rows)
                log.info(
                    "Embedded batch %d-%d (inserted=%d, updated=%d)",
                    batch_start,
                    batch_start + len(batch),
                    metrics["inserted"],
                    metrics["updated"],
                )

        duration = time.monotonic() - start_time

        with mlflow.start_run(run_name=f"embedding-{inputs.docket_id}"):
            mlflow.log_param("docket_id", inputs.docket_id)
            mlflow.log_param("parsed_path", inputs.parsed_path)
            mlflow.log_param("embeddings_path", inputs.embeddings_path)
            mlflow.log_param("embedding_model", self.backend.model_name)
            mlflow.log_param("embedding_dim", self.backend.dimension)
            mlflow.log_param("backend", self.backend.backend_name)
            mlflow.log_param("batch_size", inputs.batch_size)
            mlflow.log_param("force_reembed", inputs.force_reembed)
            mlflow.log_param("max_rows", inputs.max_rows)

            mlflow.log_metric("candidates_total", candidate_count)
            mlflow.log_metric("skipped_cache_hit", skipped_cache_hit)
            mlflow.log_metric("skipped_corrupt", skipped_corrupt)
            mlflow.log_metric("embedded_count", embedded_count)
            mlflow.log_metric("new_count", new_count)
            mlflow.log_metric("stale_reembedded_count", stale_count)
            mlflow.log_metric("rows_written", rows_written)
            mlflow.log_metric("duration_seconds", duration)

        log.info(
            "EmbeddingAgent run complete. Candidates=%d, CacheHits=%d, Corrupt=%d, "
            "Embedded=%d (new=%d, stale=%d), Written=%d, Duration=%.2fs",
            candidate_count,
            skipped_cache_hit,
            skipped_corrupt,
            embedded_count,
            new_count,
            stale_count,
            rows_written,
            duration,
        )

        return EmbeddingOutput(
            docket_id=inputs.docket_id,
            rows_written=rows_written,
            metadata={
                "candidates_total": candidate_count,
                "skipped_cache_hit": skipped_cache_hit,
                "skipped_corrupt": skipped_corrupt,
                "embedded_count": embedded_count,
                "new_count": new_count,
                "stale_reembedded_count": stale_count,
                "rows_written": rows_written,
                "duration_seconds": duration,
                "embedding_model": self.backend.model_name,
                "embedding_dim": self.backend.dimension,
                "backend": self.backend.backend_name,
            },
        )

    def _load_candidates(self, inputs: EmbeddingInput) -> list[dict[str, Any]]:
        """Read parsed_comments and filter to substantive rows for this docket.

        Corruption checks (None / empty text) are deferred to the agent loop so
        anomalies surface in a log warning rather than being silently dropped.
        """
        parsed_table = DeltaTable(inputs.parsed_path).to_pyarrow_table()
        filtered = parsed_table.filter(
            (pc.field("docket_id") == inputs.docket_id)
            & pc.field("text_source").isin(list(SUBSTANTIVE_TEXT_SOURCES))
            & (pc.field("parse_status") == "parsed")
        )
        return filtered.select(
            [
                "comment_id",
                "docket_id",
                "text_source",
                "raw_text",
                "normalized_text_hash",
            ]
        ).to_pylist()

    def _load_existing_hashes(
        self, embeddings_path: str, model_name: str
    ) -> dict[str, str]:
        """Return {comment_id: text_hash} for rows already embedded with model_name."""
        if not DeltaTable.is_deltatable(embeddings_path):
            return {}
        table = DeltaTable(embeddings_path).to_pyarrow_table()
        if table.num_rows == 0:
            return {}
        filtered = table.filter(pc.field("embedding_model") == model_name)
        result: dict[str, str] = {}
        for row in filtered.select(["comment_id", "text_hash"]).to_pylist():
            cid = row.get("comment_id")
            h = row.get("text_hash")
            if cid is not None and h is not None:
                result[cid] = h
        return result


def _rows_to_arrow(rows: list[CommentEmbedding]) -> pa.Table:
    schema = comment_embedding_arrow_schema()
    columns: dict[str, list[Any]] = {name: [] for name in schema.names}
    for row in rows:
        d = row.model_dump()
        for name in columns:
            columns[name].append(d[name])
    return pa.Table.from_pydict(columns, schema=schema)
