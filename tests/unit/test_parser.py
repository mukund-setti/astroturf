"""Unit tests for ParserAgent — real delta-rs writes to tmp_path."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pyarrow as pa
import pytest
from deltalake import DeltaTable

from agents.parser.agent import (
    ParserAgent,
    ParserInput,
    clean_html,
    is_substantive_comment,
)
from shared.delta_utils.bronze import merge_comments
from shared.schemas.comments import RawComment, raw_comment_arrow_schema
from shared.schemas.parsed_comments import (
    ParsedComment,
    parsed_comment_arrow_schema,
    parsed_comment_struct,
)
from shared.schemas.comment_details import (
    CommentDetail,
    comment_detail_arrow_schema,
    comment_detail_struct,
)
from shared.schemas.comment_attachments import (
    CommentAttachment,
    comment_attachment_arrow_schema,
    comment_attachment_struct,
)

# Global registry to dynamically serve API mock detail responses
TEST_COMMENT_MOCK_REGISTRY: dict[str, dict[str, Any]] = {}


@pytest.fixture(autouse=True)
def _mlflow_tmp(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Direct MLflow writes to a tmp dir so tests don't litter ./mlruns."""
    import mlflow

    mlflow_dir = tmp_path_factory.mktemp("mlruns")
    mlflow.set_tracking_uri(mlflow_dir.as_uri())
    mlflow.set_experiment("astroturf-tests-parser")


@pytest.fixture(autouse=True)
def _mock_detail_api(monkeypatch):
    """Hermetically mocks regulations.gov comment detail API fetches."""

    def mock_fetch(client, comment_id):
        if comment_id in TEST_COMMENT_MOCK_REGISTRY:
            return TEST_COMMENT_MOCK_REGISTRY[comment_id]

        # Safe default mock response
        return {
            "data": {
                "id": comment_id,
                "type": "comments",
                "attributes": {
                    "comment": "Default mock body text",
                    "title": "Default mock title",
                    "postedDate": "2023-05-21T12:00:00Z",
                    "hasAttachments": False,
                },
            }
        }

    import agents.parser.agent as agent_mod

    monkeypatch.setattr(agent_mod, "_fetch_comment_detail", mock_fetch)


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


def test_details_and_attachments_schemas_match_pydantic_field_set() -> None:
    # comment_details
    detail_pydantic = list(CommentDetail.model_fields.keys())
    detail_arrow = comment_detail_arrow_schema().names
    detail_spark = [f.name for f in comment_detail_struct().fields]

    assert detail_arrow == detail_pydantic
    assert detail_spark == detail_pydantic

    # comment_attachments
    attachment_pydantic = list(CommentAttachment.model_fields.keys())
    attachment_arrow = comment_attachment_arrow_schema().names
    attachment_spark = [f.name for f in comment_attachment_struct().fields]

    assert attachment_arrow == attachment_pydantic
    assert attachment_spark == attachment_pydantic


def test_clean_html() -> None:
    assert clean_html(None) is None
    assert clean_html("") is None
    assert clean_html("<div>Hello <b>World</b>!</div>") == "Hello World!"
    assert clean_html("<p>Paragraph</p>") == "Paragraph"
    assert clean_html("Simple text") == "Simple text"


def test_is_substantive_comment() -> None:
    # No attachments -> always substantive
    assert is_substantive_comment("Short text", has_attachments=False) is True

    # Substantive text with attachments
    assert (
        is_substantive_comment(
            "This is a longer, highly descriptive statement addressing EPA rules.",
            has_attachments=True,
            min_length=50,
        )
        is True
    )

    # Cover note with attachments
    assert (
        is_substantive_comment(
            "Please find attached my comment", has_attachments=True, min_length=100
        )
        is False
    )
    assert (
        is_substantive_comment("See attached pdf", has_attachments=True, min_length=100)
        is False
    )

    # Border cases
    assert is_substantive_comment(None, has_attachments=False) is False
    assert is_substantive_comment("  ", has_attachments=False) is False


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

    # Register mock API detail JSON
    TEST_COMMENT_MOCK_REGISTRY["C1"] = {
        "data": {
            "id": "C1",
            "type": "comments",
            "attributes": {
                "comment": "  This is the actual comment text.  \nWith extra whitespace.  ",
                "postedDate": "2023-05-21T12:00:00Z",
                "hasAttachments": False,
            },
        }
    }

    agent = ParserAgent(config={"bronze_path": bronze_path, "silver_path": silver_path})
    out = agent.run(
        ParserInput(
            docket_id="D1",
            details_path=str(tmp_path / "comment_details"),
            attachments_path=str(tmp_path / "comment_attachments"),
        )
    )

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
    assert parsed["text_source"] == "detail_comment_text"
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

    TEST_COMMENT_MOCK_REGISTRY["C2"] = {
        "data": {
            "id": "C2",
            "type": "comments",
            "attributes": {
                "comment": "",
                "title": "  The Title  ",
                "postedDate": "2023-05-21T12:00:00Z",
                "hasAttachments": False,
            },
        }
    }

    agent = ParserAgent(config={"bronze_path": bronze_path, "silver_path": silver_path})
    out = agent.run(
        ParserInput(
            docket_id="D1",
            details_path=str(tmp_path / "comment_details"),
            attachments_path=str(tmp_path / "comment_attachments"),
        )
    )

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

    TEST_COMMENT_MOCK_REGISTRY["C3"] = {
        "data": {
            "id": "C3",
            "type": "comments",
            "attributes": {
                "comment": None,
                "title": None,
                "postedDate": "2023-05-21T12:00:00Z",
                "hasAttachments": False,
            },
        }
    }

    agent = ParserAgent(config={"bronze_path": bronze_path, "silver_path": silver_path})
    out = agent.run(
        ParserInput(
            docket_id="D1",
            details_path=str(tmp_path / "comment_details"),
            attachments_path=str(tmp_path / "comment_attachments"),
        )
    )

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

    TEST_COMMENT_MOCK_REGISTRY["C1"] = {
        "data": {
            "id": "C1",
            "type": "comments",
            "attributes": {
                "comment": "Some   Text   to   Clean",
                "postedDate": "2023-05-21T12:00:00Z",
                "hasAttachments": False,
            },
        }
    }
    TEST_COMMENT_MOCK_REGISTRY["C2"] = {
        "data": {
            "id": "C2",
            "type": "comments",
            "attributes": {
                "comment": "  some text to clean  ",
                "postedDate": "2023-05-21T12:00:00Z",
                "hasAttachments": False,
            },
        }
    }

    agent = ParserAgent(config={"bronze_path": bronze_path, "silver_path": silver_path})
    agent.run(
        ParserInput(
            docket_id="D1",
            details_path=str(tmp_path / "comment_details"),
            attachments_path=str(tmp_path / "comment_attachments"),
        )
    )

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

    TEST_COMMENT_MOCK_REGISTRY["C_IDEM"] = {
        "data": {
            "id": "C_IDEM",
            "type": "comments",
            "attributes": {
                "comment": "World",
                "title": "Hello",
                "postedDate": "2023-05-21T12:00:00Z",
                "hasAttachments": False,
            },
        }
    }

    agent = ParserAgent(config={"bronze_path": bronze_path, "silver_path": silver_path})

    # Run twice
    out1 = agent.run(
        ParserInput(
            docket_id="D1",
            details_path=str(tmp_path / "comment_details"),
            attachments_path=str(tmp_path / "comment_attachments"),
        )
    )
    out2 = agent.run(
        ParserInput(
            docket_id="D1",
            details_path=str(tmp_path / "comment_details"),
            attachments_path=str(tmp_path / "comment_attachments"),
            force_enrich=True,
        )
    )

    rows = _delta_rows(silver_path)
    assert len(rows) == 1
    assert out1.rows_written == 1
    assert out2.rows_written == 1


def test_enrichment_cataloging_and_diagnostics(tmp_path):
    bronze_path = str(tmp_path / "raw_comments")
    silver_path = str(tmp_path / "parsed_comments")
    details_path = str(tmp_path / "comment_details")
    attachments_path = str(tmp_path / "comment_attachments")

    c1 = RawComment(
        comment_id="C_ENRICH_SUB",
        docket_id="D1",
        title="Docket Title",
        comment_text="List endpoint cover note",
        has_attachments=True,
        ingested_at=datetime.now(timezone.utc),
    )
    c2 = RawComment(
        comment_id="C_ENRICH_COVER",
        docket_id="D1",
        title="Docket Title 2",
        comment_text="List endpoint cover note 2",
        has_attachments=True,
        ingested_at=datetime.now(timezone.utc),
    )
    merge_comments(bronze_path, _to_raw_arrow([c1, c2]))

    # Register C_ENRICH_SUB (substantive comment with attachments)
    TEST_COMMENT_MOCK_REGISTRY["C_ENRICH_SUB"] = {
        "data": {
            "id": "C_ENRICH_SUB",
            "type": "comments",
            "attributes": {
                "comment": "<div>This is a substantive comment body of 100+ chars. The agency must pay attention to this deep analysis.</div>",
                "postedDate": "2023-05-21T12:00:00Z",
                "hasAttachments": True,
            },
        },
        "included": [
            {
                "id": "ATT_1",
                "type": "attachments",
                "attributes": {
                    "title": "Study.pdf",
                    "fileFormats": [
                        {
                            "fileUrl": "https://api.regulations.gov/v4/attachments/ATT_1/pdf",
                            "format": "pdf",
                            "size": 9999,
                        }
                    ],
                },
            }
        ],
    }

    # Register C_ENRICH_COVER (boilerplate cover note with attachments)
    TEST_COMMENT_MOCK_REGISTRY["C_ENRICH_COVER"] = {
        "data": {
            "id": "C_ENRICH_COVER",
            "type": "comments",
            "attributes": {
                "comment": "<p>See attached pdf</p>",
                "postedDate": "2023-05-21T12:00:00Z",
                "hasAttachments": True,
            },
        },
        "included": [
            {
                "id": "ATT_2",
                "type": "attachments",
                "attributes": {
                    "title": "CoverLetter.docx",
                    "fileFormats": [
                        {
                            "fileUrl": "https://api.regulations.gov/v4/attachments/ATT_2/docx",
                            "format": "docx",
                            "size": 1234,
                        }
                    ],
                },
            }
        ],
    }

    agent = ParserAgent(
        config={
            "bronze_path": bronze_path,
            "silver_path": silver_path,
            "details_path": details_path,
            "attachments_path": attachments_path,
        }
    )
    out = agent.run(
        ParserInput(
            docket_id="D1", details_path=details_path, attachments_path=attachments_path
        )
    )

    # Verify return metadata
    assert out.metadata["api_fetches_success"] == 2
    assert out.metadata["comments_enriched_substantive"] == 1
    assert out.metadata["comments_enriched_cover_note"] == 1
    assert out.metadata["attachments_detected"] == 2

    # Verify silver.parsed_comments has correct text and source
    parsed_rows = _delta_rows(silver_path)
    assert len(parsed_rows) == 2

    sub_parsed = [r for r in parsed_rows if r["comment_id"] == "C_ENRICH_SUB"][0]
    assert sub_parsed["text_source"] == "detail_comment_text"
    assert (
        sub_parsed["raw_text"]
        == "This is a substantive comment body of 100+ chars. The agency must pay attention to this deep analysis."
    )
    assert sub_parsed["attachment_count"] == 1

    cover_parsed = [r for r in parsed_rows if r["comment_id"] == "C_ENRICH_COVER"][0]
    assert cover_parsed["text_source"] == "detail_cover_note"
    assert cover_parsed["raw_text"] == "See attached pdf"
    assert cover_parsed["attachment_count"] == 1

    # Verify silver.comment_details has correct rows
    details = _delta_rows(details_path)
    assert len(details) == 2

    sub_detail = [r for r in details if r["comment_id"] == "C_ENRICH_SUB"][0]
    assert sub_detail["enrichment_status"] == "success"
    assert sub_detail["has_substantive_comment"] is True
    assert sub_detail["is_cover_note"] is False

    cover_detail = [r for r in details if r["comment_id"] == "C_ENRICH_COVER"][0]
    assert cover_detail["enrichment_status"] == "success"
    assert cover_detail["has_substantive_comment"] is False
    assert cover_detail["is_cover_note"] is True

    # Verify silver.comment_attachments has correct rows cataloged
    attachments = _delta_rows(attachments_path)
    assert len(attachments) == 2

    att1 = [r for r in attachments if r["comment_id"] == "C_ENRICH_SUB"][0]
    assert att1["attachment_id"] == "ATT_1_pdf"
    assert att1["file_name"] == "Study.pdf"
    assert att1["format"] == "pdf"
    assert att1["size_bytes"] == 9999
    assert att1["file_url"] == "https://api.regulations.gov/v4/attachments/ATT_1/pdf"


def test_enrichment_incremental_skipping(tmp_path):
    bronze_path = str(tmp_path / "raw_comments")
    silver_path = str(tmp_path / "parsed_comments")
    details_path = str(tmp_path / "comment_details")
    attachments_path = str(tmp_path / "comment_attachments")

    c1 = RawComment(
        comment_id="C_ALREADY",
        docket_id="D1",
        title="Docket Title",
        comment_text="List endpoint cover note",
        ingested_at=datetime.now(timezone.utc),
    )
    c2 = RawComment(
        comment_id="C_NEW",
        docket_id="D1",
        title="Docket Title 2",
        comment_text="List endpoint cover note 2",
        ingested_at=datetime.now(timezone.utc),
    )
    merge_comments(bronze_path, _to_raw_arrow([c1, c2]))

    # Seed the comment_details table to pretend C_ALREADY is already enriched
    pre_enriched = CommentDetail(
        comment_id="C_ALREADY",
        docket_id="D1",
        enrichment_status="success",
        extracted_at=datetime.now(timezone.utc),
        has_substantive_comment=True,
        is_cover_note=False,
    )

    # Write empty arrow/merge to initial detail delta table
    from shared.schemas.comment_details import comment_detail_arrow_schema
    from shared.delta_utils.silver import merge_comment_details

    # Form arrow table for seed
    seed_row = {name: [] for name in comment_detail_arrow_schema().names}
    d = pre_enriched.model_dump()
    for name in seed_row:
        seed_row[name].append(d[name])
    seed_arrow = pa.Table.from_pydict(seed_row, schema=comment_detail_arrow_schema())
    merge_comment_details(details_path, seed_arrow)

    # Verify seed worked
    assert len(_delta_rows(details_path)) == 1

    # Configure ParserAgent
    agent = ParserAgent(
        config={
            "bronze_path": bronze_path,
            "silver_path": silver_path,
            "details_path": details_path,
            "attachments_path": attachments_path,
        }
    )

    # Run in incremental mode
    out = agent.run(
        ParserInput(
            docket_id="D1",
            details_path=details_path,
            attachments_path=attachments_path,
            force_enrich=False,
        )
    )

    # C_ALREADY should be skipped (skipped incremented), C_NEW should be fetched
    assert out.metadata["already_enriched_count"] == 1
    assert out.metadata["api_fetches_attempted"] == 1

    # Run in force_enrich mode
    out_force = agent.run(
        ParserInput(
            docket_id="D1",
            details_path=details_path,
            attachments_path=attachments_path,
            force_enrich=True,
        )
    )

    # Both C_ALREADY and C_NEW should be fetched
    assert out_force.metadata["already_enriched_count"] == 0
    assert out_force.metadata["api_fetches_attempted"] == 2


def test_max_detail_fetches_limits(tmp_path):
    bronze_path = str(tmp_path / "raw_comments")
    silver_path = str(tmp_path / "parsed_comments")
    details_path = str(tmp_path / "comment_details")
    attachments_path = str(tmp_path / "comment_attachments")

    c1 = RawComment(
        comment_id="C_LIMIT_1",
        docket_id="D1",
        title="Docket Title 1",
        comment_text="Cover note 1",
        ingested_at=datetime.now(timezone.utc),
    )
    c2 = RawComment(
        comment_id="C_LIMIT_2",
        docket_id="D1",
        title="Docket Title 2",
        comment_text="Cover note 2",
        ingested_at=datetime.now(timezone.utc),
    )
    merge_comments(bronze_path, _to_raw_arrow([c1, c2]))

    agent = ParserAgent(
        config={
            "bronze_path": bronze_path,
            "silver_path": silver_path,
            "details_path": details_path,
            "attachments_path": attachments_path,
        }
    )

    # 1. max_detail_fetches=0 makes zero network calls.
    out0 = agent.run(
        ParserInput(
            docket_id="D1",
            details_path=details_path,
            attachments_path=attachments_path,
            max_detail_fetches=0,
            force_enrich=True,
        )
    )
    assert out0.metadata["detail_fetches_attempted"] == 0
    assert out0.metadata["detail_fetches_succeeded"] == 0

    # 2. max_detail_fetches=1 makes exactly one detail API call even if multiple rows need enrichment.
    out1 = agent.run(
        ParserInput(
            docket_id="D1",
            details_path=details_path,
            attachments_path=attachments_path,
            max_detail_fetches=1,
            force_enrich=True,
        )
    )
    assert out1.metadata["detail_fetches_attempted"] == 1
    assert out1.metadata["detail_fetches_succeeded"] == 1

    # 3. checkpointed already-enriched rows do not count against max_detail_fetches.
    from shared.schemas.comment_details import comment_detail_arrow_schema
    from shared.delta_utils.silver import merge_comment_details

    seed_row = CommentDetail(
        comment_id="C_LIMIT_1",
        docket_id="D1",
        enrichment_status="success",
        extracted_at=datetime.now(timezone.utc),
    )
    seed_row2 = CommentDetail(
        comment_id="C_LIMIT_2",
        docket_id="D1",
        enrichment_status="success",
        extracted_at=datetime.now(timezone.utc),
    )

    seed_dict = {name: [] for name in comment_detail_arrow_schema().names}
    for row in [seed_row, seed_row2]:
        d = row.model_dump()
        for name in seed_dict:
            seed_dict[name].append(d[name])
    seed_arrow = pa.Table.from_pydict(seed_dict, schema=comment_detail_arrow_schema())
    merge_comment_details(details_path, seed_arrow)

    # Now both are checkpointed. Run with max_detail_fetches=1, force_enrich=False (incremental).
    out_skip = agent.run(
        ParserInput(
            docket_id="D1",
            details_path=details_path,
            attachments_path=attachments_path,
            max_detail_fetches=1,
            force_enrich=False,
        )
    )
    assert out_skip.metadata["already_enriched_count"] == 2
    assert out_skip.metadata["detail_fetches_attempted"] == 0


def test_cli_importable():
    from scripts.run_parser import main

    assert main is not None
