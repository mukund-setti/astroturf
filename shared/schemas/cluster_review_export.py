"""Schema for demo.cluster_review_export.

The Pydantic ``ClusterReviewExportRow`` is the source of truth. Both the active
``cluster_review_export_arrow_schema()`` (used by the local Parquet writer) and
``cluster_review_export_struct()`` (kept for parity with the Databricks/Spark
write path) are derived from the same field-type table below.

This table is a denormalized, UI-ready join of ``gold.comment_clusters``,
``gold.comment_cluster_memberships``, and ``silver.parsed_comments`` for one
clustering run scope (one ``docket_id`` + ``embedding_model`` +
``similarity_threshold``). One row per ``(cluster_id, comment_id)``.

It exists so the dashboard / review UI does not have to perform multi-table
joins at read time and so the Databricks Workflow's
``export_dashboard_data`` step has a stable contract.

See ADR-0009 for context.
"""

from __future__ import annotations

from datetime import datetime

import pyarrow as pa
from pydantic import BaseModel, ConfigDict
from pyspark.sql import types as T


class ClusterReviewExportRow(BaseModel):
    """One row of demo.cluster_review_export.

    Each row represents one comment's membership in one cluster, joined with
    enough cluster-level and comment-level context for a reviewer to triage
    the cluster without further table joins.
    """

    model_config = ConfigDict(extra="forbid")

    # Cluster identity / run scope (carried from gold.comment_clusters so the
    # UI can group, filter, and label rows without joining back to gold).
    cluster_id: str
    docket_id: str
    topic_id: str | None = None
    agency_id: str | None = None
    embedding_model: str
    similarity_threshold: float
    cluster_size: int
    representative_comment_id: str
    representative_text: str | None = None

    # Per-comment fields.
    comment_id: str
    member_comment_id: str | None = None
    is_representative: bool
    # text_source is propagated from membership/parsed_comments so reviewers
    # can see whether the cluster was driven by detail JSON text, attachment
    # text, fallback raw text, etc. (e.g. "detail_comment_text").
    text_source: str | None = None
    # text_preview is the joined parsed_comments text, whitespace-collapsed and
    # truncated to ~500 chars. Stored on the row so the UI can render preview
    # cards without hitting silver. Full text remains in silver.parsed_comments.
    text_preview: str | None = None
    member_text: str | None = None
    similarity: float | None = None
    submitter_name: str | None = None
    submitter_organization: str | None = None
    submitter_state: str | None = None
    submitter_country: str | None = None
    posted_date: datetime | None = None

    # ``source`` distinguishes semantic-embedding clusters from the exact-hash
    # baseline so the UI can label them differently. Values: "semantic" or
    # "exact_hash". Derived from ``embedding_backend`` in gold.comment_clusters
    # (the ``exact_hash`` baseline writer uses backend = "exact_hash").
    source: str
    exact_match_ratio: float | None = None
    near_duplicate_ratio: float | None = None
    purity_score: float | None = None
    confidence_score: float | None = None

    # Optional attribution / migration evidence — populated when AttributionAgent
    # and MigrationAgent have run for this cluster. Absence MUST NOT break
    # export or UI rendering (see ADR-0015). Values are "candidate" /
    # "evidence overlap", never causal claims.
    candidate_entity_name: str | None = None
    candidate_entity_type: str | None = None
    attribution_confidence: float | None = None
    attribution_evidence_url: str | None = None
    migration_match_type: str | None = None
    migration_section: str | None = None
    migration_similarity: float | None = None
    migration_claim_scope: str | None = None

    exported_at: datetime


# (arrow_type, spark_type) per field. Field order here drives both derived
# schemas, matching the pattern in shared/schemas/comment_clusters.py.
_FIELD_TYPES: dict[str, tuple[pa.DataType, T.DataType]] = {
    "cluster_id": (pa.string(), T.StringType()),
    "docket_id": (pa.string(), T.StringType()),
    "topic_id": (pa.string(), T.StringType()),
    "agency_id": (pa.string(), T.StringType()),
    "embedding_model": (pa.string(), T.StringType()),
    "similarity_threshold": (pa.float64(), T.DoubleType()),
    "cluster_size": (pa.int64(), T.LongType()),
    "representative_comment_id": (pa.string(), T.StringType()),
    "representative_text": (pa.string(), T.StringType()),
    "comment_id": (pa.string(), T.StringType()),
    "member_comment_id": (pa.string(), T.StringType()),
    "is_representative": (pa.bool_(), T.BooleanType()),
    "text_source": (pa.string(), T.StringType()),
    "text_preview": (pa.string(), T.StringType()),
    "member_text": (pa.string(), T.StringType()),
    "similarity": (pa.float64(), T.DoubleType()),
    "submitter_name": (pa.string(), T.StringType()),
    "submitter_organization": (pa.string(), T.StringType()),
    "submitter_state": (pa.string(), T.StringType()),
    "submitter_country": (pa.string(), T.StringType()),
    "posted_date": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "source": (pa.string(), T.StringType()),
    "exact_match_ratio": (pa.float64(), T.DoubleType()),
    "near_duplicate_ratio": (pa.float64(), T.DoubleType()),
    "purity_score": (pa.float64(), T.DoubleType()),
    "confidence_score": (pa.float64(), T.DoubleType()),
    "candidate_entity_name": (pa.string(), T.StringType()),
    "candidate_entity_type": (pa.string(), T.StringType()),
    "attribution_confidence": (pa.float64(), T.DoubleType()),
    "attribution_evidence_url": (pa.string(), T.StringType()),
    "migration_match_type": (pa.string(), T.StringType()),
    "migration_section": (pa.string(), T.StringType()),
    "migration_similarity": (pa.float64(), T.DoubleType()),
    "migration_claim_scope": (pa.string(), T.StringType()),
    "exported_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
}


TEXT_PREVIEW_CHAR_LIMIT = 500
SOURCE_SEMANTIC = "semantic"
SOURCE_EXACT_HASH = "exact_hash"
EXACT_HASH_BACKEND = "exact_hash"


def cluster_review_export_arrow_schema() -> pa.Schema:
    """pyarrow schema for demo.cluster_review_export (used by the Parquet writer)."""
    return pa.schema(
        [
            pa.field(name, arrow_t, nullable=True)
            for name, (arrow_t, _) in _FIELD_TYPES.items()
        ]
    )


def cluster_review_export_struct() -> T.StructType:
    """PySpark StructType for demo.cluster_review_export (used on Databricks)."""
    return T.StructType(
        [
            T.StructField(name, spark_t, nullable=True)
            for name, (_, spark_t) in _FIELD_TYPES.items()
        ]
    )
