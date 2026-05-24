"""Schema for gold.rule_migrations.

The Pydantic ``RuleMigration`` is the source of truth. Both the active
``rule_migrations_arrow_schema()`` and ``rule_migrations_struct()`` (kept for
parity with the Databricks/Spark write path) are derived from the same
field-type table below.

This table stores **language overlap evidence**, not causal claims. See
ADR-0015. ``caveat_text`` is required on every row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import pyarrow as pa
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pyspark.sql import types as T


MigrationMatchType = Literal["exact", "near_exact", "semantic"]

MigrationConfidenceLabel = Literal["low", "medium", "high", "needs_review"]

MigrationClaimScope = Literal[
    "phrase_overlap",
    "argument_similarity",
    "possible_influence",
]


class RuleMigration(BaseModel):
    """One language-overlap finding between a cluster and a final rule section.

    Rows are evidence packets: matched phrases, the rule excerpt, a similarity
    score, and a mandatory caveat. They never claim causality.
    """

    model_config = ConfigDict(extra="forbid")

    migration_id: str
    cluster_id: str
    docket_id: str
    final_rule_document_id: str
    final_rule_url: str | None = None
    final_rule_section: str | None = None
    cluster_phrase: str
    rule_phrase: str
    similarity_score: float = Field(ge=0.0, le=1.0)
    match_type: MigrationMatchType
    confidence_score: float = Field(ge=0.0, lt=1.0)
    confidence_label: MigrationConfidenceLabel
    claim_scope: MigrationClaimScope
    caveat_text: str
    created_at: datetime
    metadata_json: str | None = None

    @field_validator("caveat_text")
    @classmethod
    def _caveat_must_be_present(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError(
                "RuleMigration.caveat_text must be a non-empty string. "
                "Every migration row must carry an explicit caveat (ADR-0015)."
            )
        return value


_FIELD_TYPES: dict[str, tuple[pa.DataType, T.DataType]] = {
    "migration_id": (pa.string(), T.StringType()),
    "cluster_id": (pa.string(), T.StringType()),
    "docket_id": (pa.string(), T.StringType()),
    "final_rule_document_id": (pa.string(), T.StringType()),
    "final_rule_url": (pa.string(), T.StringType()),
    "final_rule_section": (pa.string(), T.StringType()),
    "cluster_phrase": (pa.string(), T.StringType()),
    "rule_phrase": (pa.string(), T.StringType()),
    "similarity_score": (pa.float64(), T.DoubleType()),
    "match_type": (pa.string(), T.StringType()),
    "confidence_score": (pa.float64(), T.DoubleType()),
    "confidence_label": (pa.string(), T.StringType()),
    "claim_scope": (pa.string(), T.StringType()),
    "caveat_text": (pa.string(), T.StringType()),
    "created_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "metadata_json": (pa.string(), T.StringType()),
}


def rule_migrations_arrow_schema() -> pa.Schema:
    """pyarrow schema for gold.rule_migrations."""
    return pa.schema(
        [
            pa.field(name, arrow_t, nullable=True)
            for name, (arrow_t, _) in _FIELD_TYPES.items()
        ]
    )


def rule_migrations_struct() -> T.StructType:
    """PySpark StructType for gold.rule_migrations."""
    return T.StructType(
        [
            T.StructField(name, spark_t, nullable=True)
            for name, (_, spark_t) in _FIELD_TYPES.items()
        ]
    )
