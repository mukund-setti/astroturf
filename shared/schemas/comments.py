"""Schemas for bronze.raw_comments.

The Pydantic ``RawComment`` is the source of truth. Both the active
``raw_comment_arrow_schema()`` (used by the delta-rs writer locally) and the
``raw_comment_struct()`` (kept for parity with the Databricks/Spark write path)
are derived from the same field-type table below — a single sync test guards
against drift.
"""
from __future__ import annotations

from datetime import datetime

import pyarrow as pa
from pydantic import BaseModel, ConfigDict
from pyspark.sql import types as T


class RawComment(BaseModel):
    """One public comment from regulations.gov v4, normalized to bronze."""

    model_config = ConfigDict(extra="forbid")

    comment_id: str
    docket_id: str
    document_type: str | None = None
    title: str | None = None
    posted_date: datetime | None = None
    received_date: datetime | None = None
    last_modified_date: datetime | None = None
    comment_text: str | None = None
    submitter_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    organization: str | None = None
    city: str | None = None
    state_province_region: str | None = None
    country: str | None = None
    agency_id: str | None = None
    has_attachments: bool = False
    attributes_json: str = "{}"
    ingested_at: datetime


# (arrow_type, spark_type) per field. Field order here drives both derived schemas.
_FIELD_TYPES: dict[str, tuple[pa.DataType, T.DataType]] = {
    "comment_id": (pa.string(), T.StringType()),
    "docket_id": (pa.string(), T.StringType()),
    "document_type": (pa.string(), T.StringType()),
    "title": (pa.string(), T.StringType()),
    "posted_date": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "received_date": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "last_modified_date": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "comment_text": (pa.string(), T.StringType()),
    "submitter_name": (pa.string(), T.StringType()),
    "first_name": (pa.string(), T.StringType()),
    "last_name": (pa.string(), T.StringType()),
    "organization": (pa.string(), T.StringType()),
    "city": (pa.string(), T.StringType()),
    "state_province_region": (pa.string(), T.StringType()),
    "country": (pa.string(), T.StringType()),
    "agency_id": (pa.string(), T.StringType()),
    "has_attachments": (pa.bool_(), T.BooleanType()),
    "attributes_json": (pa.string(), T.StringType()),
    "ingested_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
}


def raw_comment_arrow_schema() -> pa.Schema:
    """pyarrow schema for bronze.raw_comments (used by the delta-rs writer)."""
    return pa.schema(
        [pa.field(name, arrow_t, nullable=True) for name, (arrow_t, _) in _FIELD_TYPES.items()]
    )


def raw_comment_struct() -> T.StructType:
    """PySpark StructType for bronze.raw_comments (used on Databricks)."""
    return T.StructType(
        [T.StructField(name, spark_t, nullable=True) for name, (_, spark_t) in _FIELD_TYPES.items()]
    )
