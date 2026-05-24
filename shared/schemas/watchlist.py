"""Schemas for workspace.discovery.watchlist.

Source of truth is the Pydantic ``WatchlistItem``.
Derived PyArrow and PySpark schemas are kept in sync.
"""

from __future__ import annotations

from datetime import datetime

import pyarrow as pa
from pydantic import BaseModel, ConfigDict
from pyspark.sql import types as T


class WatchlistItem(BaseModel):
    """Schema for a monitored item on the watchlist."""

    model_config = ConfigDict(extra="forbid")

    watch_id: str
    kind: str  # topic | agency | docket | keyword
    value: str
    label: str
    status: str  # active | inactive
    created_at: datetime
    last_checked_at: datetime
    notes: str | None = None
    metadata_json: str = "{}"


_FIELD_TYPES: dict[str, tuple[pa.DataType, T.DataType]] = {
    "watch_id": (pa.string(), T.StringType()),
    "kind": (pa.string(), T.StringType()),
    "value": (pa.string(), T.StringType()),
    "label": (pa.string(), T.StringType()),
    "status": (pa.string(), T.StringType()),
    "created_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "last_checked_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "notes": (pa.string(), T.StringType()),
    "metadata_json": (pa.string(), T.StringType()),
}


def watchlist_arrow_schema() -> pa.Schema:
    """pyarrow schema for workspace.discovery.watchlist."""
    return pa.schema(
        [
            pa.field(name, arrow_t, nullable=True)
            for name, (arrow_t, _) in _FIELD_TYPES.items()
        ]
    )


def watchlist_struct() -> T.StructType:
    """PySpark StructType for workspace.discovery.watchlist."""
    return T.StructType(
        [
            T.StructField(name, spark_t, nullable=True)
            for name, (_, spark_t) in _FIELD_TYPES.items()
        ]
    )
