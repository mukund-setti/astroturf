"""Silver layer Delta writers.

Idempotent MERGE upserts for ``silver.parsed_comments``,
``silver.comment_details``, ``silver.comment_attachments``, and
``silver.comment_embeddings``. Dispatches to the active backend per
``shared.delta_utils.backend``. See ADR-0002 for the JVM-free local
rationale and ADR-0017 for the local-vs-Databricks split.

``ensure_schema`` is the cross-backend additive-evolution gate: on
delta-rs it validates and rewrites the table; on Spark it issues
``ALTER TABLE delta.``<path>`` ADD COLUMNS (...)`` for any new fields,
delegating to ``spark_writers.spark_ensure_schema``. See ADR-0017.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

from shared.delta_utils.backend import should_use_spark

log = logging.getLogger(__name__)


def load_delta_as_pyarrow(path: str | Path) -> pa.Table:
    """Loads a Delta table from path as a PyArrow Table, using Spark if active.

    Bypasses native C-extension Parquet/dataset Arrow readers in environments
    like Databricks Serverless where pre-installed/legacy PyArrow versions
    can fail with ArrowInvalid errors on newer schema features.
    """
    path_str = str(path)

    try:
        from pyspark.sql import SparkSession

        spark = SparkSession.getActiveSession()
    except Exception:
        spark = None

    if spark is not None and path_str.startswith("/Volumes/"):
        log.info(
            "Active Spark session detected. Loading Delta table from '%s' via Spark...",
            path_str,
        )
        df = spark.read.format("delta").load(path_str)
        rows = df.collect()
        pylist = [row.asDict(recursive=True) for row in rows]
        if not pylist:
            return DeltaTable(path_str).to_pyarrow_table()
        return pa.Table.from_pylist(pylist)
    return DeltaTable(path_str).to_pyarrow_table()


def _delta_rs_merge_with_predicate(
    path: str | Path,
    arrow_table: pa.Table,
    predicate: str,
) -> dict[str, int]:
    """delta-rs merge. Initialises an empty Delta table on first call."""
    path_str = str(path)

    if not DeltaTable.is_deltatable(path_str):
        empty = pa.Table.from_pylist([], schema=arrow_table.schema)
        write_deltalake(path_str, empty, mode="overwrite")
        log.info("Initialised Delta table at %s", path_str)

    dt = DeltaTable(path_str)
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


def _dispatch_merge(
    path: str | Path,
    arrow_table: pa.Table,
    predicate: str,
) -> dict[str, int]:
    if should_use_spark(path):
        from shared.delta_utils.spark_writers import spark_merge

        return spark_merge(path, arrow_table, predicate)
    return _delta_rs_merge_with_predicate(path, arrow_table, predicate)


def merge_parsed_comments(
    path: str | Path,
    arrow_table: pa.Table,
    key: str = "comment_id",
) -> dict[str, int]:
    """Idempotent upsert into a Delta table keyed by a single column ``key``."""
    return _dispatch_merge(path, arrow_table, f"target.{key} = source.{key}")


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


def merge_comment_embeddings(
    path: str | Path,
    arrow_table: pa.Table,
) -> dict[str, int]:
    """Idempotent upsert into silver.comment_embeddings on compound PK.

    Per ADR-0005 the primary key is ``(comment_id, embedding_model)`` so a
    single comment can hold one row per model without collision.
    """
    return _dispatch_merge(
        path,
        arrow_table,
        "target.comment_id = source.comment_id "
        "AND target.embedding_model = source.embedding_model",
    )


def ensure_schema(
    table_path: str | Path,
    expected_arrow_schema: pa.Schema,
    *,
    allow_destructive: bool = False,
) -> None:
    """Ensures an existing Delta table's schema matches ``expected_arrow_schema``.

    On the delta-rs backend this is the historical implementation: validate
    additive-only changes, then rewrite the table with the new schema if
    permitted.

    On the Spark backend this delegates to
    ``shared.delta_utils.spark_writers.spark_ensure_schema`` which issues an
    explicit ``ALTER TABLE delta.``<path>`` ADD COLUMNS (...)`` for any
    additive deltas. ADR-0017 documents why we moved off the session-conf
    (``spark.databricks.delta.schema.autoMerge.enabled``) approach: it is
    not on the Databricks Serverless allowlist and raises
    ``[CONFIG_NOT_AVAILABLE]`` when set per-merge.
    """
    if should_use_spark(table_path):
        from shared.delta_utils.spark_writers import spark_ensure_schema

        spark_ensure_schema(
            table_path,
            expected_arrow_schema,
            allow_destructive=allow_destructive,
        )
        return

    table_path_str = str(table_path)
    if not DeltaTable.is_deltatable(table_path_str):
        return

    all_records = load_delta_as_pyarrow(table_path_str)
    on_disk_arrow_schema = all_records.schema

    on_disk_fields = {field.name: field for field in on_disk_arrow_schema}
    expected_fields = {field.name: field for field in expected_arrow_schema}

    removed_fields = [name for name in on_disk_fields if name not in expected_fields]
    if removed_fields:
        raise ValueError(
            f"Schema migration rejected: non-additive change. Columns {removed_fields} "
            f"exist on disk but are missing from the expected schema."
        )

    for name, on_disk_field in on_disk_fields.items():
        expected_field = expected_fields[name]
        if on_disk_field.type != expected_field.type:
            raise ValueError(
                f"Schema migration rejected: non-additive type change for field '{name}'. "
                f"On-disk type: {on_disk_field.type}, expected type: {expected_field.type}."
            )
        if on_disk_field.nullable != expected_field.nullable:
            raise ValueError(
                f"Schema migration rejected: non-additive nullability change for field '{name}'. "
                f"On-disk nullable: {on_disk_field.nullable}, expected nullable: {expected_field.nullable}."
            )

    missing_fields = [
        field for name, field in expected_fields.items() if name not in on_disk_fields
    ]
    if not missing_fields:
        return

    non_nullable_missing = [
        field.name for field in missing_fields if not field.nullable
    ]
    if non_nullable_missing:
        raise ValueError(
            f"Schema migration rejected: new fields {non_nullable_missing} are non-nullable. "
            f"New columns must be nullable to support existing data."
        )

    if not allow_destructive:
        raise ValueError(
            f"Delta table at {table_path_str} is missing new fields: {[f.name for f in missing_fields]}. "
            f"Re-run with allow_destructive=True to execute the migration automatically."
        )

    log.warning(
        "\n========================================================================\n"
        "CRITICAL SCHEMA MIGRATION WARNING\n"
        "------------------------------------------------------------------------\n"
        "Performing schema evolution overwrite on Delta table at:\n"
        "  %s\n\n"
        "Adding new nullable fields:\n"
        "  %s\n\n"
        "THIS OPERATION WILL OVERWRITE THE TABLE SCHEMA AT THE DELTA TRANSACTION LAYER.\n"
        "This cannot be undone outside of Delta time-travel / transactions history.\n"
        "========================================================================\n",
        table_path_str,
        [f.name for f in missing_fields],
    )

    for field in expected_arrow_schema:
        if field.name not in all_records.schema.names:
            null_arr = pa.nulls(len(all_records), type=field.type)
            all_records = all_records.append_column(field, null_arr)

    all_records = all_records.select(expected_arrow_schema.names)
    all_records = all_records.cast(expected_arrow_schema)

    write_deltalake(
        table_path_str,
        all_records,
        mode="overwrite",
        schema_mode="overwrite",
    )
    log.info("Schema migration successful for table: %s", table_path_str)
