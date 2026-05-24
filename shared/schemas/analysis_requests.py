"""Schemas for workspace.discovery.analysis_requests.

Source of truth is the Pydantic ``AnalysisRequestModel``.
Derived PyArrow and PySpark schemas are kept in sync.
"""

from __future__ import annotations

from datetime import datetime

import pyarrow as pa
from pydantic import BaseModel, ConfigDict
from pyspark.sql import types as T


class AnalysisRequestModel(BaseModel):
    """Schema for a docket analysis request enqueued or running on Databricks."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    docket_id: str
    source: str
    topic_id: str
    agency_id: str
    title: str
    date_start: str | None = None
    date_end: str | None = None
    expected_scale: int = 1000
    notes: str = ""
    status: str  # draft | submitted | running | succeeded | failed | canceled
    databricks_run_id: str | None = None
    error_message: str | None = None
    result_url: str | None = None
    created_at: datetime
    updated_at: datetime
    metadata_json: str = "{}"


_FIELD_TYPES: dict[str, tuple[pa.DataType, T.DataType]] = {
    "request_id": (pa.string(), T.StringType()),
    "docket_id": (pa.string(), T.StringType()),
    "source": (pa.string(), T.StringType()),
    "topic_id": (pa.string(), T.StringType()),
    "agency_id": (pa.string(), T.StringType()),
    "title": (pa.string(), T.StringType()),
    "date_start": (pa.string(), T.StringType()),
    "date_end": (pa.string(), T.StringType()),
    "expected_scale": (pa.int64(), T.LongType()),
    "notes": (pa.string(), T.StringType()),
    "status": (pa.string(), T.StringType()),
    "databricks_run_id": (pa.string(), T.StringType()),
    "error_message": (pa.string(), T.StringType()),
    "result_url": (pa.string(), T.StringType()),
    "created_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "updated_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "metadata_json": (pa.string(), T.StringType()),
}


def analysis_requests_arrow_schema() -> pa.Schema:
    """pyarrow schema for workspace.discovery.analysis_requests."""
    return pa.schema(
        [
            pa.field(name, arrow_t, nullable=True)
            for name, (arrow_t, _) in _FIELD_TYPES.items()
        ]
    )


def analysis_requests_struct() -> T.StructType:
    """PySpark StructType for workspace.discovery.analysis_requests."""
    return T.StructType(
        [
            T.StructField(name, spark_t, nullable=True)
            for name, (_, spark_t) in _FIELD_TYPES.items()
        ]
    )
