"""Schemas for bronze.raw_comments.

The Pydantic ``RawComment`` is the source of truth. Both the active
``raw_comment_arrow_schema()`` (used by the delta-rs writer locally) and the
``raw_comment_struct()`` (kept for parity with the Databricks/Spark write path)
are derived from the same field-type table below — a single sync test guards
against drift.

See ADR-0012 for the multi-source unification design (regulations.gov + ECFS).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import pyarrow as pa
from pydantic import BaseModel, ConfigDict
from pyspark.sql import types as T


class RawComment(BaseModel):
    """One public comment normalized to bronze.

    Source is required at the Pydantic layer so the IngestionAgent cannot insert
    a row without a source label, but the column is Arrow-nullable so ADR-0004's
    ``ensure_schema()`` can migrate older on-disk tables that pre-date the
    field. Same pattern as ``comment_id``, ``docket_id``, ``ingested_at``. See
    ADR-0012.
    """

    model_config = ConfigDict(extra="forbid")

    comment_id: str
    docket_id: str
    source: Literal["regulations_gov", "ecfs"]
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
    ecfs_proceeding_id: str | None = None
    ecfs_submission_type_id: int | None = None
    ecfs_express_comment: bool | None = None


# (arrow_type, spark_type) per field. Field order here drives both derived schemas.
_FIELD_TYPES: dict[str, tuple[pa.DataType, T.DataType]] = {
    "comment_id": (pa.string(), T.StringType()),
    "docket_id": (pa.string(), T.StringType()),
    "source": (pa.string(), T.StringType()),
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
    "ecfs_proceeding_id": (pa.string(), T.StringType()),
    "ecfs_submission_type_id": (pa.int64(), T.LongType()),
    "ecfs_express_comment": (pa.bool_(), T.BooleanType()),
}


def raw_comment_arrow_schema() -> pa.Schema:
    """pyarrow schema for bronze.raw_comments (used by the delta-rs writer)."""
    return pa.schema(
        [
            pa.field(name, arrow_t, nullable=True)
            for name, (arrow_t, _) in _FIELD_TYPES.items()
        ]
    )


def raw_comment_struct() -> T.StructType:
    """PySpark StructType for bronze.raw_comments (used on Databricks)."""
    return T.StructType(
        [
            T.StructField(name, spark_t, nullable=True)
            for name, (_, spark_t) in _FIELD_TYPES.items()
        ]
    )
