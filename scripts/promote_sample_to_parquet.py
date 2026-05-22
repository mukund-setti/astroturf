#!/usr/bin/env python3
"""promote_sample_to_parquet.py — export a curated Databricks promotion sample.

Reads the local delta-rs lakehouse under ``./data`` and writes Parquet snapshots
of the curated EPA-HQ-OAR-2021-0317 sample (plus an optional CFPB-2016-0025
slice) to ``./data/exports/uc_sample/<table_name>/``. The Parquet files are the
upload payload for ``astroturf.bronze.raw_imports`` per ``docs/databricks-uc-
promotion.md``.

The sample includes:

- All ``EPA-HQ-OAR-2021-0317`` rows from bronze, parsed, details, attachments,
  the ``databricks-bge-large-en`` slice of ``silver.comment_embeddings``, and
  the gold clusters/memberships for the same docket + model.
- Optionally, the equivalent ``CFPB-2016-0025`` slice when
  ``--include-cfpb-sample`` is passed (skipped by default).

Schemas are pinned to the Pydantic-derived Arrow schemas under
``shared/schemas/`` so the Parquet payload matches the Unity Catalog Delta
table definitions in ``docs/databricks-integration.md``.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from typing import Any, Callable

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from deltalake import DeltaTable

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.schemas.comment_attachments import comment_attachment_arrow_schema
from shared.schemas.comment_clusters import (
    comment_cluster_arrow_schema,
    comment_cluster_membership_arrow_schema,
)
from shared.schemas.comment_details import comment_detail_arrow_schema
from shared.schemas.comment_embeddings import comment_embedding_arrow_schema
from shared.schemas.comments import raw_comment_arrow_schema
from shared.schemas.parsed_comments import parsed_comment_arrow_schema

log = logging.getLogger(__name__)

EPA_DOCKET = "EPA-HQ-OAR-2021-0317"
CFPB_DOCKET = "CFPB-2016-0025"
DATABRICKS_EMBEDDING_MODEL = "databricks-bge-large-en"

DEFAULT_DATA_DIR = "./data"
DEFAULT_OUTPUT_DIR = "./data/exports/uc_sample"


@dataclass(frozen=True)
class TableExport:
    """One Unity Catalog table to export from the local lakehouse."""

    name: str
    source_subpath: str
    schema_fn: Callable[[], pa.Schema]
    filter_model: bool  # additionally filter by embedding_model = bge-large-en
    has_comment_id: bool  # row carries a comment_id we can restrict to the slice


TABLE_EXPORTS: tuple[TableExport, ...] = (
    TableExport(
        name="bronze.raw_comments",
        source_subpath="bronze/raw_comments",
        schema_fn=raw_comment_arrow_schema,
        filter_model=False,
        has_comment_id=True,
    ),
    TableExport(
        name="silver.parsed_comments",
        source_subpath="silver/parsed_comments",
        schema_fn=parsed_comment_arrow_schema,
        filter_model=False,
        has_comment_id=True,
    ),
    TableExport(
        name="silver.comment_details",
        source_subpath="silver/comment_details",
        schema_fn=comment_detail_arrow_schema,
        filter_model=False,
        has_comment_id=True,
    ),
    TableExport(
        name="silver.comment_attachments",
        source_subpath="silver/comment_attachments",
        schema_fn=comment_attachment_arrow_schema,
        filter_model=False,
        has_comment_id=True,
    ),
    TableExport(
        name="silver.comment_embeddings",
        source_subpath="silver/comment_embeddings",
        schema_fn=comment_embedding_arrow_schema,
        filter_model=True,
        has_comment_id=True,
    ),
    TableExport(
        name="gold.comment_clusters",
        source_subpath="gold/comment_clusters",
        schema_fn=comment_cluster_arrow_schema,
        filter_model=True,
        has_comment_id=False,
    ),
    TableExport(
        name="gold.comment_cluster_memberships",
        source_subpath="gold/comment_cluster_memberships",
        schema_fn=comment_cluster_membership_arrow_schema,
        filter_model=True,
        has_comment_id=True,
    ),
)


def load_delta(path: str) -> pa.Table | None:
    """Read a local Delta table as a pyarrow Table, or return None if missing."""
    if not DeltaTable.is_deltatable(path):
        log.warning("Delta table not found at %s — skipping", path)
        return None
    return DeltaTable(path).to_pyarrow_table()


def filter_table(
    table: pa.Table,
    *,
    dockets: list[str],
    filter_model: bool,
    embedding_model: str,
    docket_comment_ids: dict[str, list[str]] | None = None,
    has_comment_id: bool = False,
) -> pa.Table:
    """Filter a pyarrow table to the configured docket(s), model, and slice.

    When ``docket_comment_ids`` is provided, rows for a docket in that map are
    further restricted to ``comment_id`` values in the per-docket slice.
    Dockets not in the map are unrestricted. Tables without a ``comment_id``
    column (``has_comment_id=False``) skip the per-comment filter entirely.
    """
    if "docket_id" not in table.column_names:
        return table.slice(0, 0)
    mask = pc.is_in(table["docket_id"], value_set=pa.array(dockets))
    if filter_model:
        if "embedding_model" not in table.column_names:
            return table.slice(0, 0)
        mask = pc.and_(
            mask,
            pc.equal(table["embedding_model"], pa.scalar(embedding_model)),
        )

    if docket_comment_ids and has_comment_id and "comment_id" in table.column_names:
        # For each restricted docket, keep only rows whose comment_id is in the
        # per-docket slice. Unrestricted dockets stay fully included.
        comment_id_col = table["comment_id"]
        docket_col = table["docket_id"]
        per_docket_mask = pa.array([False] * table.num_rows, type=pa.bool_())
        for docket in dockets:
            if docket in docket_comment_ids:
                slice_set = pa.array(docket_comment_ids[docket])
                docket_mask = pc.and_(
                    pc.equal(docket_col, pa.scalar(docket)),
                    pc.is_in(comment_id_col, value_set=slice_set),
                )
            else:
                docket_mask = pc.equal(docket_col, pa.scalar(docket))
            per_docket_mask = pc.or_(per_docket_mask, docket_mask)
        mask = pc.and_(mask, per_docket_mask)

    return table.filter(mask)


def load_cfpb_comment_id_slice(data_dir: str, *, docket: str) -> list[str]:
    """Return the curated CFPB comment_id slice from local silver.parsed_comments.

    The slice is exactly the comment_ids already promoted to
    ``silver.parsed_comments`` for the docket — every CFPB row in the export
    therefore has a corresponding parsed entry, which keeps the slice small and
    self-consistent. Returns an empty list when the parsed table is absent.
    """
    parsed_path = os.path.join(data_dir, "silver", "parsed_comments")
    parsed = load_delta(parsed_path)
    if parsed is None or "docket_id" not in parsed.column_names:
        return []
    docket_mask = pc.equal(parsed["docket_id"], pa.scalar(docket))
    docket_rows = parsed.filter(docket_mask)
    return docket_rows["comment_id"].to_pylist()


def coerce_to_schema(table: pa.Table, schema: pa.Schema) -> pa.Table:
    """Project ``table`` onto ``schema``, casting columns and filling missing ones.

    Missing columns are added as all-null. Extra columns are dropped. Column
    order is forced to match ``schema``. Casts use ``safe=False`` so timestamps
    with differing units cast cleanly.
    """
    columns: dict[str, pa.Array] = {}
    n_rows = table.num_rows
    for field in schema:
        if field.name in table.column_names:
            col = table[field.name]
            if col.type != field.type:
                col = col.cast(field.type, safe=False)
            columns[field.name] = col
        else:
            columns[field.name] = pa.nulls(n_rows, type=field.type)
    return pa.table(columns, schema=schema)


def output_path_for(output_dir: str, table_name: str) -> str:
    """Return the per-table output directory (e.g. .../bronze.raw_comments/)."""
    return os.path.join(output_dir, table_name)


def write_parquet(
    out_dir: str,
    arrow_table: pa.Table,
    *,
    overwrite: bool,
) -> str:
    """Write ``arrow_table`` as a single Parquet file under ``out_dir``.

    Refuses to write if ``out_dir`` already contains files, unless
    ``overwrite`` is set. Returns the Parquet file path.
    """
    if os.path.exists(out_dir):
        existing = [entry for entry in os.listdir(out_dir) if not entry.startswith(".")]
        if existing and not overwrite:
            raise FileExistsError(
                f"Refusing to overwrite existing export at {out_dir}. "
                "Pass --overwrite to replace it."
            )
        if existing and overwrite:
            shutil.rmtree(out_dir)

    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, "part-000.parquet")
    pq.write_table(arrow_table, target, compression="snappy")
    return target


def export_one(
    export: TableExport,
    *,
    data_dir: str,
    output_dir: str,
    dockets: list[str],
    embedding_model: str,
    overwrite: bool,
    docket_comment_ids: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Run a single table export and return a summary record."""
    source_path = os.path.join(data_dir, export.source_subpath)
    raw = load_delta(source_path)
    schema = export.schema_fn()

    if raw is None:
        coerced = pa.table({field.name: [] for field in schema}, schema=schema)
        filtered_rows = 0
    else:
        filtered = filter_table(
            raw,
            dockets=dockets,
            filter_model=export.filter_model,
            embedding_model=embedding_model,
            docket_comment_ids=docket_comment_ids,
            has_comment_id=export.has_comment_id,
        )
        coerced = coerce_to_schema(filtered, schema)
        filtered_rows = coerced.num_rows

    out_dir = output_path_for(output_dir, export.name)
    parquet_path = write_parquet(out_dir, coerced, overwrite=overwrite)

    return {
        "table": export.name,
        "source_path": source_path,
        "output_path": parquet_path,
        "row_count": filtered_rows,
        "source_exists": raw is not None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export a curated EPA + optional CFPB sample from the local "
            "delta-rs lakehouse as Parquet snapshots for Unity Catalog "
            "promotion."
        )
    )
    parser.add_argument(
        "--data-dir",
        default=DEFAULT_DATA_DIR,
        help="Root of the local lakehouse (default: ./data).",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=(
            "Output directory for the Parquet snapshot. One subdirectory per "
            "Unity Catalog table (default: ./data/exports/uc_sample)."
        ),
    )
    parser.add_argument(
        "--embedding-model",
        default=DATABRICKS_EMBEDDING_MODEL,
        help=(
            "embedding_model value to filter to in silver.comment_embeddings "
            "and the gold cluster tables (default: databricks-bge-large-en)."
        ),
    )
    parser.add_argument(
        "--include-cfpb-sample",
        action="store_true",
        help=(
            "Also include the CFPB-2016-0025 rows present locally. Off by "
            "default so the sample is the minimum-credible EPA slice."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing exports under the output directory.",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    dockets = [EPA_DOCKET]
    docket_comment_ids: dict[str, list[str]] = {}
    if args.include_cfpb_sample:
        dockets.append(CFPB_DOCKET)
        cfpb_slice = load_cfpb_comment_id_slice(args.data_dir, docket=CFPB_DOCKET)
        docket_comment_ids[CFPB_DOCKET] = cfpb_slice

    print("Starting Unity Catalog sample promotion export")
    print(f"Data dir:        {args.data_dir}")
    print(f"Output dir:      {args.output_dir}")
    print(f"Dockets:         {', '.join(dockets)}")
    print(f"Embedding model: {args.embedding_model}")
    print(f"Overwrite:       {args.overwrite}")
    if args.include_cfpb_sample:
        print(
            f"CFPB slice size: {len(docket_comment_ids.get(CFPB_DOCKET, []))} "
            f"comment_ids from silver.parsed_comments"
        )
    print()

    summaries: list[dict[str, Any]] = []
    for export in TABLE_EXPORTS:
        try:
            summary = export_one(
                export,
                data_dir=args.data_dir,
                output_dir=args.output_dir,
                dockets=dockets,
                embedding_model=args.embedding_model,
                overwrite=args.overwrite,
                docket_comment_ids=docket_comment_ids or None,
            )
        except FileExistsError as exc:
            print(f"\nERROR: {exc}", file=sys.stderr)
            sys.exit(2)
        summaries.append(summary)

    print("=" * 60)
    print("EXPORT SUMMARY")
    print("=" * 60)
    for summary in summaries:
        marker = "" if summary["source_exists"] else "  (source missing)"
        print(
            f"{summary['table']:<40} "
            f"rows={summary['row_count']:>7}  "
            f"-> {summary['output_path']}{marker}"
        )
    total_rows = sum(s["row_count"] for s in summaries)
    print("-" * 60)
    print(f"Total rows exported: {total_rows}")
    print("=" * 60)


if __name__ == "__main__":
    main()
