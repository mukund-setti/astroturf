"""Sync tests for gold cluster schemas."""

from __future__ import annotations

from pyspark.sql import types as T

from shared.schemas.comment_clusters import (
    CommentCluster,
    CommentClusterMembership,
    comment_cluster_arrow_schema,
    comment_cluster_membership_arrow_schema,
    comment_cluster_membership_struct,
    comment_cluster_struct,
)


def test_comment_cluster_schema_sync() -> None:
    pydantic_fields = list(CommentCluster.model_fields.keys())
    arrow_fields = comment_cluster_arrow_schema().names
    spark_fields = [field.name for field in comment_cluster_struct().fields]

    assert arrow_fields == pydantic_fields
    assert spark_fields == pydantic_fields


def test_comment_cluster_membership_schema_sync() -> None:
    pydantic_fields = list(CommentClusterMembership.model_fields.keys())
    arrow_fields = comment_cluster_membership_arrow_schema().names
    spark_fields = [field.name for field in comment_cluster_membership_struct().fields]

    assert arrow_fields == pydantic_fields
    assert spark_fields == pydantic_fields


def test_cluster_provenance_fields_present() -> None:
    fields = set(CommentCluster.model_fields)
    assert "clustering_run_id" in fields
    assert "candidate_count" in fields
    assert "embedding_backend" in fields
    assert "representative_text_hash" in fields
    assert "representative_text" not in fields


def test_membership_key_fields_present() -> None:
    fields = set(CommentClusterMembership.model_fields)
    assert "cluster_id" in fields
    assert "comment_id" in fields
    assert "clustering_run_id" in fields


def test_similarity_threshold_is_double() -> None:
    cluster_struct = comment_cluster_struct()
    threshold_field = next(
        field for field in cluster_struct.fields if field.name == "similarity_threshold"
    )
    assert threshold_field.dataType == T.DoubleType()
