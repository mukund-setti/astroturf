"""Delta-rs helpers for local and Databricks discovery writes.

Idempotent updates using Delta merges on unique stable primary keys.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

from shared.delta_utils.fuse_bypass import local_tmp_delta_path
from shared.delta_utils.silver import ensure_schema

log = logging.getLogger(__name__)


def _merge_table(
    path: str | Path,
    arrow_table: pa.Table,
    key: str,
) -> dict[str, int]:
    """Upsert pyarrow Table into Delta Lake table at path keyed by key."""
    with local_tmp_delta_path(path) as local_path:
        path_str = str(local_path)

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


def merge_docket_catalog(
    path: str | Path,
    arrow_table: pa.Table,
) -> dict[str, int]:
    """Idempotently merge discovered/monitored dockets into docket_catalog table by docket_id."""
    return _merge_table(path, arrow_table, key="docket_id")


def merge_watchlist(
    path: str | Path,
    arrow_table: pa.Table,
) -> dict[str, int]:
    """Idempotently merge watchlist items into watchlist table by watch_id."""
    return _merge_table(path, arrow_table, key="watch_id")


def merge_analysis_requests(
    path: str | Path,
    arrow_table: pa.Table,
) -> dict[str, int]:
    """Idempotently merge analysis request updates into analysis_requests table by request_id."""
    return _merge_table(path, arrow_table, key="request_id")


def merge_autopilot_runs(
    path: str | Path,
    arrow_table: pa.Table,
) -> dict[str, int]:
    """Idempotently merge autopilot run tracking into autopilot_runs table by run_id."""
    return _merge_table(path, arrow_table, key="run_id")
