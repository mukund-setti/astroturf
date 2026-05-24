"""Schema for gold.campaign_attributions.

The Pydantic ``CampaignAttribution`` is the source of truth. Both the active
``campaign_attributions_arrow_schema()`` (used by the local delta-rs writer)
and ``campaign_attributions_struct()`` (kept for parity with the
Databricks/Spark write path) are derived from the same field-type table
below, following the pattern in ``shared/schemas/comment_clusters.py``.

This table stores **evidence packets**, not accusations. See ADR-0015 for the
full policy on what AttributionAgent claims and what it does not claim.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import pyarrow as pa
from pydantic import BaseModel, ConfigDict, Field
from pyspark.sql import types as T


CandidateEntityType = Literal[
    "trade_association",
    "advocacy_group",
    "company",
    "unknown",
    "other",
]

AttributionEvidenceType = Literal[
    "exact_phrase_match",
    "fuzzy_phrase_match",
    "known_campaign_registry",
    "manual_seed",
    "llm_hypothesis",
]

AttributionConfidenceLabel = Literal["low", "medium", "high", "needs_review"]

AttributionReviewedStatus = Literal["unreviewed", "reviewed", "rejected"]


class CampaignAttribution(BaseModel):
    """One evidence-backed candidate origin for a cluster.

    Each row represents a single observed match against a curated source.
    Multiple rows per cluster are expected (one per matched entity / phrase).
    """

    model_config = ConfigDict(extra="forbid")

    attribution_id: str
    cluster_id: str
    docket_id: str
    candidate_entity_name: str
    candidate_entity_type: CandidateEntityType
    candidate_url: str | None = None
    evidence_type: AttributionEvidenceType
    matched_phrase: str | None = None
    evidence_excerpt: str | None = None
    confidence_score: float = Field(ge=0.0, lt=1.0)
    confidence_label: AttributionConfidenceLabel
    reasoning_summary: str
    reviewed_status: AttributionReviewedStatus = "unreviewed"
    created_at: datetime
    metadata_json: str | None = None


_FIELD_TYPES: dict[str, tuple[pa.DataType, T.DataType]] = {
    "attribution_id": (pa.string(), T.StringType()),
    "cluster_id": (pa.string(), T.StringType()),
    "docket_id": (pa.string(), T.StringType()),
    "candidate_entity_name": (pa.string(), T.StringType()),
    "candidate_entity_type": (pa.string(), T.StringType()),
    "candidate_url": (pa.string(), T.StringType()),
    "evidence_type": (pa.string(), T.StringType()),
    "matched_phrase": (pa.string(), T.StringType()),
    "evidence_excerpt": (pa.string(), T.StringType()),
    "confidence_score": (pa.float64(), T.DoubleType()),
    "confidence_label": (pa.string(), T.StringType()),
    "reasoning_summary": (pa.string(), T.StringType()),
    "reviewed_status": (pa.string(), T.StringType()),
    "created_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "metadata_json": (pa.string(), T.StringType()),
}


def campaign_attributions_arrow_schema() -> pa.Schema:
    """pyarrow schema for gold.campaign_attributions."""
    return pa.schema(
        [
            pa.field(name, arrow_t, nullable=True)
            for name, (arrow_t, _) in _FIELD_TYPES.items()
        ]
    )


def campaign_attributions_struct() -> T.StructType:
    """PySpark StructType for gold.campaign_attributions."""
    return T.StructType(
        [
            T.StructField(name, spark_t, nullable=True)
            for name, (_, spark_t) in _FIELD_TYPES.items()
        ]
    )
