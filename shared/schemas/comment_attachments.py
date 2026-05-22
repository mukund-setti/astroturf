"""Schemas for silver.comment_attachments.

The Pydantic ``CommentAttachment`` is the source of truth. Both the active
``comment_attachment_arrow_schema()`` (used by the delta-rs writer locally) and the
``comment_attachment_struct()`` (kept for parity with the Databricks/Spark write path)
are derived from the same field-type table below — a single sync test guards
against drift.
"""

from __future__ import annotations

from datetime import datetime

import pyarrow as pa
from pydantic import BaseModel, ConfigDict
from pyspark.sql import types as T


class CommentAttachment(BaseModel):
    """Metadata for one comment attachment resource format."""

    model_config = ConfigDict(extra="forbid")

    attachment_id: str  # Format: "{id}_{format}"
    comment_id: str
    docket_id: str
    file_name: str | None = None
    file_url: str
    format: str
    size_bytes: int | None = None
    detected_at: datetime
    download_status: str = "pending"
    extracted_text_path: str | None = None
    local_path: str | None = None
    checksum_sha256: str | None = None
    downloaded_at: datetime | None = None
    download_error: str | None = None
    size_bytes_actual: int | None = None


# (arrow_type, spark_type) per field. Field order here drives both derived schemas.
_FIELD_TYPES: dict[str, tuple[pa.DataType, T.DataType]] = {
    "attachment_id": (pa.string(), T.StringType()),
    "comment_id": (pa.string(), T.StringType()),
    "docket_id": (pa.string(), T.StringType()),
    "file_name": (pa.string(), T.StringType()),
    "file_url": (pa.string(), T.StringType()),
    "format": (pa.string(), T.StringType()),
    "size_bytes": (pa.int64(), T.LongType()),
    "detected_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "download_status": (pa.string(), T.StringType()),
    "extracted_text_path": (pa.string(), T.StringType()),
    "local_path": (pa.string(), T.StringType()),
    "checksum_sha256": (pa.string(), T.StringType()),
    "downloaded_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "download_error": (pa.string(), T.StringType()),
    "size_bytes_actual": (pa.int64(), T.LongType()),
}


def comment_attachment_arrow_schema() -> pa.Schema:
    """pyarrow schema for silver.comment_attachments (used by the delta-rs writer)."""
    return pa.schema(
        [
            pa.field(name, arrow_t, nullable=True)
            for name, (arrow_t, _) in _FIELD_TYPES.items()
        ]
    )


def comment_attachment_struct() -> T.StructType:
    """PySpark StructType for silver.comment_attachments (used on Databricks)."""
    return T.StructType(
        [
            T.StructField(name, spark_t, nullable=True)
            for name, (_, spark_t) in _FIELD_TYPES.items()
        ]
    )
