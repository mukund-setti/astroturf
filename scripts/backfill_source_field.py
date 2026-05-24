#!/usr/bin/env python3
"""backfill_source_field.py — one-time idempotent backfill of bronze.raw_comments.

Adds the ``source`` column (and the ``ecfs_*`` columns) via ``ensure_schema()``,
then sets ``source = "regulations_gov"`` on every existing row where it is NULL.
Re-running the script after a successful pass is a no-op (zero NULL ``source``
rows, zero writes). See ADR-0012.

Targets the local Delta table at ``./data/bronze/raw_comments`` by default;
pass ``--target databricks`` together with ``--catalog`` / ``--schema`` to run
against the Unity Catalog ``bronze.raw_comments`` table in a Databricks notebook.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc

# Allow importing absolute paths from root directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deltalake import DeltaTable, write_deltalake  # noqa: E402

from shared.delta_utils.silver import ensure_schema  # noqa: E402
from shared.schemas.comments import raw_comment_arrow_schema  # noqa: E402

log = logging.getLogger("backfill_source_field")

DEFAULT_LOCAL_PATH = "./data/bronze/raw_comments"


def _count_null_source(table: pa.Table) -> int:
    """Count rows where ``source`` is NULL. Returns total row count if column missing."""
    if "source" not in table.column_names:
        return table.num_rows
    null_mask = pc.is_null(table.column("source"))
    return int(pc.sum(pc.cast(null_mask, pa.int64())).as_py() or 0)


def backfill_local(path: str) -> dict[str, int]:
    """Add ``source`` column and backfill ``"regulations_gov"`` on NULL rows."""
    if not DeltaTable.is_deltatable(path):
        raise FileNotFoundError(f"No Delta table at {path}; nothing to backfill.")

    ensure_schema(path, raw_comment_arrow_schema(), allow_destructive=True)

    dt = DeltaTable(path)
    table = dt.to_pyarrow_table()
    rows_before = table.num_rows
    null_before = _count_null_source(table)

    log.info(
        "Pre-backfill: %s total rows, %s NULL-source rows at %s",
        rows_before,
        null_before,
        path,
    )

    if null_before == 0:
        log.info("No NULL-source rows; backfill is a no-op")
        return {
            "rows_before": rows_before,
            "rows_after": rows_before,
            "null_source_before": 0,
            "null_source_after": 0,
            "rows_updated": 0,
        }

    source_col = table.column("source")
    new_source = pc.fill_null(source_col, pa.scalar("regulations_gov", pa.string()))
    source_idx = table.schema.get_field_index("source")
    table = table.set_column(source_idx, "source", new_source)

    write_deltalake(
        path,
        table,
        mode="overwrite",
        schema_mode="overwrite",
    )

    dt = DeltaTable(path)
    after = dt.to_pyarrow_table()
    rows_after = after.num_rows
    null_after = _count_null_source(after)

    log.info(
        "Post-backfill: %s total rows, %s NULL-source rows",
        rows_after,
        null_after,
    )

    if null_after != 0:
        raise RuntimeError(
            f"Backfill incomplete: {null_after} rows still have NULL source"
        )

    return {
        "rows_before": rows_before,
        "rows_after": rows_after,
        "null_source_before": null_before,
        "null_source_after": null_after,
        "rows_updated": null_before,
    }


def backfill_databricks(catalog: str, schema: str, table_name: str) -> dict[str, int]:
    """Run the same backfill against a Unity Catalog Delta table.

    Imported lazily so the script imports cleanly outside Databricks.
    """
    try:
        from pyspark.sql import SparkSession  # noqa: WPS433
        from pyspark.sql import functions as F  # noqa: WPS433
    except ImportError as e:  # pragma: no cover - environment-dependent
        raise RuntimeError(
            "pyspark is not available; run --target databricks from a Databricks notebook."
        ) from e

    fq = f"`{catalog}`.`{schema}`.`{table_name}`"
    spark = SparkSession.builder.getOrCreate()

    df = spark.read.table(fq)
    rows_before = df.count()
    null_before = df.filter(F.col("source").isNull()).count()
    log.info(
        "Pre-backfill: %s total rows, %s NULL-source rows at %s",
        rows_before,
        null_before,
        fq,
    )

    if null_before == 0:
        return {
            "rows_before": rows_before,
            "rows_after": rows_before,
            "null_source_before": 0,
            "null_source_after": 0,
            "rows_updated": 0,
        }

    spark.sql(f"UPDATE {fq} SET source = 'regulations_gov' WHERE source IS NULL")

    after = spark.read.table(fq)
    rows_after = after.count()
    null_after = after.filter(F.col("source").isNull()).count()

    if null_after != 0:
        raise RuntimeError(
            f"Backfill incomplete: {null_after} rows still have NULL source"
        )

    return {
        "rows_before": rows_before,
        "rows_after": rows_after,
        "null_source_before": null_before,
        "null_source_after": null_after,
        "rows_updated": null_before,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=("local", "databricks"),
        default="local",
        help="Backfill target. local => path-based Delta; databricks => UC table.",
    )
    parser.add_argument(
        "--bronze-path",
        default=DEFAULT_LOCAL_PATH,
        help="Local Delta table path (for --target local).",
    )
    parser.add_argument(
        "--catalog",
        default="workspace",
        help="UC catalog (for --target databricks).",
    )
    parser.add_argument(
        "--schema",
        default="bronze",
        help="UC schema (for --target databricks).",
    )
    parser.add_argument(
        "--table",
        default="raw_comments",
        help="UC table name (for --target databricks).",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.target == "local":
        result = backfill_local(str(Path(args.bronze_path)))
    else:
        result = backfill_databricks(args.catalog, args.schema, args.table)

    log.info("Backfill complete: %s", result)
    print("Backfill summary:")
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
