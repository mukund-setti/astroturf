"""Schemas for silver.comment_details.

The Pydantic ``CommentDetail`` is the source of truth. Both the active
``comment_detail_arrow_schema()`` (used by the delta-rs writer locally) and the
``comment_detail_struct()`` (kept for parity with the Databricks/Spark write path)
are derived from the same field-type table below — a single sync test guards
against drift.
"""

from __future__ import annotations

from datetime import datetime

import pyarrow as pa
from pydantic import BaseModel, ConfigDict
from pyspark.sql import types as T


class CommentDetail(BaseModel):
    """Raw detail JSON and enrichment metadata for one public comment."""

    model_config = ConfigDict(extra="forbid")

    comment_id: str
    docket_id: str
    enrichment_status: str
    enrichment_error: str | None = None
    raw_detail_json: str | None = None
    extracted_at: datetime
    api_version: str = "regulations.gov_v4"
    has_substantive_comment: bool = False
    is_cover_note: bool = False


# (arrow_type, spark_type) per field. Field order here drives both derived schemas.
_FIELD_TYPES: dict[str, tuple[pa.DataType, T.DataType]] = {
    "comment_id": (pa.string(), T.StringType()),
    "docket_id": (pa.string(), T.StringType()),
    "enrichment_status": (pa.string(), T.StringType()),
    "enrichment_error": (pa.string(), T.StringType()),
    "raw_detail_json": (pa.string(), T.StringType()),
    "extracted_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "api_version": (pa.string(), T.StringType()),
    "has_substantive_comment": (pa.bool_(), T.BooleanType()),
    "is_cover_note": (pa.bool_(), T.BooleanType()),
}


def comment_detail_arrow_schema() -> pa.Schema:
    """pyarrow schema for silver.comment_details (used by the delta-rs writer)."""
    return pa.schema(
        [
            pa.field(name, arrow_t, nullable=True)
            for name, (arrow_t, _) in _FIELD_TYPES.items()
        ]
    )


def comment_detail_struct() -> T.StructType:
    """PySpark StructType for silver.comment_details (used on Databricks)."""
    return T.StructType(
        [
            T.StructField(name, spark_t, nullable=True)
            for name, (_, spark_t) in _FIELD_TYPES.items()
        ]
    )
