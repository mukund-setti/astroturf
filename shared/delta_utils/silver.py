"""Delta-rs helpers for local silver writes.

See docs/decisions/0002-deltalake-for-local-bronze.md for the JVM-free rationale.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

log = logging.getLogger(__name__)


def merge_parsed_comments(
    path: str | Path,
    arrow_table: pa.Table,
    key: str = "comment_id",
) -> dict[str, int]:
    """Idempotent upsert of ``arrow_table`` into the Delta table at ``path``.

    Initialises an empty Delta table with ``arrow_table.schema`` on first call so
    the merge always has a target. Returns the row-count operation metrics from
    delta-rs as ``{"inserted": N, "updated": M}``.
    """
    path_str = str(path)

    if not DeltaTable.is_deltatable(path_str):
        empty = pa.Table.from_pylist([], schema=arrow_table.schema)
        write_deltalake(path_str, empty, mode="overwrite")
        log.info("Initialised Delta table at %s", path_str)

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


def merge_comment_details(
    path: str | Path,
    arrow_table: pa.Table,
) -> dict[str, int]:
    """Idempotent upsert of detail rows into silver.comment_details."""
    return merge_parsed_comments(path, arrow_table, key="comment_id")


def merge_comment_attachments(
    path: str | Path,
    arrow_table: pa.Table,
) -> dict[str, int]:
    """Idempotent upsert of attachment rows into silver.comment_attachments."""
    return merge_parsed_comments(path, arrow_table, key="attachment_id")
