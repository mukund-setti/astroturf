"""Delta writers for the discovery layer (autopilot / catalog / watchlist).

Idempotent upserts on stable PKs. Dispatches between delta-rs and Spark per
ADR-0017.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

from shared.delta_utils.backend import should_use_spark
from shared.delta_utils.silver import ensure_schema

log = logging.getLogger(__name__)


def _delta_rs_merge_table(
    path: str | Path,
    arrow_table: pa.Table,
    key: str,
) -> dict[str, int]:
    path_str = str(path)

    if not DeltaTable.is_deltatable(path_str):
        empty = pa.Table.from_pylist([], schema=arrow_table.schema)
        write_deltalake(path_str, empty, mode="overwrite")
        log.info("Initialised Delta table at %s", path_str)
    else:
        ensure_schema(path_str, arrow_table.schema, allow_destructive=True)

    dt = DeltaTable(path_str)
    metrics = (
        dt.merge(
            source=arrow_table,
            predicate=f"target.{key} = source.{key}",
            source_alias="source",
            target_alias="target",
        )
        .when_matched_update_all()
        .when_not_matched_insert_all()
        .execute()
    )
    return {
        "inserted": int(metrics.get("num_target_rows_inserted", 0)),
        "updated": int(metrics.get("num_target_rows_updated", 0)),
    }


def _dispatch_merge(
    path: str | Path,
    arrow_table: pa.Table,
    key: str,
) -> dict[str, int]:
    if should_use_spark(path):
        from shared.delta_utils.spark_writers import spark_merge

        return spark_merge(path, arrow_table, f"target.{key} = source.{key}")
    return _delta_rs_merge_table(path, arrow_table, key)


def merge_docket_catalog(
    path: str | Path,
    arrow_table: pa.Table,
) -> dict[str, int]:
    """Idempotently merge dockets into docket_catalog by docket_id."""
    return _dispatch_merge(path, arrow_table, key="docket_id")


def merge_watchlist(
    path: str | Path,
    arrow_table: pa.Table,
) -> dict[str, int]:
    """Idempotently merge watchlist items into watchlist by watch_id."""
    return _dispatch_merge(path, arrow_table, key="watch_id")


def merge_analysis_requests(
    path: str | Path,
    arrow_table: pa.Table,
) -> dict[str, int]:
    """Idempotently merge analysis_request updates by request_id."""
    return _dispatch_merge(path, arrow_table, key="request_id")


def merge_autopilot_runs(
    path: str | Path,
    arrow_table: pa.Table,
) -> dict[str, int]:
    """Idempotently merge autopilot_runs tracking by run_id."""
    return _dispatch_merge(path, arrow_table, key="run_id")
