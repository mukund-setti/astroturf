"""Unit tests for export_to_demo_table with optional attribution/migration.

Covers:
- Export works with attribution/migration tables absent (graceful fallback).
- Export works with attribution/migration tables present (fields populated).
- The ClusterReviewExportRow schema accepts the new fields as nullable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from scripts.export_to_demo_table import (
    build_export_rows,
    export_to_demo_table,
    rows_to_arrow,
)
from shared.delta_utils.attribution import merge_campaign_attributions
from shared.delta_utils.gold import (
    merge_comment_cluster_memberships,
    merge_comment_clusters,
)
from shared.delta_utils.migration import merge_rule_migrations
from shared.delta_utils.silver import merge_parsed_comments
from shared.schemas.campaign_attributions import (
    CampaignAttribution,
    campaign_attributions_arrow_schema,
)
from shared.schemas.cluster_review_export import (
    ClusterReviewExportRow,
    cluster_review_export_arrow_schema,
)
from shared.schemas.comment_clusters import (
    CommentCluster,
    CommentClusterMembership,
    comment_cluster_arrow_schema,
    comment_cluster_membership_arrow_schema,
)
from shared.schemas.parsed_comments import (
    ParsedComment,
    parsed_comment_arrow_schema,
)
from shared.schemas.rule_migrations import (
    RuleMigration,
    rule_migrations_arrow_schema,
)


def _arrow_from(rows: list[Any], schema: pa.Schema) -> pa.Table:
    columns: dict[str, list[Any]] = {n: [] for n in schema.names}
    for row in rows:
        d = row.model_dump()
        for n in columns:
            columns[n].append(d[n])
    return pa.Table.from_pydict(columns, schema=schema)


def _seed_cluster_world(tmp_path: Path) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    clusters_path = tmp_path / "gold" / "comment_clusters"
    memberships_path = tmp_path / "gold" / "comment_cluster_memberships"
    parsed_path = tmp_path / "silver" / "parsed_comments"

    cluster = CommentCluster(
        cluster_id="CLUSTER-A",
        clustering_run_id="run-1",
        docket_id="17-108",
        embedding_model="test-model",
        embedding_backend="test-backend",
        clustering_version="v1",
        similarity_threshold=0.92,
        candidate_count=2,
        cluster_size=2,
        representative_comment_id="C1",
        representative_text_hash="hash",
        mean_similarity=0.95,
        min_similarity=0.93,
        max_similarity=1.0,
        created_at=now,
        updated_at=now,
    )
    merge_comment_clusters(
        clusters_path, _arrow_from([cluster], comment_cluster_arrow_schema())
    )

    memberships = [
        CommentClusterMembership(
            cluster_id="CLUSTER-A",
            comment_id="C1",
            clustering_run_id="run-1",
            docket_id="17-108",
            embedding_model="test-model",
            embedding_backend="test-backend",
            clustering_version="v1",
            similarity_threshold=0.92,
            text_hash="hash",
            text_source="detail_comment_text",
            similarity_to_representative=1.0,
            membership_rank=1,
            created_at=now,
            updated_at=now,
        ),
        CommentClusterMembership(
            cluster_id="CLUSTER-A",
            comment_id="C2",
            clustering_run_id="run-1",
            docket_id="17-108",
            embedding_model="test-model",
            embedding_backend="test-backend",
            clustering_version="v1",
            similarity_threshold=0.92,
            text_hash="hash2",
            text_source="detail_comment_text",
            similarity_to_representative=0.94,
            membership_rank=2,
            created_at=now,
            updated_at=now,
        ),
    ]
    merge_comment_cluster_memberships(
        memberships_path,
        _arrow_from(memberships, comment_cluster_membership_arrow_schema()),
    )

    parsed = [
        ParsedComment(
            comment_id="C1",
            docket_id="17-108",
            source_system_version="test",
            parser_version="v1",
            text_source="detail_comment_text",
            raw_text="Representative campaign template text.",
            normalized_text="representative campaign template text.",
            normalized_text_hash="rt1",
            token_estimate=5,
            char_count=40,
            parse_status="ok",
            parsed_at=now,
        ),
        ParsedComment(
            comment_id="C2",
            docket_id="17-108",
            source_system_version="test",
            parser_version="v1",
            text_source="detail_comment_text",
            raw_text="Member text body.",
            normalized_text="member text body.",
            normalized_text_hash="rt2",
            token_estimate=3,
            char_count=20,
            parse_status="ok",
            parsed_at=now,
        ),
    ]
    merge_parsed_comments(
        parsed_path, _arrow_from(parsed, parsed_comment_arrow_schema())
    )
    return {
        "clusters_path": str(clusters_path),
        "memberships_path": str(memberships_path),
        "parsed_path": str(parsed_path),
    }


def test_export_works_without_attribution_or_migration(tmp_path: Path) -> None:
    paths = _seed_cluster_world(tmp_path)
    output_dir = tmp_path / "exports" / "no_attr"
    export_to_demo_table(
        docket_id="17-108",
        topic_id="telecom",
        agency_id="FCC",
        embedding_model="test-model",
        similarity_threshold=0.92,
        clusters_path=paths["clusters_path"],
        memberships_path=paths["memberships_path"],
        parsed_comments_path=paths["parsed_path"],
        raw_comments_path=None,
        output_target=str(output_dir),
        mode="local",
        overwrite=True,
        # Point at paths that don't exist — export must succeed regardless.
        attributions_path=str(tmp_path / "missing" / "attr"),
        migrations_path=str(tmp_path / "missing" / "mig"),
    )

    parquet_path = output_dir / "cluster_review_export.parquet"
    assert parquet_path.exists()
    table = pq.read_table(parquet_path)
    assert table.num_rows == 2
    # All attribution/migration columns must be present and null.
    for col in (
        "candidate_entity_name",
        "candidate_entity_type",
        "attribution_confidence",
        "attribution_evidence_url",
        "migration_match_type",
        "migration_section",
        "migration_similarity",
        "migration_claim_scope",
    ):
        assert col in table.column_names
        assert table.column(col).null_count == table.num_rows


def test_export_works_with_attribution_and_migration(tmp_path: Path) -> None:
    paths = _seed_cluster_world(tmp_path)
    now = datetime.now(timezone.utc)
    attr_path = tmp_path / "gold" / "attr"
    mig_path = tmp_path / "gold" / "mig"

    attribution = CampaignAttribution(
        attribution_id="attr-1",
        cluster_id="CLUSTER-A",
        docket_id="17-108",
        candidate_entity_name="Broadband for America",
        candidate_entity_type="trade_association",
        candidate_url="https://example.invalid/bfa",
        evidence_type="exact_phrase_match",
        matched_phrase="smothering innovation",
        evidence_excerpt="...smothering innovation...",
        confidence_score=0.85,
        confidence_label="high",
        reasoning_summary="Candidate source. Evidence match.",
        reviewed_status="unreviewed",
        created_at=now,
        metadata_json=None,
    )
    merge_campaign_attributions(
        attr_path,
        _arrow_from([attribution], campaign_attributions_arrow_schema()),
    )

    migration = RuleMigration(
        migration_id="mig-1",
        cluster_id="CLUSTER-A",
        docket_id="17-108",
        final_rule_document_id="doc1",
        final_rule_url="https://example.invalid/rule",
        final_rule_section="Section A",
        cluster_phrase="smothering innovation",
        rule_phrase="smothering innovation",
        similarity_score=1.0,
        match_type="exact",
        confidence_score=0.80,
        confidence_label="high",
        claim_scope="phrase_overlap",
        caveat_text="Language overlap only. Does not establish causality.",
        created_at=now,
        metadata_json=None,
    )
    merge_rule_migrations(
        mig_path,
        _arrow_from([migration], rule_migrations_arrow_schema()),
    )

    output_dir = tmp_path / "exports" / "with_attr"
    export_to_demo_table(
        docket_id="17-108",
        topic_id="telecom",
        agency_id="FCC",
        embedding_model="test-model",
        similarity_threshold=0.92,
        clusters_path=paths["clusters_path"],
        memberships_path=paths["memberships_path"],
        parsed_comments_path=paths["parsed_path"],
        raw_comments_path=None,
        output_target=str(output_dir),
        mode="local",
        overwrite=True,
        attributions_path=str(attr_path),
        migrations_path=str(mig_path),
    )

    table = pq.read_table(output_dir / "cluster_review_export.parquet")
    rows = table.to_pylist()
    assert rows
    for row in rows:
        assert row["candidate_entity_name"] == "Broadband for America"
        assert row["candidate_entity_type"] == "trade_association"
        assert row["attribution_confidence"] is not None
        assert row["attribution_confidence"] < 1.0
        assert row["attribution_evidence_url"] == "https://example.invalid/bfa"
        assert row["migration_match_type"] == "exact"
        assert row["migration_section"] == "Section A"
        assert row["migration_claim_scope"] == "phrase_overlap"
        assert row["migration_similarity"] == 1.0


def test_build_export_rows_handles_none_attribution_migration() -> None:
    # Ensure build_export_rows() does not crash when attributions/migrations
    # are None (default).
    clusters = pd.DataFrame(
        [
            {
                "cluster_id": "X",
                "docket_id": "17-108",
                "embedding_model": "test",
                "similarity_threshold": 0.9,
                "cluster_size": 1,
                "representative_comment_id": "rep",
                "embedding_backend": "test",
                "mean_similarity": 0.9,
                "min_similarity": 0.9,
            }
        ]
    )
    memberships = pd.DataFrame(
        [
            {
                "cluster_id": "X",
                "comment_id": "rep",
                "text_source": "x",
                "text_hash": "h",
                "similarity_to_representative": 1.0,
            }
        ]
    )
    parsed = pd.DataFrame(
        [
            {
                "comment_id": "rep",
                "raw_text": "Body.",
                "normalized_text": "body.",
                "posted_date": None,
            }
        ]
    )
    rows = build_export_rows(
        clusters=clusters,
        memberships=memberships,
        parsed_comments=parsed,
        raw_comments=None,
        topic_id="telecom",
        agency_id="FCC",
        exported_at=datetime.now(timezone.utc),
        attributions=None,
        migrations=None,
    )
    assert len(rows) == 1
    assert rows[0].candidate_entity_name is None
    assert rows[0].migration_match_type is None


def test_cluster_review_export_row_accepts_attribution_fields() -> None:
    now = datetime.now(timezone.utc)
    row = ClusterReviewExportRow(
        cluster_id="X",
        docket_id="17-108",
        embedding_model="test",
        similarity_threshold=0.9,
        cluster_size=1,
        representative_comment_id="rep",
        comment_id="rep",
        is_representative=True,
        source="semantic",
        candidate_entity_name="Broadband for America",
        candidate_entity_type="trade_association",
        attribution_confidence=0.85,
        attribution_evidence_url="https://example.invalid",
        migration_match_type="exact",
        migration_section="Section A",
        migration_similarity=1.0,
        migration_claim_scope="phrase_overlap",
        exported_at=now,
    )
    arrow = rows_to_arrow([row])
    assert "candidate_entity_name" in arrow.column_names
    schema = cluster_review_export_arrow_schema()
    assert "migration_match_type" in schema.names
