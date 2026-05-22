"""Schemas for silver.parsed_comments.

The Pydantic ``ParsedComment`` is the source of truth. Both the active
``parsed_comment_arrow_schema()`` (used by the delta-rs writer locally) and the
``parsed_comment_struct()`` (kept for parity with the Databricks/Spark write path)
are derived from the same field-type table below — a single sync test guards
against drift.
"""

from __future__ import annotations

from datetime import datetime

import pyarrow as pa
from pydantic import BaseModel, ConfigDict
from pyspark.sql import types as T


class ParsedComment(BaseModel):
    """One parsed public comment normalized to silver."""

    model_config = ConfigDict(extra="forbid")

    comment_id: str
    docket_id: str
    title: str | None = None
    posted_date: datetime | None = None
    last_modified_date: datetime | None = None
    received_date: datetime | None = None
    source_system_version: str
    parser_version: str
    text_source: str
    raw_text: str | None = None
    normalized_text: str | None = None
    normalized_text_hash: str | None = None
    token_estimate: int
    char_count: int
    has_attachments: bool = False
    parse_status: str
    parse_error: str | None = None
    parsed_at: datetime


# (arrow_type, spark_type) per field. Field order here drives both derived schemas.
_FIELD_TYPES: dict[str, tuple[pa.DataType, T.DataType]] = {
    "comment_id": (pa.string(), T.StringType()),
    "docket_id": (pa.string(), T.StringType()),
    "title": (pa.string(), T.StringType()),
    "posted_date": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "last_modified_date": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "received_date": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "source_system_version": (pa.string(), T.StringType()),
    "parser_version": (pa.string(), T.StringType()),
    "text_source": (pa.string(), T.StringType()),
    "raw_text": (pa.string(), T.StringType()),
    "normalized_text": (pa.string(), T.StringType()),
    "normalized_text_hash": (pa.string(), T.StringType()),
    "token_estimate": (pa.int64(), T.LongType()),
    "char_count": (pa.int64(), T.LongType()),
    "has_attachments": (pa.bool_(), T.BooleanType()),
    "parse_status": (pa.string(), T.StringType()),
    "parse_error": (pa.string(), T.StringType()),
    "parsed_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
}


def parsed_comment_arrow_schema() -> pa.Schema:
    """pyarrow schema for silver.parsed_comments (used by the delta-rs writer)."""
    return pa.schema(
        [
            pa.field(name, arrow_t, nullable=True)
            for name, (arrow_t, _) in _FIELD_TYPES.items()
        ]
    )


def parsed_comment_struct() -> T.StructType:
    """PySpark StructType for silver.parsed_comments (used on Databricks)."""
    return T.StructType(
        [
            T.StructField(name, spark_t, nullable=True)
            for name, (_, spark_t) in _FIELD_TYPES.items()
        ]
    )
