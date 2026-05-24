"""Unit tests for AttributionAgent (offline_seed mode).

Covers:
- seed exact phrase match
- seed fuzzy phrase match
- registry-only match has needs_review label
- confidence_score is always strictly below 1.0
- end-to-end run via Delta tables produces a non-empty gold.campaign_attributions
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from deltalake import DeltaTable

from agents.attribution.agent import (
    AttributionAgent,
    AttributionInput,
    _attributions_for_cluster,
    _confidence_label_for,
    _load_seed_registry,
)
from shared.delta_utils.silver import (
    merge_comment_embeddings,  # noqa: F401  (kept for parity, not used)
    merge_parsed_comments,
)
from shared.schemas.parsed_comments import (
    ParsedComment,
    parsed_comment_arrow_schema,
)
from shared.schemas.comment_clusters import (
    CommentCluster,
    comment_cluster_arrow_schema,
)
from shared.delta_utils.gold import merge_comment_clusters


@pytest.fixture(autouse=True)
def _mlflow_tmp(tmp_path_factory: pytest.TempPathFactory) -> None:
    import mlflow

    mlflow_dir = tmp_path_factory.mktemp("mlruns")
    mlflow.set_tracking_uri(mlflow_dir.as_uri())
    mlflow.set_experiment("astroturf-tests-attribution")


def _seed_file(tmp_path: Path, phrases: list[str]) -> Path:
    path = tmp_path / "seed.json"
    payload = {
        "docket_id": "17-108",
        "sources": [
            {
                "entity_name": "Broadband for America",
                "entity_type": "trade_association",
                "url": "https://example.invalid/bfa",
                "template_phrases": phrases,
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _seed_two_entities(tmp_path: Path) -> Path:
    path = tmp_path / "seed.json"
    payload = {
        "sources": [
            {
                "entity_name": "Has Phrases",
                "entity_type": "advocacy_group",
                "template_phrases": ["completely different phrase that won't match"],
            },
            {
                "entity_name": "Phraseless",
                "entity_type": "company",
                "template_phrases": [],
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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


def test_exact_phrase_match_is_high_confidence(tmp_path: Path) -> None:
    seed = _load_seed_registry(
        AttributionInput(
            docket_id="17-108",
            seed_path=str(
                _seed_file(
                    tmp_path,
                    [
                        "smothering innovation, damaging the American economy",
                    ],
                )
            ),
        )
    )
    text = (
        "I am writing to oppose the rule. The unprecedented regulatory power "
        "is smothering innovation, damaging the American economy and "
        "obstructing job creation."
    )
    rows = _attributions_for_cluster(
        cluster_id="C1",
        docket_id="17-108",
        text=text,
        seed=seed,
        confidence_threshold=0.0,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.evidence_type == "exact_phrase_match"
    assert row.confidence_label == "high"
    # No certainty.
    assert row.confidence_score < 1.0
    assert row.confidence_score >= 0.80
    assert row.matched_phrase is not None
    assert row.evidence_excerpt is not None
    assert row.candidate_entity_name == "Broadband for America"
    assert row.reviewed_status == "unreviewed"


def test_fuzzy_phrase_match_is_medium_confidence(tmp_path: Path) -> None:
    seed = _load_seed_registry(
        AttributionInput(
            docket_id="17-108",
            seed_path=str(
                _seed_file(
                    tmp_path,
                    [
                        "smothering innovation, damaging the American economy",
                    ],
                )
            ),
        )
    )
    # Mostly the phrase but with a small mutation; SequenceMatcher ratio
    # against the whole text is artificially low — feed a short text that
    # is mostly the phrase plus a tweak.
    text = "smothering innovations, damaging the American economy"
    rows = _attributions_for_cluster(
        cluster_id="C2",
        docket_id="17-108",
        text=text,
        seed=seed,
        confidence_threshold=0.0,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.evidence_type == "fuzzy_phrase_match"
    assert row.confidence_label == "medium"
    assert 0.60 <= row.confidence_score < 0.80


def test_registry_only_is_needs_review(tmp_path: Path) -> None:
    seed = _load_seed_registry(
        AttributionInput(
            docket_id="17-108",
            seed_path=str(_seed_two_entities(tmp_path)),
        )
    )
    text = "Comment text completely unrelated to any template phrase."
    rows = _attributions_for_cluster(
        cluster_id="C3",
        docket_id="17-108",
        text=text,
        seed=seed,
        confidence_threshold=0.0,
    )
    # "Phraseless" has no template phrases — never matched.
    # "Has Phrases" emits a registry-only row.
    assert len(rows) == 1
    row = rows[0]
    assert row.evidence_type == "known_campaign_registry"
    assert row.confidence_label == "needs_review"
    assert row.confidence_score < 0.5


def test_confidence_label_mapping_thresholds() -> None:
    assert _confidence_label_for(0.0) == "needs_review"
    assert _confidence_label_for(0.49) == "needs_review"
    assert _confidence_label_for(0.50) == "low"
    assert _confidence_label_for(0.60) == "medium"
    assert _confidence_label_for(0.85) == "high"


def test_confidence_threshold_filters_low_scores(tmp_path: Path) -> None:
    seed = _load_seed_registry(
        AttributionInput(
            docket_id="17-108",
            seed_path=str(_seed_two_entities(tmp_path)),
        )
    )
    text = "Unrelated text."
    rows = _attributions_for_cluster(
        cluster_id="C4",
        docket_id="17-108",
        text=text,
        seed=seed,
        confidence_threshold=0.5,
    )
    assert rows == []


def test_end_to_end_writes_attributions(tmp_path: Path) -> None:
    clusters_path = tmp_path / "gold" / "comment_clusters"
    parsed_path = tmp_path / "silver" / "parsed_comments"
    out_path = tmp_path / "gold" / "campaign_attributions"

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
            raw_text=(
                "The unprecedented regulatory power the Obama Administration "
                "imposed on the internet is smothering innovation, damaging "
                "the American economy and obstructing job creation."
            ),
        ),
    )
    seed_path = _seed_file(
        tmp_path,
        [
            "The unprecedented regulatory power the Obama Administration "
            "imposed on the internet is smothering innovation, damaging the "
            "American economy and obstructing job creation.",
            "smothering innovation, damaging the American economy",
        ],
    )

    output = AttributionAgent().run(
        AttributionInput(
            docket_id="17-108",
            seed_path=str(seed_path),
            clusters_path=str(clusters_path),
            parsed_comments_path=str(parsed_path),
            attributions_path=str(out_path),
        )
    )

    assert output.rows_written >= 1
    assert DeltaTable.is_deltatable(str(out_path))
    rows = DeltaTable(str(out_path)).to_pyarrow_table().to_pylist()
    assert len(rows) >= 1
    row = rows[0]
    assert row["cluster_id"] == "CLUSTER-A"
    assert row["candidate_entity_name"] == "Broadband for America"
    assert row["confidence_score"] < 1.0
    assert row["evidence_type"] == "exact_phrase_match"
    # Multi-phrase bonus is applied when two exact phrases match.
    assert row["confidence_score"] >= 0.85


def test_run_in_unsupported_mode_raises(tmp_path: Path) -> None:
    inputs = AttributionInput(
        docket_id="17-108",
        mode="web_research",
        seed_path=str(_seed_two_entities(tmp_path)),
    )
    with pytest.raises(NotImplementedError):
        AttributionAgent().run(inputs)
