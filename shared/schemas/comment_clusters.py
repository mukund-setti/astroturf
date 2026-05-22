"""Schemas for gold.comment_clusters and gold.comment_cluster_memberships.

The Pydantic models are the source of truth. Arrow schemas support local
delta-rs writes, while Spark StructTypes keep parity with the future Databricks
write path.
"""

from __future__ import annotations

from datetime import datetime

import pyarrow as pa
from pydantic import BaseModel, ConfigDict
from pyspark.sql import types as T


class CommentCluster(BaseModel):
    """One detected connected-component cluster for a docket/model run."""

    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    clustering_run_id: str
    docket_id: str
    embedding_model: str
    embedding_backend: str
    clustering_version: str
    similarity_threshold: float
    candidate_count: int
    cluster_size: int
    representative_comment_id: str
    representative_text_hash: str
    mean_similarity: float
    min_similarity: float
    max_similarity: float
    created_at: datetime
    updated_at: datetime


class CommentClusterMembership(BaseModel):
    """One comment's membership in a detected cluster."""

    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    comment_id: str
    clustering_run_id: str
    docket_id: str
    embedding_model: str
    embedding_backend: str
    clustering_version: str
    similarity_threshold: float
    text_hash: str
    text_source: str
    similarity_to_representative: float
    membership_rank: int
    created_at: datetime
    updated_at: datetime


_CLUSTER_FIELD_TYPES: dict[str, tuple[pa.DataType, T.DataType]] = {
    "cluster_id": (pa.string(), T.StringType()),
    "clustering_run_id": (pa.string(), T.StringType()),
    "docket_id": (pa.string(), T.StringType()),
    "embedding_model": (pa.string(), T.StringType()),
    "embedding_backend": (pa.string(), T.StringType()),
    "clustering_version": (pa.string(), T.StringType()),
    "similarity_threshold": (pa.float64(), T.DoubleType()),
    "candidate_count": (pa.int64(), T.LongType()),
    "cluster_size": (pa.int64(), T.LongType()),
    "representative_comment_id": (pa.string(), T.StringType()),
    "representative_text_hash": (pa.string(), T.StringType()),
    "mean_similarity": (pa.float64(), T.DoubleType()),
    "min_similarity": (pa.float64(), T.DoubleType()),
    "max_similarity": (pa.float64(), T.DoubleType()),
    "created_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "updated_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
}

_MEMBERSHIP_FIELD_TYPES: dict[str, tuple[pa.DataType, T.DataType]] = {
    "cluster_id": (pa.string(), T.StringType()),
    "comment_id": (pa.string(), T.StringType()),
    "clustering_run_id": (pa.string(), T.StringType()),
    "docket_id": (pa.string(), T.StringType()),
    "embedding_model": (pa.string(), T.StringType()),
    "embedding_backend": (pa.string(), T.StringType()),
    "clustering_version": (pa.string(), T.StringType()),
    "similarity_threshold": (pa.float64(), T.DoubleType()),
    "text_hash": (pa.string(), T.StringType()),
    "text_source": (pa.string(), T.StringType()),
    "similarity_to_representative": (pa.float64(), T.DoubleType()),
    "membership_rank": (pa.int64(), T.LongType()),
    "created_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "updated_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
}


def comment_cluster_arrow_schema() -> pa.Schema:
    """pyarrow schema for gold.comment_clusters."""
    return pa.schema(
        [
            pa.field(name, arrow_t, nullable=True)
            for name, (arrow_t, _) in _CLUSTER_FIELD_TYPES.items()
        ]
    )


def comment_cluster_membership_arrow_schema() -> pa.Schema:
    """pyarrow schema for gold.comment_cluster_memberships."""
    return pa.schema(
        [
            pa.field(name, arrow_t, nullable=True)
            for name, (arrow_t, _) in _MEMBERSHIP_FIELD_TYPES.items()
        ]
    )


def comment_cluster_struct() -> T.StructType:
    """PySpark StructType for gold.comment_clusters."""
    return T.StructType(
        [
            T.StructField(name, spark_t, nullable=True)
            for name, (_, spark_t) in _CLUSTER_FIELD_TYPES.items()
        ]
    )


def comment_cluster_membership_struct() -> T.StructType:
    """PySpark StructType for gold.comment_cluster_memberships."""
    return T.StructType(
        [
            T.StructField(name, spark_t, nullable=True)
            for name, (_, spark_t) in _MEMBERSHIP_FIELD_TYPES.items()
        ]
    )
