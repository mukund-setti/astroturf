#!/usr/bin/env python3
"""Export demo.cluster_review_export as Parquet for the dashboard / review UI.

This is the local equivalent of the Databricks Workflow's
``export_dashboard_data`` task. It joins ``gold.comment_clusters``,
``gold.comment_cluster_memberships``, and ``silver.parsed_comments`` for one
clustering run scope (docket + embedding model + similarity threshold) and
writes the joined dataset as Parquet under
``./data/exports/cluster_review_export/`` by default.

Idempotent: refuses to overwrite an existing output directory unless
``--overwrite`` is passed.
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from deltalake import DeltaTable

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.schemas.cluster_review_export import (
    EXACT_HASH_BACKEND,
    SOURCE_EXACT_HASH,
    SOURCE_SEMANTIC,
    TEXT_PREVIEW_CHAR_LIMIT,
    ClusterReviewExportRow,
    cluster_review_export_arrow_schema,
)

log = logging.getLogger(__name__)

DEFAULT_CLUSTERS_PATH = "./data/gold/comment_clusters"
DEFAULT_MEMBERSHIPS_PATH = "./data/gold/comment_cluster_memberships"
DEFAULT_PARSED_COMMENTS_PATH = "./data/silver/parsed_comments"
DEFAULT_RAW_COMMENTS_PATH = "./data/bronze/raw_comments"
DEFAULT_OUTPUT_DIR = "./data/exports/cluster_review_export"


def _load_delta_frame(
    path: str,
    *,
    columns: list[str] | None = None,
    filters: list[tuple[str, str, Any]] | None = None,
) -> pd.DataFrame:
    """Load a Delta table into pandas, with a fallback for older delta-rs."""
    if not DeltaTable.is_deltatable(path):
        raise FileNotFoundError(f"Delta table not found at {path}")

    table = DeltaTable(path)
    try:
        return table.to_pandas(columns=columns, filters=filters)
    except Exception:
        if not filters:
            raise
        df = table.to_pandas(columns=columns)
        return _apply_filters(df, filters)


def _apply_filters(
    df: pd.DataFrame, filters: list[tuple[str, str, Any]]
) -> pd.DataFrame:
    filtered = df
    for column, operator, value in filters:
        if column not in filtered.columns:
            return filtered.iloc[0:0].copy()
        if operator != "=":
            raise ValueError(f"Unsupported filter operator: {operator}")
        if isinstance(value, float):
            filtered = filtered[(filtered[column].astype(float) - value).abs() <= 1e-9]
        else:
            filtered = filtered[filtered[column] == value]
    return filtered.copy()


def truncate_text(value: Any, limit: int = TEXT_PREVIEW_CHAR_LIMIT) -> str | None:
    """Whitespace-collapse and truncate text for a preview column."""
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
    except TypeError:
        pass
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def classify_source(embedding_backend: Any) -> str:
    """Map an embedding backend onto the UI-facing source label."""
    if embedding_backend is None:
        return SOURCE_SEMANTIC
    if str(embedding_backend) == EXACT_HASH_BACKEND:
        return SOURCE_EXACT_HASH
    return SOURCE_SEMANTIC


def build_export_rows(
    *,
    clusters: pd.DataFrame,
    memberships: pd.DataFrame,
    parsed_comments: pd.DataFrame,
    raw_comments: pd.DataFrame | None,
    exported_at: datetime,
) -> list[ClusterReviewExportRow]:
    """Join the three input frames into validated export rows."""
    if clusters.empty or memberships.empty:
        return []

    cluster_columns = [
        "cluster_id",
        "docket_id",
        "embedding_model",
        "similarity_threshold",
        "cluster_size",
        "representative_comment_id",
        "embedding_backend",
    ]
    cluster_slim = clusters[
        [c for c in cluster_columns if c in clusters.columns]
    ].copy()

    membership_columns = [
        "cluster_id",
        "comment_id",
        "text_source",
    ]
    membership_slim = memberships[
        [c for c in membership_columns if c in memberships.columns]
    ].copy()

    joined = membership_slim.merge(cluster_slim, on="cluster_id", how="inner")

    parsed_columns = [
        column
        for column in ["comment_id", "raw_text", "normalized_text", "posted_date"]
        if column in parsed_comments.columns
    ]
    if "comment_id" in parsed_columns:
        joined = joined.merge(
            parsed_comments[parsed_columns], on="comment_id", how="left"
        )

    if raw_comments is not None and not raw_comments.empty:
        raw_columns = [
            column
            for column in ["comment_id", "submitter_name"]
            if column in raw_comments.columns
        ]
        if "comment_id" in raw_columns and "submitter_name" in raw_columns:
            joined = joined.merge(
                raw_comments[raw_columns], on="comment_id", how="left"
            )

    rows: list[ClusterReviewExportRow] = []
    for record in joined.to_dict(orient="records"):
        preview_source = record.get("raw_text") or record.get("normalized_text")
        rows.append(
            ClusterReviewExportRow(
                cluster_id=str(record["cluster_id"]),
                docket_id=str(record["docket_id"]),
                embedding_model=str(record["embedding_model"]),
                similarity_threshold=float(record["similarity_threshold"]),
                cluster_size=int(record["cluster_size"]),
                representative_comment_id=str(record["representative_comment_id"]),
                comment_id=str(record["comment_id"]),
                is_representative=str(record["comment_id"])
                == str(record["representative_comment_id"]),
                text_source=_optional_str(record.get("text_source")),
                text_preview=truncate_text(preview_source),
                submitter_name=_optional_str(record.get("submitter_name")),
                posted_date=_optional_datetime(record.get("posted_date")),
                source=classify_source(record.get("embedding_backend")),
                exported_at=exported_at,
            )
        )

    rows.sort(key=lambda row: (row.cluster_id, row.comment_id))
    return rows


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
    except TypeError:
        pass
    text = str(value).strip()
    return text or None


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
    except TypeError:
        pass
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    return ts.to_pydatetime()


def rows_to_arrow(rows: list[ClusterReviewExportRow]) -> pa.Table:
    schema = cluster_review_export_arrow_schema()
    columns: dict[str, list[Any]] = {name: [] for name in schema.names}
    for row in rows:
        data = row.model_dump()
        for name in columns:
            columns[name].append(data[name])
    return pa.Table.from_pydict(columns, schema=schema)


def write_parquet(rows: list[ClusterReviewExportRow], output_dir: Path) -> Path:
    """Write rows as a single Parquet file inside ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    table = rows_to_arrow(rows)
    output_file = output_dir / "cluster_review_export.parquet"
    pq.write_table(table, output_file)
    return output_file


def export_cluster_review_dataset(
    *,
    docket_id: str,
    embedding_model: str,
    similarity_threshold: float,
    clusters_path: str = DEFAULT_CLUSTERS_PATH,
    memberships_path: str = DEFAULT_MEMBERSHIPS_PATH,
    parsed_comments_path: str = DEFAULT_PARSED_COMMENTS_PATH,
    raw_comments_path: str | None = DEFAULT_RAW_COMMENTS_PATH,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    overwrite: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run the export end-to-end and return a small metadata dict."""
    target_dir = Path(output_dir)
    if target_dir.exists() and any(target_dir.iterdir()):
        if not overwrite:
            raise FileExistsError(
                f"Output directory {target_dir} is not empty. "
                "Re-run with --overwrite to replace it."
            )
        shutil.rmtree(target_dir)

    scope_filters = [
        ("docket_id", "=", docket_id),
        ("embedding_model", "=", embedding_model),
        ("similarity_threshold", "=", similarity_threshold),
    ]

    clusters = _load_delta_frame(clusters_path, filters=scope_filters)
    memberships = _load_delta_frame(memberships_path, filters=scope_filters)
    parsed_comments = _load_delta_frame(
        parsed_comments_path,
        filters=[("docket_id", "=", docket_id)],
        columns=[
            "comment_id",
            "docket_id",
            "raw_text",
            "normalized_text",
            "posted_date",
        ],
    )

    raw_comments: pd.DataFrame | None = None
    if raw_comments_path and DeltaTable.is_deltatable(raw_comments_path):
        raw_comments = _load_delta_frame(
            raw_comments_path,
            filters=[("docket_id", "=", docket_id)],
            columns=["comment_id", "submitter_name"],
        )

    exported_at = now or datetime.now(timezone.utc)
    rows = build_export_rows(
        clusters=clusters,
        memberships=memberships,
        parsed_comments=parsed_comments,
        raw_comments=raw_comments,
        exported_at=exported_at,
    )

    output_file = write_parquet(rows, target_dir)

    return {
        "docket_id": docket_id,
        "embedding_model": embedding_model,
        "similarity_threshold": similarity_threshold,
        "clusters_in_scope": int(len(clusters)),
        "memberships_in_scope": int(len(memberships)),
        "rows_written": len(rows),
        "output_file": str(output_file),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export demo.cluster_review_export as Parquet for the review UI. "
            "Local equivalent of the Databricks export_dashboard_data task."
        )
    )
    parser.add_argument("--docket-id", required=True, help="Regulations.gov docket ID")
    parser.add_argument("--embedding-model", required=True)
    parser.add_argument("--similarity-threshold", required=True, type=float)
    parser.add_argument("--clusters-path", default=DEFAULT_CLUSTERS_PATH)
    parser.add_argument("--memberships-path", default=DEFAULT_MEMBERSHIPS_PATH)
    parser.add_argument("--parsed-comments-path", default=DEFAULT_PARSED_COMMENTS_PATH)
    parser.add_argument("--raw-comments-path", default=DEFAULT_RAW_COMMENTS_PATH)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the output directory if it already exists.",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        summary = export_cluster_review_dataset(
            docket_id=args.docket_id,
            embedding_model=args.embedding_model,
            similarity_threshold=args.similarity_threshold,
            clusters_path=args.clusters_path,
            memberships_path=args.memberships_path,
            parsed_comments_path=args.parsed_comments_path,
            raw_comments_path=args.raw_comments_path,
            output_dir=args.output_dir,
            overwrite=args.overwrite,
        )
    except FileExistsError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"\nERROR: Cluster review export failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 50)
    print("CLUSTER REVIEW EXPORT SUMMARY")
    print("=" * 50)
    print(f"Docket ID:             {summary['docket_id']}")
    print(f"Embedding Model:       {summary['embedding_model']}")
    print(f"Similarity Threshold:  {summary['similarity_threshold']}")
    print(f"Clusters In Scope:     {summary['clusters_in_scope']}")
    print(f"Memberships In Scope:  {summary['memberships_in_scope']}")
    print(f"Rows Written:          {summary['rows_written']}")
    print(f"Output File:           {summary['output_file']}")
    print("=" * 50)


if __name__ == "__main__":
    main()
