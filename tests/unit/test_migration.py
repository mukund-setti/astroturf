"""Unit tests for MigrationAgent (local_text mode).

Covers:
- exact phrase overlap path
- near-exact (fuzzy) phrase overlap path
- mandatory caveat_text on every row
- claim_scope never escalates past possible_influence
- end-to-end run via Delta tables writes gold.rule_migrations
- caveat_text validator rejects empty strings
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from deltalake import DeltaTable
from pydantic import ValidationError

from agents.migration.agent import (
    CAVEAT_DEFAULT,
    POSSIBLE_INFLUENCE_MIN_WORDS,
    MigrationAgent,
    MigrationInput,
    _migrations_for_cluster,
    _split_sections,
)
from shared.delta_utils.gold import merge_comment_clusters
from shared.delta_utils.silver import merge_parsed_comments
from shared.schemas.comment_clusters import (
    CommentCluster,
    comment_cluster_arrow_schema,
)
from shared.schemas.parsed_comments import (
    ParsedComment,
    parsed_comment_arrow_schema,
)
from shared.schemas.rule_migrations import RuleMigration


@pytest.fixture(autouse=True)
def _mlflow_tmp(tmp_path_factory: pytest.TempPathFactory) -> None:
    import mlflow

    mlflow_dir = tmp_path_factory.mktemp("mlruns")
    mlflow.set_tracking_uri(mlflow_dir.as_uri())
    mlflow.set_experiment("astroturf-tests-migration")


def _make_cluster_arrow(
    *,
    cluster_id: str,
    docket_id: str,
    representative_comment_id: str,
    cluster_size: int = 5,
) -> pa.Table:
    now = datetime.now(timezone.utc)
    row = CommentCluster(
        cluster_id=cluster_id,
        clustering_run_id=f"run-{cluster_id}",
        docket_id=docket_id,
        embedding_model="test-model",
        embedding_backend="test-backend",
        clustering_version="v1",
        similarity_threshold=0.92,
        candidate_count=cluster_size,
        cluster_size=cluster_size,
        representative_comment_id=representative_comment_id,
        representative_text_hash="hash",
        mean_similarity=0.95,
        min_similarity=0.93,
        max_similarity=1.0,
        created_at=now,
        updated_at=now,
    )
    schema = comment_cluster_arrow_schema()
    columns: dict[str, list[Any]] = {n: [] for n in schema.names}
    d = row.model_dump()
    for n in columns:
        columns[n].append(d[n])
    return pa.Table.from_pydict(columns, schema=schema)


def _make_parsed_arrow(
    *,
    comment_id: str,
    docket_id: str,
    raw_text: str,
) -> pa.Table:
    now = datetime.now(timezone.utc)
    row = ParsedComment(
        comment_id=comment_id,
        docket_id=docket_id,
        source_system_version="test",
        parser_version="v1",
        text_source="detail_comment_text",
        raw_text=raw_text,
        normalized_text=raw_text.lower(),
        normalized_text_hash="rt_hash",
        token_estimate=len(raw_text.split()),
        char_count=len(raw_text),
        parse_status="ok",
        parsed_at=now,
    )
    schema = parsed_comment_arrow_schema()
    columns: dict[str, list[Any]] = {n: [] for n in schema.names}
    d = row.model_dump()
    for n in columns:
        columns[n].append(d[n])
    return pa.Table.from_pydict(columns, schema=schema)


def test_split_sections_finds_headers() -> None:
    text = "# comment line\n## Section A\nBody of A.\n\n## Section B\nBody of B.\n"
    sections = _split_sections(text)
    assert [name for name, _ in sections] == ["Section A", "Section B"]
    assert "Body of A." in sections[0][1]
    assert "Body of B." in sections[1][1]


def test_exact_phrase_match_emits_phrase_overlap() -> None:
    # When a cluster sentence appears verbatim inside the rule section body,
    # the agent must classify the row as an exact match.
    section_body = (
        "The Commission concluded that smothering innovation across the "
        "broadband marketplace is contrary to the public interest. We "
        "further note that the prior framework imposed administrative costs."
    )
    sections = [("Section A", section_body)]
    cluster_text = (
        "smothering innovation across the broadband marketplace is contrary "
        "to the public interest."
    )
    rows = _migrations_for_cluster(
        cluster_id="C1",
        docket_id="17-108",
        cluster_text=cluster_text,
        sections=sections,
        final_rule_document_id="doc1",
        final_rule_url=None,
        similarity_threshold=0.75,
        phrase_min_words=4,
        phrase_max_words=30,
        max_rows_per_cluster=5,
    )
    assert rows, "Expected at least one migration row."
    assert any(r.match_type == "exact" for r in rows)
    for row in rows:
        assert row.caveat_text  # mandatory
        assert row.confidence_score < 1.0
        assert row.claim_scope in {"phrase_overlap", "possible_influence"}


def test_near_exact_phrase_match_path() -> None:
    # Cluster phrase is a slight variation of the rule phrase — should land in
    # near_exact (ratio >= 0.90) or semantic (>= 0.75), never exact.
    sections = [
        (
            "Section A",
            "Commenters argue the prior framework was damaging the American economy and obstructing job creation.",
        ),
    ]
    rows = _migrations_for_cluster(
        cluster_id="C1b",
        docket_id="17-108",
        cluster_text=(
            "The prior framework is damaging the American economy and "
            "obstructing job growth."
        ),
        sections=sections,
        final_rule_document_id="doc1",
        final_rule_url=None,
        similarity_threshold=0.75,
        phrase_min_words=4,
        phrase_max_words=30,
        max_rows_per_cluster=5,
    )
    assert rows
    for row in rows:
        assert row.match_type in {"near_exact", "semantic"}
        assert row.caveat_text
        assert row.confidence_score < 1.0
        assert row.claim_scope == "phrase_overlap"


def test_possible_influence_requires_long_exact_phrase() -> None:
    # Long exact phrase >= POSSIBLE_INFLUENCE_MIN_WORDS triggers
    # possible_influence claim_scope.
    long_phrase = " ".join(["alpha"] * (POSSIBLE_INFLUENCE_MIN_WORDS + 4))
    sections = [("Section A", f"Preamble sentence. {long_phrase}. Trailing sentence.")]
    cluster_text = f"Opening. {long_phrase}. Closing."
    rows = _migrations_for_cluster(
        cluster_id="C2",
        docket_id="17-108",
        cluster_text=cluster_text,
        sections=sections,
        final_rule_document_id="doc1",
        final_rule_url=None,
        similarity_threshold=0.75,
        phrase_min_words=4,
        phrase_max_words=POSSIBLE_INFLUENCE_MIN_WORDS + 10,
        max_rows_per_cluster=5,
    )
    assert any(r.claim_scope == "possible_influence" for r in rows)
    for row in rows:
        assert row.caveat_text  # mandatory


def test_short_exact_match_stays_phrase_overlap() -> None:
    sections = [("Section A", "smothering innovation across broadband markets.")]
    cluster_text = "smothering innovation across broadband markets."
    rows = _migrations_for_cluster(
        cluster_id="C3",
        docket_id="17-108",
        cluster_text=cluster_text,
        sections=sections,
        final_rule_document_id="doc1",
        final_rule_url=None,
        similarity_threshold=0.75,
        phrase_min_words=4,
        phrase_max_words=30,
        max_rows_per_cluster=5,
    )
    assert rows
    for row in rows:
        assert row.claim_scope == "phrase_overlap"
        assert row.caveat_text == CAVEAT_DEFAULT


def test_caveat_validator_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        RuleMigration(
            migration_id="m1",
            cluster_id="c1",
            docket_id="d1",
            final_rule_document_id="doc1",
            cluster_phrase="x",
            rule_phrase="y",
            similarity_score=0.9,
            match_type="exact",
            confidence_score=0.8,
            confidence_label="high",
            claim_scope="phrase_overlap",
            caveat_text="",  # <-- forbidden
            created_at=datetime.now(timezone.utc),
        )


def test_end_to_end_writes_migrations(tmp_path: Path) -> None:
    clusters_path = tmp_path / "gold" / "comment_clusters"
    parsed_path = tmp_path / "silver" / "parsed_comments"
    out_path = tmp_path / "gold" / "rule_migrations"
    fixture_path = tmp_path / "final_rule.txt"

    fixture_text = (
        "# test fixture, not official full rule text\n"
        "## Section A\n"
        "The Commission concluded that smothering innovation across the "
        "broadband marketplace is contrary to the public interest.\n"
        "## Section B\n"
        "Commenters have asserted that the prior approach risked damaging "
        "the American economy and obstructing job creation.\n"
    )
    fixture_path.write_text(fixture_text, encoding="utf-8")

    # One cluster sentence is a verbatim substring of Section A, so the
    # exact-match path fires and at least one row is emitted.
    cluster_text = (
        "We strongly oppose the rule. smothering innovation across the "
        "broadband marketplace is contrary to the public interest."
    )

    merge_comment_clusters(
        clusters_path,
        _make_cluster_arrow(
            cluster_id="CLUSTER-A",
            docket_id="17-108",
            representative_comment_id="COMMENT-1",
        ),
    )
    merge_parsed_comments(
        parsed_path,
        _make_parsed_arrow(
            comment_id="COMMENT-1",
            docket_id="17-108",
            raw_text=cluster_text,
        ),
    )

    output = MigrationAgent().run(
        MigrationInput(
            docket_id="17-108",
            final_rule_text_path=str(fixture_path),
            final_rule_url="https://example.invalid/rule",
            clusters_path=str(clusters_path),
            parsed_comments_path=str(parsed_path),
            migrations_path=str(out_path),
            similarity_threshold=0.75,
            phrase_min_words=4,
        )
    )

    assert output.rows_written >= 1
    rows = DeltaTable(str(out_path)).to_pyarrow_table().to_pylist()
    assert rows
    for row in rows:
        assert row["cluster_id"] == "CLUSTER-A"
        assert row["docket_id"] == "17-108"
        assert row["caveat_text"]  # mandatory, never empty
        assert row["confidence_score"] < 1.0
        assert row["claim_scope"] in {"phrase_overlap", "possible_influence"}
        assert row["match_type"] in {"exact", "near_exact", "semantic"}


def test_run_in_unsupported_mode_raises(tmp_path: Path) -> None:
    inputs = MigrationInput(
        docket_id="17-108",
        mode="federal_register_api",
        final_rule_text="placeholder",
    )
    with pytest.raises(NotImplementedError):
        MigrationAgent().run(inputs)


def test_missing_final_rule_text_raises() -> None:
    with pytest.raises(ValueError, match="final_rule_text"):
        MigrationAgent().run(MigrationInput(docket_id="17-108"))
