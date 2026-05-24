"""Delta-rs helpers for gold.rule_migrations writes.

Idempotent upserts keyed by ``migration_id`` (see ADR-0015). Mirrors the
pattern in ``shared/delta_utils/gold.py``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

from shared.delta_utils.fuse_bypass import local_tmp_delta_path

log = logging.getLogger(__name__)


def _initialize_if_needed(path: str | Path, schema: pa.Schema) -> None:
    path_str = str(path)
    if DeltaTable.is_deltatable(path_str):
        return
    empty = pa.Table.from_pylist([], schema=schema)
    write_deltalake(path_str, empty, mode="overwrite")
    log.info("Initialised Delta table at %s", path_str)


def merge_rule_migrations(
    path: str | Path,
    arrow_table: pa.Table,
) -> dict[str, int]:
    """Idempotent upsert into gold.rule_migrations by migration_id."""
    with local_tmp_delta_path(path) as local_path:
        _initialize_if_needed(local_path, arrow_table.schema)
        dt = DeltaTable(str(local_path))
        metrics = (
            dt.merge(
                source=arrow_table,
                predicate="target.migration_id = source.migration_id",
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


def delete_migration_scope(
    path: str | Path,
    schema: pa.Schema,
    *,
    docket_id: str,
    cluster_ids: list[str] | None = None,
) -> int:
    """Delete prior migration rows for a docket (optionally narrowed to clusters)."""
    with local_tmp_delta_path(path) as local_path:
        _initialize_if_needed(local_path, schema)
        dt = DeltaTable(str(local_path))
        escaped_docket = docket_id.replace("'", "''")
        predicate = f"docket_id = '{escaped_docket}'"
        if cluster_ids:
            escaped_ids = ", ".join(
                f"'{cid.replace(chr(39), chr(39) + chr(39))}'" for cid in cluster_ids
            )
            predicate = f"{predicate} AND cluster_id IN ({escaped_ids})"
        metrics = dt.delete(predicate=predicate)
        return int(metrics.get("num_deleted_rows", 0))
