"""Delta-rs helpers for local silver writes.

See docs/decisions/0002-deltalake-for-local-bronze.md for the JVM-free rationale.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

from shared.delta_utils.fuse_bypass import local_tmp_delta_path

log = logging.getLogger(__name__)


def load_delta_as_pyarrow(path: str | Path) -> pa.Table:
    """Loads a Delta table from path as a PyArrow Table, using Spark if active.

    This bypasses native C-extension Parquet/dataset Arrow readers in environments
    like Databricks Serverless where pre-installed/legacy PyArrow versions can
    fail with ArrowInvalid errors on newer schema features.
    """
    path_str = str(path)

    # Try to get active Spark session
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
        # Load Delta table using Spark
        df = spark.read.format("delta").load(path_str)
        # Collect to PyArrow table
        # Collecting to pylist and converting via PyArrow Table directly from pylist
        # bypasses any Parquet/dataset native type checking issues in old PyArrow versions.
        rows = df.collect()
        pylist = [row.asDict(recursive=True) for row in rows]
        if not pylist:
            # If the table has no data, delta-rs can read it safely without Parquet type errors
            return DeltaTable(path_str).to_pyarrow_table()

        table = pa.Table.from_pylist(pylist)
        return table
    else:
        # Fallback to standard delta-rs
        return DeltaTable(path_str).to_pyarrow_table()


def _merge_with_predicate(
    path: str | Path,
    arrow_table: pa.Table,
    predicate: str,
) -> dict[str, int]:
    """Idempotent upsert of ``arrow_table`` using a raw SQL merge ``predicate``.

    Initialises an empty Delta table with ``arrow_table.schema`` on first call so
    the merge always has a target. Returns the row-count operation metrics from
    delta-rs as ``{"inserted": N, "updated": M}``.
    """
    with local_tmp_delta_path(path) as local_path:
        path_str = str(local_path)

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


def merge_parsed_comments(
    path: str | Path,
    arrow_table: pa.Table,
    key: str = "comment_id",
) -> dict[str, int]:
    """Idempotent upsert into a Delta table keyed by a single column ``key``."""
    return _merge_with_predicate(path, arrow_table, f"target.{key} = source.{key}")


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

    Per ADR-0005 the primary key is ``(comment_id, embedding_model)`` so a single
    comment can hold one row per model without collision.
    """
    return _merge_with_predicate(
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
    """Ensures an existing Delta table's schema matches expected_arrow_schema.

    Only additive, nullable migrations are allowed. If allow_destructive is False,
    raises ValueError for missing columns. Logs loudly on destructive overwrites.
    """
    with local_tmp_delta_path(table_path) as local_table_path:
        table_path_str = str(local_table_path)
        if not DeltaTable.is_deltatable(table_path_str):
            # Table does not exist, nothing to migrate or ensure
            return

        all_records = load_delta_as_pyarrow(table_path_str)
        on_disk_arrow_schema = all_records.schema

        on_disk_fields = {field.name: field for field in on_disk_arrow_schema}
        expected_fields = {field.name: field for field in expected_arrow_schema}

        # Reject non-additive changes: removed fields
        removed_fields = [
            name for name in on_disk_fields if name not in expected_fields
        ]
        if removed_fields:
            raise ValueError(
                f"Schema migration rejected: non-additive change. Columns {removed_fields} "
                f"exist on disk but are missing from the expected schema."
            )

        # Reject type and nullability changes
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

        # Find missing fields on disk that are declared in the expected schema
        missing_fields = [
            field
            for name, field in expected_fields.items()
            if name not in on_disk_fields
        ]
        if not missing_fields:
            # Schemas match perfectly, no migration needed
            return

        # All missing fields must be nullable
        non_nullable_missing = [
            field.name for field in missing_fields if not field.nullable
        ]
        if non_nullable_missing:
            raise ValueError(
                f"Schema migration rejected: new fields {non_nullable_missing} are non-nullable. "
                f"New columns must be nullable to support existing data."
            )

        # If destructive migration is not permitted, raise an error
        if not allow_destructive:
            raise ValueError(
                f"Delta table at {table_path_str} is missing new fields: {[f.name for f in missing_fields]}. "
                f"Re-run with allow_destructive=True to execute the migration automatically."
            )

        # Log loudly before destructive overwrite
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

        # Append missing columns as nulls
        for field in expected_arrow_schema:
            if field.name not in all_records.schema.names:
                null_arr = pa.nulls(len(all_records), type=field.type)
                all_records = all_records.append_column(field, null_arr)

        # Reorder columns to match the expected schema before casting types —
        # ``Table.cast`` doesn't reorder, so additions in the middle of the
        # schema would otherwise fail with a field-name mismatch.
        all_records = all_records.select(expected_arrow_schema.names)
        all_records = all_records.cast(expected_arrow_schema)

        # Write back the table
        write_deltalake(
            table_path_str,
            all_records,
            mode="overwrite",
            schema_mode="overwrite",
        )
        log.info("Schema migration successful for table: %s", table_path_str)
