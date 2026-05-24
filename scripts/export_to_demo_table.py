#!/usr/bin/env python3
"""scripts/export_to_demo_table.py — Materialize gold cluster data to a flat UI-ready demo table.

Supports local Parquet folder export and live Databricks SQL Warehouse CTAS operations.
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

# Add root folder to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.schemas.cluster_review_export import (
    EXACT_HASH_BACKEND,
    SOURCE_EXACT_HASH,
    SOURCE_SEMANTIC,
    TEXT_PREVIEW_CHAR_LIMIT,
    ClusterReviewExportRow,
    cluster_review_export_arrow_schema,
)

log = logging.getLogger("export_to_demo_table")


def load_simple_env() -> None:
    """Load environment variables from a local .env file using simple rules."""
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip().strip('"').strip("'")


def _load_delta_frame(
    path: str,
    *,
    columns: list[str] | None = None,
    filters: list[tuple[str, str, Any]] | None = None,
) -> pd.DataFrame:
    """Load a Delta table into pandas with filtering support."""
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
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, datetime):
        return value
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    return ts.to_pydatetime()


def _best_attribution_by_cluster(
    attributions: pd.DataFrame | None,
) -> dict[str, dict[str, Any]]:
    """Pick the highest-confidence attribution row per cluster (if any)."""
    if attributions is None or attributions.empty:
        return {}
    required = {"cluster_id", "confidence_score"}
    if not required.issubset(attributions.columns):
        return {}
    df = attributions.copy()
    df["confidence_score"] = df["confidence_score"].astype(float)
    df = df.sort_values(by=["cluster_id", "confidence_score"], ascending=[True, False])
    result: dict[str, dict[str, Any]] = {}
    for cluster_id, group in df.groupby("cluster_id"):
        first = group.iloc[0].to_dict()
        result[str(cluster_id)] = first
    return result


def _best_migration_by_cluster(
    migrations: pd.DataFrame | None,
) -> dict[str, dict[str, Any]]:
    """Pick the highest-confidence migration row per cluster (if any)."""
    if migrations is None or migrations.empty:
        return {}
    required = {"cluster_id", "confidence_score"}
    if not required.issubset(migrations.columns):
        return {}
    df = migrations.copy()
    df["confidence_score"] = df["confidence_score"].astype(float)
    df = df.sort_values(by=["cluster_id", "confidence_score"], ascending=[True, False])
    result: dict[str, dict[str, Any]] = {}
    for cluster_id, group in df.groupby("cluster_id"):
        first = group.iloc[0].to_dict()
        result[str(cluster_id)] = first
    return result


def build_export_rows(
    *,
    clusters: pd.DataFrame,
    memberships: pd.DataFrame,
    parsed_comments: pd.DataFrame,
    raw_comments: pd.DataFrame | None,
    topic_id: str,
    agency_id: str,
    exported_at: datetime,
    attributions: pd.DataFrame | None = None,
    migrations: pd.DataFrame | None = None,
) -> list[ClusterReviewExportRow]:
    """Join input data frames into validated export rows."""
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
        "mean_similarity",
        "min_similarity",
    ]
    cluster_slim = clusters[
        [c for c in cluster_columns if c in clusters.columns]
    ].copy()

    membership_columns = [
        "cluster_id",
        "comment_id",
        "text_source",
        "text_hash",
        "similarity_to_representative",
    ]
    membership_cols_exist = [c for c in membership_columns if c in memberships.columns]
    membership_slim = memberships[membership_cols_exist].copy()

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
            for column in [
                "comment_id",
                "submitter_name",
                "organization",
                "state_province_region",
                "country",
            ]
            if column in raw_comments.columns
        ]
        if "comment_id" in raw_columns:
            joined = joined.merge(
                raw_comments[raw_columns], on="comment_id", how="left"
            )

    representative_text_by_cluster = _representative_text_by_cluster(joined)
    exact_ratio_by_cluster = _exact_match_ratio_by_cluster(joined)
    attribution_by_cluster = _best_attribution_by_cluster(attributions)
    migration_by_cluster = _best_migration_by_cluster(migrations)

    rows: list[ClusterReviewExportRow] = []
    for record in joined.to_dict(orient="records"):
        preview_source = record.get("raw_text") or record.get("normalized_text")
        cluster_id = str(record["cluster_id"])
        exact_ratio = exact_ratio_by_cluster.get(cluster_id)
        attribution_row = attribution_by_cluster.get(cluster_id)
        migration_row = migration_by_cluster.get(cluster_id)
        rows.append(
            ClusterReviewExportRow(
                cluster_id=cluster_id,
                docket_id=str(record["docket_id"]),
                topic_id=topic_id,
                agency_id=agency_id,
                embedding_model=str(record["embedding_model"]),
                similarity_threshold=float(record["similarity_threshold"]),
                cluster_size=int(record["cluster_size"]),
                representative_comment_id=str(record["representative_comment_id"]),
                representative_text=representative_text_by_cluster.get(cluster_id),
                comment_id=str(record["comment_id"]),
                member_comment_id=str(record["comment_id"]),
                is_representative=str(record["comment_id"])
                == str(record["representative_comment_id"]),
                text_source=_optional_str(record.get("text_source")),
                text_preview=truncate_text(preview_source),
                member_text=truncate_text(preview_source, limit=2000),
                similarity=_optional_float(record.get("similarity_to_representative")),
                submitter_name=_optional_str(record.get("submitter_name")),
                submitter_organization=_optional_str(record.get("organization")),
                submitter_state=_optional_str(record.get("state_province_region")),
                submitter_country=_optional_str(record.get("country")),
                posted_date=_optional_datetime(record.get("posted_date")),
                source=classify_source(record.get("embedding_backend")),
                exact_match_ratio=exact_ratio,
                near_duplicate_ratio=(
                    1.0 - exact_ratio if exact_ratio is not None else None
                ),
                purity_score=_optional_float(record.get("min_similarity")),
                confidence_score=_optional_float(record.get("mean_similarity")),
                candidate_entity_name=_optional_str(
                    attribution_row.get("candidate_entity_name")
                    if attribution_row
                    else None
                ),
                candidate_entity_type=_optional_str(
                    attribution_row.get("candidate_entity_type")
                    if attribution_row
                    else None
                ),
                attribution_confidence=_optional_float(
                    attribution_row.get("confidence_score") if attribution_row else None
                ),
                attribution_evidence_url=_optional_str(
                    attribution_row.get("candidate_url") if attribution_row else None
                ),
                migration_match_type=_optional_str(
                    migration_row.get("match_type") if migration_row else None
                ),
                migration_section=_optional_str(
                    migration_row.get("final_rule_section") if migration_row else None
                ),
                migration_similarity=_optional_float(
                    migration_row.get("similarity_score") if migration_row else None
                ),
                migration_claim_scope=_optional_str(
                    migration_row.get("claim_scope") if migration_row else None
                ),
                exported_at=exported_at,
            )
        )

    rows.sort(key=lambda row: (row.cluster_id, row.comment_id))
    return rows


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _representative_text_by_cluster(joined: pd.DataFrame) -> dict[str, str | None]:
    if joined.empty:
        return {}
    result: dict[str, str | None] = {}
    for cluster_id, cluster_rows in joined.groupby("cluster_id"):
        rep_id = str(cluster_rows.iloc[0]["representative_comment_id"])
        rep_rows = cluster_rows[cluster_rows["comment_id"].astype(str) == rep_id]
        source_row = rep_rows.iloc[0] if not rep_rows.empty else cluster_rows.iloc[0]
        result[str(cluster_id)] = truncate_text(
            source_row.get("raw_text") or source_row.get("normalized_text"),
            limit=2000,
        )
    return result


def _exact_match_ratio_by_cluster(joined: pd.DataFrame) -> dict[str, float | None]:
    if joined.empty or "text_hash" not in joined.columns:
        return {}
    result: dict[str, float | None] = {}
    for cluster_id, cluster_rows in joined.groupby("cluster_id"):
        hashes = [
            str(value)
            for value in cluster_rows["text_hash"].tolist()
            if _optional_str(value) is not None
        ]
        if not hashes:
            result[str(cluster_id)] = None
            continue
        counts = pd.Series(hashes).value_counts()
        result[str(cluster_id)] = float(counts.iloc[0] / len(cluster_rows))
    return result


def rows_to_arrow(rows: list[ClusterReviewExportRow]) -> pa.Table:
    schema = cluster_review_export_arrow_schema()
    columns: dict[str, list[Any]] = {name: [] for name in schema.names}
    for row in rows:
        data = row.model_dump()
        for name in columns:
            columns[name].append(data[name])
    return pa.Table.from_pydict(columns, schema=schema)


def build_databricks_export_sql(
    *,
    catalog: str,
    output_target: str,
    docket_id: str,
    topic_id: str,
    agency_id: str,
    embedding_model: str,
    similarity_threshold: float,
) -> str:
    docket = _sql_literal(docket_id)
    topic = _sql_literal(topic_id)
    agency = _sql_literal(agency_id)
    model = _sql_literal(embedding_model)
    return f"""
CREATE OR REPLACE TABLE {output_target} AS
WITH joined AS (
    SELECT
        c.cluster_id,
        c.docket_id,
        {topic} AS topic_id,
        {agency} AS agency_id,
        c.embedding_model,
        c.similarity_threshold,
        c.cluster_size,
        c.representative_comment_id,
        m.comment_id,
        CAST(m.comment_id = c.representative_comment_id AS BOOLEAN)
            AS is_representative,
        m.text_source,
        m.text_hash,
        m.similarity_to_representative,
        SUBSTR(
            REGEXP_REPLACE(COALESCE(p.raw_text, p.normalized_text, ''), '\\\\s+', ' '),
            1,
            500
        ) AS text_preview,
        SUBSTR(
            REGEXP_REPLACE(COALESCE(p.raw_text, p.normalized_text, ''), '\\\\s+', ' '),
            1,
            2000
        ) AS member_text,
        r.submitter_name,
        r.organization AS submitter_organization,
        r.state_province_region AS submitter_state,
        r.country AS submitter_country,
        p.posted_date,
        c.embedding_backend,
        c.mean_similarity,
        c.min_similarity
    FROM {catalog}.gold.comment_clusters c
    JOIN {catalog}.gold.comment_cluster_memberships m
        ON c.cluster_id = m.cluster_id
    LEFT JOIN {catalog}.silver.parsed_comments p
        ON m.comment_id = p.comment_id
    LEFT JOIN {catalog}.bronze.raw_comments r
        ON m.comment_id = r.comment_id
    WHERE c.docket_id = {docket}
      AND c.embedding_model = {model}
      AND ABS(c.similarity_threshold - {similarity_threshold}) < 1e-9
),
cluster_stats AS (
    SELECT
        cluster_id,
        MAX(CASE WHEN is_representative THEN member_text END) AS representative_text,
        MAX(hash_count) / COUNT(*) AS exact_match_ratio
    FROM (
        SELECT
            joined.*,
            COUNT(*) OVER (PARTITION BY cluster_id, text_hash) AS hash_count
        FROM joined
    )
    GROUP BY cluster_id
)
SELECT
    j.cluster_id,
    j.docket_id,
    j.topic_id,
    j.agency_id,
    j.embedding_model,
    j.similarity_threshold,
    j.cluster_size,
    j.representative_comment_id,
    COALESCE(s.representative_text, j.member_text) AS representative_text,
    j.comment_id,
    j.comment_id AS member_comment_id,
    j.is_representative,
    j.text_source,
    j.text_preview,
    j.member_text,
    j.similarity_to_representative AS similarity,
    j.submitter_name,
    j.submitter_organization,
    j.submitter_state,
    j.submitter_country,
    j.posted_date,
    CASE
        WHEN j.embedding_backend = 'exact_hash' THEN 'exact_hash'
        ELSE 'semantic'
    END AS source,
    s.exact_match_ratio,
    1.0 - s.exact_match_ratio AS near_duplicate_ratio,
    j.min_similarity AS purity_score,
    j.mean_similarity AS confidence_score,
    CURRENT_TIMESTAMP() AS exported_at
FROM joined j
LEFT JOIN cluster_stats s
    ON j.cluster_id = s.cluster_id
"""


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def export_to_demo_table(
    *,
    docket_id: str,
    topic_id: str,
    agency_id: str,
    embedding_model: str,
    similarity_threshold: float,
    clusters_path: str,
    memberships_path: str,
    parsed_comments_path: str,
    raw_comments_path: str | None,
    output_target: str,
    mode: str = "local",
    overwrite: bool = False,
    dry_run: bool = False,
    attributions_path: str | None = None,
    migrations_path: str | None = None,
) -> None:
    """Orchestrate denormalization and export depending on local vs. Databricks mode."""
    exported_at = datetime.now(timezone.utc)

    if mode == "local":
        log.info("Executing local export to Parquet directory: %s", output_target)
        target_dir = Path(output_target)
        if target_dir.exists() and any(target_dir.iterdir()):
            if not overwrite:
                raise FileExistsError(
                    f"Output directory {target_dir} is not empty. Use overwrite=True."
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
                columns=[
                    "comment_id",
                    "submitter_name",
                    "organization",
                    "state_province_region",
                    "country",
                ],
            )

        # Attribution + migration are optional. Absence MUST NOT break the
        # export (ADR-0015 / Phase 8 acceptance criteria).
        attributions: pd.DataFrame | None = None
        if attributions_path and DeltaTable.is_deltatable(attributions_path):
            try:
                attributions = _load_delta_frame(
                    attributions_path,
                    filters=[("docket_id", "=", docket_id)],
                )
            except Exception as exc:
                log.warning(
                    "Skipping attributions at %s due to load error: %s",
                    attributions_path,
                    exc,
                )

        migrations: pd.DataFrame | None = None
        if migrations_path and DeltaTable.is_deltatable(migrations_path):
            try:
                migrations = _load_delta_frame(
                    migrations_path,
                    filters=[("docket_id", "=", docket_id)],
                )
            except Exception as exc:
                log.warning(
                    "Skipping migrations at %s due to load error: %s",
                    migrations_path,
                    exc,
                )

        rows = build_export_rows(
            clusters=clusters,
            memberships=memberships,
            parsed_comments=parsed_comments,
            raw_comments=raw_comments,
            topic_id=topic_id,
            agency_id=agency_id,
            exported_at=exported_at,
            attributions=attributions,
            migrations=migrations,
        )

        target_dir.mkdir(parents=True, exist_ok=True)
        table = rows_to_arrow(rows)
        pq.write_table(table, target_dir / "cluster_review_export.parquet")
        log.info("Local Parquet export completed successfully. Rows: %d", len(rows))

    else:
        log.info(
            "Executing remote Databricks SQL Warehouse CTAS statement. Target Table: %s",
            output_target,
        )
        # Parse catalog from table name
        catalog = output_target.split(".")[0] if "." in output_target else "workspace"

        sql_query = build_databricks_export_sql(
            catalog=catalog,
            output_target=output_target,
            docket_id=docket_id,
            topic_id=topic_id,
            agency_id=agency_id,
            embedding_model=embedding_model,
            similarity_threshold=similarity_threshold,
        )
        if dry_run:
            print(f"CREATE SCHEMA IF NOT EXISTS {catalog}.demo;")
            print(sql_query)
            return

        from databricks import sql

        host = (
            os.environ.get("DATABRICKS_HOST", "")
            .replace("https://", "")
            .replace("http://", "")
            .split("/")[0]
        )
        path = os.environ.get("DATABRICKS_HTTP_PATH", "")
        token = os.environ.get("DATABRICKS_TOKEN", "")
        if not host or not path or not token:
            raise RuntimeError(
                "Databricks export requires DATABRICKS_HOST, DATABRICKS_TOKEN, "
                "and DATABRICKS_HTTP_PATH."
            )

        connection = sql.connect(
            server_hostname=host, http_path=path, access_token=token
        )
        cursor = connection.cursor()
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {catalog}.demo")
        log.info("Running SQL statement against SQL Warehouse...")
        cursor.execute(sql_query)
        cursor.close()
        connection.close()
        log.info("Databricks SQL Warehouse export materialized successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize joined gold clusters and silver comments to UI-ready review export."
    )
    parser.add_argument("--docket-id", required=True)
    parser.add_argument("--topic-id", required=True)
    parser.add_argument("--agency-id", required=True)
    parser.add_argument("--embedding-model", required=True)
    parser.add_argument("--threshold", type=float, default=0.92)
    parser.add_argument("--clusters-path", default="./data/gold/comment_clusters")
    parser.add_argument(
        "--memberships-path", default="./data/gold/comment_cluster_memberships"
    )
    parser.add_argument(
        "--parsed-comments-path", default="./data/silver/parsed_comments"
    )
    parser.add_argument("--raw-comments-path", default="./data/bronze/raw_comments")
    parser.add_argument("--output-target", required=True)
    parser.add_argument("--mode", choices=("local", "databricks"), default="local")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print SQL without executing"
    )
    parser.add_argument(
        "--attributions-path",
        default="./data/gold/campaign_attributions",
        help=(
            "Optional path to gold.campaign_attributions. Export proceeds "
            "without these fields if the table is absent."
        ),
    )
    parser.add_argument(
        "--migrations-path",
        default="./data/gold/rule_migrations",
        help=(
            "Optional path to gold.rule_migrations. Export proceeds without "
            "these fields if the table is absent."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )

    load_simple_env()

    export_to_demo_table(
        docket_id=args.docket_id,
        topic_id=args.topic_id,
        agency_id=args.agency_id,
        embedding_model=args.embedding_model,
        similarity_threshold=args.threshold,
        clusters_path=args.clusters_path,
        memberships_path=args.memberships_path,
        parsed_comments_path=args.parsed_comments_path,
        raw_comments_path=args.raw_comments_path,
        output_target=args.output_target,
        mode=args.mode,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
        attributions_path=args.attributions_path,
        migrations_path=args.migrations_path,
    )


if __name__ == "__main__":
    main()
