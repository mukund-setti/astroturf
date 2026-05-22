"""Sync check: arrow and Spark schemas stay aligned with the Pydantic source of truth."""

from __future__ import annotations

from shared.schemas.comments import (
    RawComment,
    raw_comment_arrow_schema,
    raw_comment_struct,
)


def test_arrow_and_struct_schemas_match_pydantic_field_set() -> None:
    pydantic_fields = list(RawComment.model_fields.keys())
    arrow_fields = raw_comment_arrow_schema().names
    spark_fields = [f.name for f in raw_comment_struct().fields]

    assert arrow_fields == pydantic_fields, (
        "arrow schema drifted from RawComment.model_fields; update _FIELD_TYPES "
        "in shared/schemas/comments.py"
    )
    assert spark_fields == pydantic_fields, (
        "PySpark StructType drifted from RawComment.model_fields; update _FIELD_TYPES "
        "in shared/schemas/comments.py"
    )
