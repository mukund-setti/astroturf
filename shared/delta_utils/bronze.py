"""Bronze layer Delta writers.

Idempotent MERGE upserts keyed by ``comment_id``. Dispatches to the active
backend (``delta_rs`` for local Windows runs, ``spark`` for Databricks
notebook execution) per ``shared.delta_utils.backend``. See ADR-0002 for the
JVM-free local rationale and ADR-0017 for the local-vs-Databricks split.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

from shared.delta_utils.backend import should_use_spark
from shared.delta_utils.silver import ensure_schema

log = logging.getLogger(__name__)


def merge_comments(
    path: str | Path,
    arrow_table: pa.Table,
    key: str = "comment_id",
) -> dict[str, int]:
    """Idempotent upsert of ``arrow_table`` into the Delta table at ``path``.

    Routes to the Spark backend for Databricks Volume / DBFS paths when a
    Spark session is active; otherwise uses delta-rs. Both backends return
    the same ``{"inserted": N, "updated": M}`` shape.
    """
    predicate = f"target.{key} = source.{key}"
    if should_use_spark(path):
        from shared.delta_utils.spark_writers import spark_merge

        return spark_merge(path, arrow_table, predicate)
    return _delta_rs_merge_comments(path, arrow_table, key)


def _delta_rs_merge_comments(
    path: str | Path,
    arrow_table: pa.Table,
    key: str,
) -> dict[str, int]:
    """delta-rs upsert. Initialises an empty Delta table on first call and
    migrates additively via ``ensure_schema()`` (ADR-0004) so a pre-source-field
    bronze table picks up new columns transparently.
    """
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
