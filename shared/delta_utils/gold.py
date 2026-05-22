"""Delta-rs helpers for local gold writes."""

from __future__ import annotations

import logging
from pathlib import Path

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

from shared.delta_utils.silver import ensure_schema

log = logging.getLogger(__name__)


def _initialize_if_needed(path: str | Path, schema: pa.Schema) -> None:
    path_str = str(path)
    if DeltaTable.is_deltatable(path_str):
        return
    empty = pa.Table.from_pylist([], schema=schema)
    write_deltalake(path_str, empty, mode="overwrite")
    log.info("Initialised Delta table at %s", path_str)


def _merge_with_predicate(
    path: str | Path,
    arrow_table: pa.Table,
    predicate: str,
) -> dict[str, int]:
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


def _scope_predicate(
    *,
    docket_id: str,
    embedding_model: str,
    clustering_version: str,
    similarity_threshold: float,
) -> str:
    escaped_docket = docket_id.replace("'", "''")
    escaped_model = embedding_model.replace("'", "''")
    escaped_version = clustering_version.replace("'", "''")
    threshold = repr(float(similarity_threshold))
    return (
        f"docket_id = '{escaped_docket}' "
        f"AND embedding_model = '{escaped_model}' "
        f"AND clustering_version = '{escaped_version}' "
        f"AND similarity_threshold = {threshold}"
    )


def delete_clustering_scope(
    path: str | Path,
    schema: pa.Schema,
    *,
    docket_id: str,
    embedding_model: str,
    clustering_version: str,
    similarity_threshold: float,
) -> int:
    """Delete prior deterministic clustering output for an exact run scope."""
    _initialize_if_needed(path, schema)
    ensure_schema(path, schema, allow_destructive=True)
    dt = DeltaTable(str(path))
    metrics = dt.delete(
        predicate=_scope_predicate(
            docket_id=docket_id,
            embedding_model=embedding_model,
            clustering_version=clustering_version,
            similarity_threshold=similarity_threshold,
        )
    )
    return int(metrics.get("num_deleted_rows", 0))


def merge_comment_clusters(
    path: str | Path,
    arrow_table: pa.Table,
) -> dict[str, int]:
    """Idempotent upsert into gold.comment_clusters by cluster_id."""
    return _merge_with_predicate(
        path,
        arrow_table,
        "target.cluster_id = source.cluster_id",
    )


def merge_comment_cluster_memberships(
    path: str | Path,
    arrow_table: pa.Table,
) -> dict[str, int]:
    """Idempotent upsert into gold.comment_cluster_memberships by compound key."""
    return _merge_with_predicate(
        path,
        arrow_table,
        "target.cluster_id = source.cluster_id "
        "AND target.comment_id = source.comment_id",
    )
