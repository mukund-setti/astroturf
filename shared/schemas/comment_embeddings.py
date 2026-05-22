"""Schemas for silver.comment_embeddings.

The Pydantic ``CommentEmbedding`` is the source of truth. Both the active
``comment_embedding_arrow_schema()`` (used by the delta-rs writer locally) and
``comment_embedding_struct()`` (kept for parity with the Databricks/Spark write
path) are derived from the same field-type table below — a single sync test
guards against drift.

The compound primary key is ``(comment_id, embedding_model)`` so multiple models
can coexist in the same table (see ADR-0005). The vector column is
variable-size (``pa.list_(pa.float32())`` / ``ArrayType(FloatType)``) so the
table is not locked to a single dimension; Databricks Vector Search indexes
filter by ``embedding_model`` to recover a fixed-dimension slice.
"""

from __future__ import annotations

from datetime import datetime

import pyarrow as pa
from pydantic import BaseModel, ConfigDict
from pyspark.sql import types as T


class CommentEmbedding(BaseModel):
    """One dense embedding for a single (comment_id, embedding_model) pair."""

    model_config = ConfigDict(extra="forbid")

    comment_id: str
    docket_id: str
    embedding_model: str
    embedding_dim: int
    text_hash: str
    text_source: str
    embedding_vector: list[float]
    embedded_at: datetime
    backend: str


# (arrow_type, spark_type) per field. Field order here drives both derived schemas.
_FIELD_TYPES: dict[str, tuple[pa.DataType, T.DataType]] = {
    "comment_id": (pa.string(), T.StringType()),
    "docket_id": (pa.string(), T.StringType()),
    "embedding_model": (pa.string(), T.StringType()),
    "embedding_dim": (pa.int64(), T.LongType()),
    "text_hash": (pa.string(), T.StringType()),
    "text_source": (pa.string(), T.StringType()),
    "embedding_vector": (pa.list_(pa.float32()), T.ArrayType(T.FloatType())),
    "embedded_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "backend": (pa.string(), T.StringType()),
}


def comment_embedding_arrow_schema() -> pa.Schema:
    """pyarrow schema for silver.comment_embeddings (used by the delta-rs writer)."""
    return pa.schema(
        [
            pa.field(name, arrow_t, nullable=True)
            for name, (arrow_t, _) in _FIELD_TYPES.items()
        ]
    )


def comment_embedding_struct() -> T.StructType:
    """PySpark StructType for silver.comment_embeddings (used on Databricks)."""
    return T.StructType(
        [
            T.StructField(name, spark_t, nullable=True)
            for name, (_, spark_t) in _FIELD_TYPES.items()
        ]
    )
