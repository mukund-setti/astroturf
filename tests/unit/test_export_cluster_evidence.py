"""Unit tests for the cluster evidence export helpers."""

from __future__ import annotations

import pandas as pd

from scripts.export_cluster_evidence import (
    attach_parsed_fields,
    build_report,
    classify_cluster,
    cluster_duplicate_stats,
    select_clusters,
    text_preview,
)


def test_select_clusters_orders_by_size_then_id() -> None:
    clusters = pd.DataFrame(
        [
            {"cluster_id": "b", "cluster_size": 3},
            {"cluster_id": "a", "cluster_size": 3},
            {"cluster_id": "c", "cluster_size": 2},
        ]
    )

    selected = select_clusters(clusters, cluster_id=None, top_n_clusters=2)

    assert selected["cluster_id"].tolist() == ["a", "b"]


def test_select_clusters_prefers_explicit_cluster_id() -> None:
    clusters = pd.DataFrame(
        [
            {"cluster_id": "large", "cluster_size": 10},
            {"cluster_id": "small", "cluster_size": 2},
        ]
    )

    selected = select_clusters(clusters, cluster_id="small", top_n_clusters=1)

    assert selected["cluster_id"].tolist() == ["small"]


def test_cluster_duplicate_stats_counts_only_duplicate_members() -> None:
    members = pd.DataFrame(
        {
            "normalized_text_hash": [
                "hash-a",
                "hash-a",
                "hash-b",
                "hash-c",
                "hash-c",
                "hash-c",
                None,
                "",
            ]
        }
    )

    stats = cluster_duplicate_stats(members)

    assert stats == {
        "unique_hash_count": 3,
        "exact_duplicate_groups": 2,
        "exact_duplicate_members": 5,
        "largest_exact_duplicate_group": 3,
    }


def test_classify_cluster() -> None:
    assert (
        classify_cluster(
            cluster_size=10,
            unique_hash_count=9,
            largest_exact_duplicate_group=1,
        )
        == "embedding/paraphrase-driven"
    )
    assert (
        classify_cluster(
            cluster_size=10,
            unique_hash_count=2,
            largest_exact_duplicate_group=7,
        )
        == "exact-duplicate-driven"
    )
    assert (
        classify_cluster(
            cluster_size=10,
            unique_hash_count=5,
            largest_exact_duplicate_group=4,
        )
        == "mixed"
    )


def test_text_preview_collapses_whitespace_and_truncates() -> None:
    assert text_preview(" alpha\n\n beta\tgamma ", limit=20) == "alpha beta gamma"
    assert text_preview("x" * 25, limit=10) == "xxxxxxx..."


def test_attach_parsed_fields_adds_preview_and_hash() -> None:
    members = pd.DataFrame(
        [
            {
                "cluster_id": "cluster-1",
                "comment_id": "comment-1",
                "text_hash": "member-hash",
            }
        ]
    )
    parsed = pd.DataFrame(
        [
            {
                "comment_id": "comment-1",
                "title": "A title",
                "raw_text": "Raw text",
                "normalized_text": "normalized text",
                "normalized_text_hash": "parsed-hash",
            }
        ]
    )

    joined = attach_parsed_fields(members, parsed)

    assert joined.loc[0, "title"] == "A title"
    assert joined.loc[0, "normalized_text_hash"] == "parsed-hash"
    assert joined.loc[0, "text_preview"] == "Raw text"


def test_build_report_contains_cluster_evidence() -> None:
    clusters = pd.DataFrame(
        [
            {
                "cluster_id": "cluster-1",
                "cluster_size": 2,
                "representative_comment_id": "comment-1",
                "mean_similarity": 0.95,
                "min_similarity": 0.92,
                "max_similarity": 1.0,
            }
        ]
    )
    memberships = pd.DataFrame(
        [
            {
                "cluster_id": "cluster-1",
                "comment_id": "comment-1",
                "membership_rank": 1,
                "similarity_to_representative": 1.0,
                "text_hash": "hash-1",
            },
            {
                "cluster_id": "cluster-1",
                "comment_id": "comment-2",
                "membership_rank": 2,
                "similarity_to_representative": 0.93,
                "text_hash": "hash-2",
            },
        ]
    )
    parsed = pd.DataFrame(
        [
            {
                "comment_id": "comment-1",
                "title": "Rep",
                "raw_text": "Representative text",
                "normalized_text": "representative text",
                "normalized_text_hash": "hash-1",
            },
            {
                "comment_id": "comment-2",
                "title": "Other",
                "raw_text": "Other text",
                "normalized_text": "other text",
                "normalized_text_hash": "hash-2",
            },
        ]
    )

    report = build_report(
        docket_id="D1",
        embedding_model="model",
        threshold=0.92,
        clusters=clusters,
        memberships=memberships,
        parsed_comments=parsed,
        selected_clusters=clusters,
    )

    assert "# Cluster Evidence Export: D1" in report
    assert "- Total clusters: `1`" in report
    assert "- Classification: `embedding/paraphrase-driven`" in report
    assert "> Representative text" in report
    assert "| comment-2 | 0.930000 | Other | Other text |" in report
