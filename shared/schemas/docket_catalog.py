"""Schemas for workspace.discovery.docket_catalog.

Source of truth is the Pydantic ``DiscoveredDocket``.
Derived PyArrow and PySpark schemas are kept in sync.
"""

from __future__ import annotations

from datetime import datetime

import pyarrow as pa
from pydantic import BaseModel, ConfigDict
from pyspark.sql import types as T


class DiscoveredDocket(BaseModel):
    """Schema for a discovered/monitored rulemaking docket."""

    model_config = ConfigDict(extra="forbid")

    docket_id: str
    source: str
    agency_id: str
    topic_id: str
    title: str
    summary: str
    status: str
    comment_count_estimate: int = 0
    last_comment_date: datetime | None = None
    last_ingested_at: datetime | None = None
    last_analyzed_at: datetime | None = None
    freshness_label: str
    priority_score: float = 0.0
    user_requested_count: int = 0
    tags: str = ""  # Comma-separated list of tags
    metadata_json: str = "{}"
    created_at: datetime
    updated_at: datetime


_FIELD_TYPES: dict[str, tuple[pa.DataType, T.DataType]] = {
    "docket_id": (pa.string(), T.StringType()),
    "source": (pa.string(), T.StringType()),
    "agency_id": (pa.string(), T.StringType()),
    "topic_id": (pa.string(), T.StringType()),
    "title": (pa.string(), T.StringType()),
    "summary": (pa.string(), T.StringType()),
    "status": (pa.string(), T.StringType()),
    "comment_count_estimate": (pa.int64(), T.LongType()),
    "last_comment_date": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "last_ingested_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "last_analyzed_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "freshness_label": (pa.string(), T.StringType()),
    "priority_score": (pa.float64(), T.DoubleType()),
    "user_requested_count": (pa.int64(), T.LongType()),
    "tags": (pa.string(), T.StringType()),
    "metadata_json": (pa.string(), T.StringType()),
    "created_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "updated_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
}


def docket_catalog_arrow_schema() -> pa.Schema:
    """pyarrow schema for workspace.discovery.docket_catalog."""
    return pa.schema(
        [
            pa.field(name, arrow_t, nullable=True)
            for name, (arrow_t, _) in _FIELD_TYPES.items()
        ]
    )


def docket_catalog_struct() -> T.StructType:
    """PySpark StructType for workspace.discovery.docket_catalog."""
    return T.StructType(
        [
            T.StructField(name, spark_t, nullable=True)
            for name, (_, spark_t) in _FIELD_TYPES.items()
        ]
    )
