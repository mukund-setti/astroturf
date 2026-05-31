"""Delta writers for gold.rule_migrations.

Idempotent upserts keyed by ``migration_id`` (see ADR-0015). Dispatches
between delta-rs and Spark per ADR-0017.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

from shared.delta_utils.backend import should_use_spark

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
    predicate = "target.migration_id = source.migration_id"
    if should_use_spark(path):
        from shared.delta_utils.spark_writers import spark_merge

        return spark_merge(path, arrow_table, predicate)

    _initialize_if_needed(path, arrow_table.schema)
    dt = DeltaTable(str(path))
    metrics = (
        dt.merge(
            source=arrow_table,
            predicate=predicate,
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
    escaped_docket = docket_id.replace("'", "''")
    predicate = f"docket_id = '{escaped_docket}'"
    if cluster_ids:
        escaped_ids = ", ".join(
            f"'{cid.replace(chr(39), chr(39) + chr(39))}'" for cid in cluster_ids
        )
        predicate = f"{predicate} AND cluster_id IN ({escaped_ids})"

    if should_use_spark(path):
        from shared.delta_utils.spark_writers import (
            spark_delete,
            spark_ensure_path_initialized,
        )

        spark_ensure_path_initialized(path, schema)
        return spark_delete(path, predicate)

    _initialize_if_needed(path, schema)
    dt = DeltaTable(str(path))
    metrics = dt.delete(predicate=predicate)
    return int(metrics.get("num_deleted_rows", 0))
