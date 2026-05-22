"""Sync test: arrow and Spark schemas stay aligned with the Pydantic source of truth."""

from __future__ import annotations

import pyarrow as pa
from pyspark.sql import types as T

from shared.schemas.comment_embeddings import (
    CommentEmbedding,
    comment_embedding_arrow_schema,
    comment_embedding_struct,
)


def test_embeddings_schema_sync() -> None:
    pydantic_fields = list(CommentEmbedding.model_fields.keys())
    arrow_fields = comment_embedding_arrow_schema().names
    spark_fields = [f.name for f in comment_embedding_struct().fields]

    assert arrow_fields == pydantic_fields, (
        "arrow schema drifted from CommentEmbedding.model_fields; update _FIELD_TYPES "
        "in shared/schemas/comment_embeddings.py"
    )
    assert spark_fields == pydantic_fields, (
        "PySpark StructType drifted from CommentEmbedding.model_fields; update _FIELD_TYPES "
        "in shared/schemas/comment_embeddings.py"
    )


def test_embedding_vector_is_variable_size_list() -> None:
    """ADR-0005: the embedding_vector column must be variable-size to support multi-dim models."""
    arrow_schema = comment_embedding_arrow_schema()
    vector_field = arrow_schema.field("embedding_vector")
    assert vector_field.type == pa.list_(pa.float32()), (
        "embedding_vector must be variable-size pa.list_(pa.float32()) per ADR-0005"
    )

    struct = comment_embedding_struct()
    spark_vector_field = next(f for f in struct.fields if f.name == "embedding_vector")
    assert spark_vector_field.dataType == T.ArrayType(T.FloatType()), (
        "embedding_vector Spark type must be ArrayType(FloatType) per ADR-0005"
    )


def test_compound_pk_fields_present() -> None:
    """ADR-0005: compound PK is (comment_id, embedding_model) — both must be present."""
    fields = list(CommentEmbedding.model_fields.keys())
    assert "comment_id" in fields
    assert "embedding_model" in fields
