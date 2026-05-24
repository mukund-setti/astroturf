"""Schemas for workspace.discovery.autopilot_runs.

Source of truth is the Pydantic ``AutopilotRun``.
Derived PyArrow and PySpark schemas are kept in sync.
"""

from __future__ import annotations

from datetime import datetime

import pyarrow as pa
from pydantic import BaseModel, ConfigDict
from pyspark.sql import types as T


class AutopilotRun(BaseModel):
    """Schema for tracking Autopilot scheduled/manual orchestration runs."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str  # success | failed | running
    dockets_discovered: int = 0
    dockets_classified: int = 0
    jobs_triggered: int = 0
    started_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None
    metadata_json: str = "{}"


_FIELD_TYPES: dict[str, tuple[pa.DataType, T.DataType]] = {
    "run_id": (pa.string(), T.StringType()),
    "status": (pa.string(), T.StringType()),
    "dockets_discovered": (pa.int64(), T.LongType()),
    "dockets_classified": (pa.int64(), T.LongType()),
    "jobs_triggered": (pa.int64(), T.LongType()),
    "started_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "completed_at": (pa.timestamp("us", tz="UTC"), T.TimestampType()),
    "error_message": (pa.string(), T.StringType()),
    "metadata_json": (pa.string(), T.StringType()),
}


def autopilot_runs_arrow_schema() -> pa.Schema:
    """pyarrow schema for workspace.discovery.autopilot_runs."""
    return pa.schema(
        [
            pa.field(name, arrow_t, nullable=True)
            for name, (arrow_t, _) in _FIELD_TYPES.items()
        ]
    )


def autopilot_runs_struct() -> T.StructType:
    """PySpark StructType for workspace.discovery.autopilot_runs."""
    return T.StructType(
        [
            T.StructField(name, spark_t, nullable=True)
            for name, (_, spark_t) in _FIELD_TYPES.items()
        ]
    )
