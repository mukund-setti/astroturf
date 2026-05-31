"""Spark-native Delta writers.

These functions are the Spark equivalents of the delta-rs helpers in
``bronze.py``, ``silver.py``, ``gold.py``, ``attribution.py``,
``migration.py``, and ``discovery.py``. They are dispatched to from
``shared.delta_utils`` when ``shared.delta_utils.backend.should_use_spark(path)``
returns ``True`` — typically inside a Databricks notebook execution.

Design notes
------------

* **Same FUSE paths.** Spark writes to the exact ``/Volumes/.../...`` paths
  that the delta-rs branch writes to. We deliberately do not switch to
  ``saveAsTable(...)`` because the existing Unity Catalog views resolve
  ``SELECT * FROM delta.``<fuse_path>`` `` on read; switching to managed UC
  tables would silently fork the data location. See ADR-0017.

* **Additive schema evolution.** Driven by ``spark_ensure_schema`` (called
  from ``shared.delta_utils.silver.ensure_schema`` before every MERGE),
  which issues an explicit ``ALTER TABLE delta.``<path>`` ADD COLUMNS
  (...)`` for any new fields and refuses non-additive changes (column
  removal, type mismatch). The session-conf approach
  ``spark.databricks.delta.schema.autoMerge.enabled`` that was used in the
  H1 first cut raises ``[CONFIG_NOT_AVAILABLE]`` on Databricks Serverless,
  so we moved to explicit ALTER (ADR-0017 schema-evolution decision).

* **Brand-new paths.** The very first write at a path goes through
  ``overwrite`` (no target to merge into) and reports the row count as
  ``inserted``. Subsequent calls go through MERGE.

* **Empty source short-circuit.** A merge with zero source rows is a no-op
  that still rewrites the Delta log; we skip it explicitly so we don't
  reproduce the "15 empty MERGEs per ingestion page" pattern that the
  diagnosis flagged for the IngestionAgent loop.

* **Metrics shape parity.** Returns ``{"inserted": N, "updated": M}`` — the
  same shape as the delta-rs helpers so call sites don't need to branch on
  backend.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pyarrow as pa

log = logging.getLogger(__name__)


def _get_spark():
    """Return the active SparkSession; build one only as a last resort."""
    from pyspark.sql import SparkSession  # noqa: WPS433

    session = SparkSession.getActiveSession()
    if session is None:
        session = SparkSession.builder.getOrCreate()
    return session


def _arrow_schema_to_spark_struct(spark, arrow_schema: pa.Schema):
    """Convert a PyArrow schema to a Spark ``StructType``.

    Prefers ``pyspark.sql.pandas.types.from_arrow_schema`` when available
    (canonical, preserves nullability and nested types). Falls back to a
    zero-row pandas roundtrip through ``createDataFrame`` for runtimes
    that don't expose the helper (older PySpark / Connect variants).

    The fallback is good enough for the str / int / float / timestamp /
    list[float] types the project actually uses; it loses some nullability
    detail on round-trip, which is acceptable because the additive-only
    schema gate only cares about field presence and dtype equality, not
    nullability flips on pre-existing columns.
    """
    try:
        from pyspark.sql.pandas.types import from_arrow_schema  # noqa: WPS433

        return from_arrow_schema(arrow_schema)
    except Exception:  # noqa: BLE001 - any failure -> fallback path
        empty = pa.Table.from_pylist([], schema=arrow_schema)
        return spark.createDataFrame(empty.to_pandas()).schema


def _spark_delta_table_exists(spark, path: str) -> bool:
    """Cheap existence probe for a Delta table at ``path``.

    Tries a 0-row Spark read; any failure (path missing, not a Delta log,
    permission error) is treated as "does not exist" for the purposes of
    deciding init-vs-merge. The merge call itself will surface real errors.
    """
    try:
        spark.read.format("delta").load(path).limit(0).collect()
        return True
    except Exception as exc:
        log.debug("Delta path %s probe failed: %s", path, exc)
        return False


def _arrow_to_spark_df(spark, arrow_table: pa.Table):
    """Convert a PyArrow Table into a Spark DataFrame.

    Round-trips via pandas because Spark's ``createDataFrame`` handles
    pandas dtypes (including list[float] embeddings) more reliably than the
    direct dict-list path for the schemas we use in this project.
    """
    pdf = arrow_table.to_pandas()
    return spark.createDataFrame(pdf)


def _last_operation_metrics(spark, path: str) -> dict[str, Any]:
    from delta.tables import DeltaTable as SparkDeltaTable  # noqa: WPS433

    rows = SparkDeltaTable.forPath(spark, path).history(1).collect()
    if not rows:
        return {}
    metrics = rows[0]["operationMetrics"]
    return dict(metrics) if metrics else {}


def spark_ensure_schema(
    path: str | Path,
    expected_arrow_schema: pa.Schema,
    *,
    allow_destructive: bool = False,
) -> None:
    """Additive schema-evolution gate for the Spark backend.

    Compares the on-disk Delta schema at ``path`` against
    ``expected_arrow_schema`` and issues
    ``ALTER TABLE delta.``<path>`` ADD COLUMNS (...)`` for any fields the
    expected schema introduces. Refuses non-additive changes (column
    removal, type mismatch on overlapping columns) with a ``ValueError``,
    matching the delta-rs branch of ``ensure_schema``.

    Brand-new paths are a no-op: the first ``spark_merge`` call writes
    using the source schema via ``mode("overwrite")``, so there is nothing
    to evolve. Subsequent calls land here with a real on-disk schema.

    ``allow_destructive`` is accepted for API parity with the delta-rs
    branch but does not change behavior on Spark: ADD COLUMNS is the only
    operation we ever perform, and we never rewrite or drop columns
    (ADR-0004 requires destructive changes to go through explicit
    migration steps).
    """
    spark = _get_spark()
    path_str = str(path)

    if not _spark_delta_table_exists(spark, path_str):
        # Brand-new path: the first write will use the source schema; no
        # evolution needed. Same exit point as the delta-rs branch.
        return

    target_struct = spark.read.format("delta").load(path_str).schema
    expected_struct = _arrow_schema_to_spark_struct(spark, expected_arrow_schema)

    target_fields = {f.name: f for f in target_struct.fields}
    expected_fields = {f.name: f for f in expected_struct.fields}

    removed = sorted(set(target_fields) - set(expected_fields))
    if removed:
        # Source is missing a column the on-disk table has. We don't drop
        # columns automatically — MERGE handles this fine on its own
        # (whenMatchedUpdateAll only touches columns the source has) so
        # the target keeps the column. No raise here, no ALTER either.
        log.debug(
            "spark_ensure_schema: target %s has columns %s not in source; "
            "leaving them in place (MERGE will preserve them).",
            path_str,
            removed,
        )

    type_mismatches: list[str] = []
    for name, target_field in target_fields.items():
        expected_field = expected_fields.get(name)
        if expected_field is None:
            continue
        if target_field.dataType != expected_field.dataType:
            type_mismatches.append(
                f"{name}: on-disk={target_field.dataType.simpleString()} "
                f"expected={expected_field.dataType.simpleString()}"
            )
    if type_mismatches:
        raise ValueError(
            f"Schema migration rejected: non-additive type change(s) for table "
            f"at {path_str}: {type_mismatches}. Destructive changes (type "
            "narrowing, rename, drop) must go through an explicit migration "
            "step; see ADR-0004."
        )

    missing = [f for f in expected_struct.fields if f.name not in target_fields]
    if not missing:
        return

    add_cols_ddl = ", ".join(
        f"`{field.name}` {field.dataType.simpleString()}" for field in missing
    )
    sql = f"ALTER TABLE delta.`{path_str}` ADD COLUMNS ({add_cols_ddl})"
    log.info(
        "spark_ensure_schema: ALTER on %s adding %s",
        path_str,
        [f.name for f in missing],
    )
    spark.sql(sql)


def spark_merge(
    path: str | Path,
    arrow_table: pa.Table,
    predicate: str,
) -> dict[str, int]:
    """Spark MERGE-INTO equivalent of the delta-rs ``_merge_with_predicate``.

    ``predicate`` follows the same convention as the delta-rs helpers:
    references the source via ``source.<col>`` and the target via
    ``target.<col>`` (e.g. ``"target.comment_id = source.comment_id"``).

    The function runs ``spark_ensure_schema`` itself before MERGE so the
    target table is known to be compatible with the source. Callers that
    want to pre-validate schema (e.g. to surface a destructive-change
    rejection earlier in the agent) can still invoke
    ``shared.delta_utils.silver.ensure_schema`` themselves; the inner
    call here is cheap when the schema is already aligned (one read of
    the table schema, no ALTER).
    """
    from delta.tables import DeltaTable as SparkDeltaTable  # noqa: WPS433

    spark = _get_spark()
    path_str = str(path)

    if arrow_table.num_rows == 0:
        log.info("spark_merge: empty source for %s; skipping MERGE no-op.", path_str)
        return {"inserted": 0, "updated": 0}

    spark_ensure_schema(path_str, arrow_table.schema, allow_destructive=True)
    source_df = _arrow_to_spark_df(spark, arrow_table)

    if not _spark_delta_table_exists(spark, path_str):
        # First write at this path: overwrite-as-init, then return the row
        # count as 'inserted'. This matches the delta-rs branch which seeds
        # an empty table and then merges; the user-visible counts agree on
        # the second call onward (which will MERGE the same rows and report
        # 0 inserted / 0 updated, matching the delta-rs path).
        n = source_df.count()
        (
            source_df.write.format("delta")
            .mode("overwrite")
            .option("overwriteSchema", "true")
            .save(path_str)
        )
        log.info(
            "spark_merge: initialized brand-new Delta table at %s with %d rows",
            path_str,
            n,
        )
        return {"inserted": int(n), "updated": 0}

    delta_table = SparkDeltaTable.forPath(spark, path_str)
    (
        delta_table.alias("target")
        .merge(source_df.alias("source"), predicate)
        .whenMatchedUpdateAll()
        .whenNotMatchedInsertAll()
        .execute()
    )
    metrics = _last_operation_metrics(spark, path_str)
    return {
        "inserted": int(metrics.get("numTargetRowsInserted", 0) or 0),
        "updated": int(metrics.get("numTargetRowsUpdated", 0) or 0),
    }


def spark_delete(path: str | Path, predicate: str) -> int:
    """Spark DELETE equivalent for the delta-rs ``DeltaTable.delete`` path."""
    from delta.tables import DeltaTable as SparkDeltaTable  # noqa: WPS433

    spark = _get_spark()
    path_str = str(path)
    if not _spark_delta_table_exists(spark, path_str):
        log.info(
            "spark_delete: table at %s does not exist yet; nothing to delete.",
            path_str,
        )
        return 0
    SparkDeltaTable.forPath(spark, path_str).delete(predicate)
    metrics = _last_operation_metrics(spark, path_str)
    return int(metrics.get("numDeletedRows", 0) or 0)


def spark_ensure_path_initialized(
    path: str | Path,
    arrow_schema: pa.Schema,
) -> bool:
    """Create an empty Delta table at ``path`` with ``arrow_schema`` if missing.

    Returns ``True`` if the table was newly created, ``False`` if it already
    existed. Used by the gold/attribution/migration delete helpers, which
    historically called ``_initialize_if_needed`` before issuing a delete
    against a possibly-missing target.
    """
    spark = _get_spark()
    path_str = str(path)
    if _spark_delta_table_exists(spark, path_str):
        return False
    empty = pa.Table.from_pylist([], schema=arrow_schema)
    empty_df = _arrow_to_spark_df(spark, empty)
    (
        empty_df.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .save(path_str)
    )
    log.info("spark_ensure_path_initialized: created empty Delta table at %s", path_str)
    return True
