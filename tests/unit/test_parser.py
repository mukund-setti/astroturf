"""Unit tests for ParserAgent — real delta-rs writes to tmp_path."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pyarrow as pa
import pytest
from deltalake import DeltaTable

from agents.parser.agent import ParserAgent, ParserInput
from shared.delta_utils.bronze import merge_comments
from shared.schemas.comments import RawComment, raw_comment_arrow_schema
from shared.schemas.parsed_comments import (
    ParsedComment,
    parsed_comment_arrow_schema,
    parsed_comment_struct,
)


@pytest.fixture(autouse=True)
def _mlflow_tmp(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Direct MLflow writes to a tmp dir so tests don't litter ./mlruns."""
    import mlflow

    mlflow_dir = tmp_path_factory.mktemp("mlruns")
    mlflow.set_tracking_uri(mlflow_dir.as_uri())
    mlflow.set_experiment("astroturf-tests-parser")


def _to_raw_arrow(rows: list[RawComment]) -> pa.Table:
    schema = raw_comment_arrow_schema()
    columns = {name: [] for name in schema.names}
    for row in rows:
        d = row.model_dump()
        for name in columns:
            columns[name].append(d[name])
    return pa.Table.from_pydict(columns, schema=schema)


def _delta_rows(path: str) -> list[dict[str, Any]]:
    return DeltaTable(path).to_pyarrow_table().to_pylist()


def test_silver_schemas_match_pydantic_field_set() -> None:
    pydantic_fields = list(ParsedComment.model_fields.keys())
    arrow_fields = parsed_comment_arrow_schema().names
    spark_fields = [f.name for f in parsed_comment_struct().fields]

    assert arrow_fields == pydantic_fields, (
        "arrow schema drifted from ParsedComment.model_fields; update _FIELD_TYPES "
        "in shared/schemas/parsed_comments.py"
    )
    assert spark_fields == pydantic_fields, (
        "PySpark StructType drifted from ParsedComment.model_fields; update _FIELD_TYPES "
        "in shared/schemas/parsed_comments.py"
    )


def test_parser_chooses_body_when_present(tmp_path):
    bronze_path = str(tmp_path / "raw_comments")
    silver_path = str(tmp_path / "parsed_comments")

    raw_comment = RawComment(
        comment_id="C1",
        docket_id="D1",
        title="My Title",
        comment_text="  This is the actual comment text.  \nWith extra whitespace.  ",
        ingested_at=datetime.now(timezone.utc),
    )
    merge_comments(bronze_path, _to_raw_arrow([raw_comment]))

    agent = ParserAgent(config={"bronze_path": bronze_path, "silver_path": silver_path})
    out = agent.run(ParserInput(docket_id="D1"))

    assert out.rows_written == 1
    assert out.metadata["parsed_count"] == 1
    assert out.metadata["title_only_count"] == 0

    parsed = _delta_rows(silver_path)[0]
    assert parsed["comment_id"] == "C1"
    assert (
        parsed["raw_text"]
        == "  This is the actual comment text.  \nWith extra whitespace.  "
    )
    assert (
        parsed["normalized_text"]
        == "this is the actual comment text. with extra whitespace."
    )
    assert parsed["text_source"] == "comment_text"
    assert parsed["parse_status"] == "parsed"
    assert parsed["token_estimate"] > 0
    assert parsed["char_count"] == len(parsed["raw_text"])


def test_parser_falls_back_to_title_when_body_missing(tmp_path):
    bronze_path = str(tmp_path / "raw_comments")
    silver_path = str(tmp_path / "parsed_comments")

    raw_comment = RawComment(
        comment_id="C2",
        docket_id="D1",
        title="  The Title  ",
        comment_text="",  # empty
        ingested_at=datetime.now(timezone.utc),
    )
    merge_comments(bronze_path, _to_raw_arrow([raw_comment]))

    agent = ParserAgent(config={"bronze_path": bronze_path, "silver_path": silver_path})
    out = agent.run(ParserInput(docket_id="D1"))

    assert out.rows_written == 1
    assert out.metadata["parsed_count"] == 0
    assert out.metadata["title_only_count"] == 1

    parsed = _delta_rows(silver_path)[0]
    assert parsed["comment_id"] == "C2"
    assert parsed["raw_text"] == "  The Title  "
    assert parsed["normalized_text"] == "the title"
    assert parsed["text_source"] == "title_only"
    assert parsed["parse_status"] == "title_only"


def test_parser_marks_missing_text_when_both_missing(tmp_path):
    bronze_path = str(tmp_path / "raw_comments")
    silver_path = str(tmp_path / "parsed_comments")

    raw_comment = RawComment(
        comment_id="C3",
        docket_id="D1",
        title=None,
        comment_text=None,
        ingested_at=datetime.now(timezone.utc),
    )
    merge_comments(bronze_path, _to_raw_arrow([raw_comment]))

    agent = ParserAgent(config={"bronze_path": bronze_path, "silver_path": silver_path})
    out = agent.run(ParserInput(docket_id="D1"))

    assert out.rows_written == 1
    assert out.metadata["missing_text_count"] == 1

    parsed = _delta_rows(silver_path)[0]
    assert parsed["comment_id"] == "C3"
    assert parsed["raw_text"] is None
    assert parsed["normalized_text"] is None
    assert parsed["normalized_text_hash"] is None
    assert parsed["text_source"] == "missing"
    assert parsed["parse_status"] == "missing_text"
    assert parsed["token_estimate"] == 0
    assert parsed["char_count"] == 0


def test_normalization_and_hash_are_stable(tmp_path):
    bronze_path = str(tmp_path / "raw_comments")
    silver_path = str(tmp_path / "parsed_comments")

    c1 = RawComment(
        comment_id="C1",
        docket_id="D1",
        title=None,
        comment_text="Some   Text   to   Clean",
        ingested_at=datetime.now(timezone.utc),
    )
    c2 = RawComment(
        comment_id="C2",
        docket_id="D1",
        title=None,
        comment_text="  some text to clean  ",
        ingested_at=datetime.now(timezone.utc),
    )
    merge_comments(bronze_path, _to_raw_arrow([c1, c2]))

    agent = ParserAgent(config={"bronze_path": bronze_path, "silver_path": silver_path})
    agent.run(ParserInput(docket_id="D1"))

    parsed = _delta_rows(silver_path)
    p1 = [p for p in parsed if p["comment_id"] == "C1"][0]
    p2 = [p for p in parsed if p["comment_id"] == "C2"][0]

    assert p1["normalized_text"] == "some text to clean"
    assert p2["normalized_text"] == "some text to clean"
    assert p1["normalized_text_hash"] == p2["normalized_text_hash"]
    assert p1["normalized_text_hash"] is not None


def test_silver_merge_is_idempotent(tmp_path):
    bronze_path = str(tmp_path / "raw_comments")
    silver_path = str(tmp_path / "parsed_comments")

    c = RawComment(
        comment_id="C_IDEM",
        docket_id="D1",
        title="Hello",
        comment_text="World",
        ingested_at=datetime.now(timezone.utc),
    )
    merge_comments(bronze_path, _to_raw_arrow([c]))

    agent = ParserAgent(config={"bronze_path": bronze_path, "silver_path": silver_path})

    # Run twice
    out1 = agent.run(ParserInput(docket_id="D1"))
    out2 = agent.run(ParserInput(docket_id="D1"))

    rows = _delta_rows(silver_path)
    assert len(rows) == 1
    assert out1.rows_written == 1
    assert out2.rows_written == 1  # merge handles updates, it updates in-place


def test_cli_importable():
    from scripts.run_parser import main

    assert main is not None
