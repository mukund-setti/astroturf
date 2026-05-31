"""Unit tests for the Spark branch of additive schema evolution.

Exercises ``shared.delta_utils.spark_writers.spark_ensure_schema`` directly
with a faked SparkSession so the tests don't require a JVM. The real-spark
behaviour (ALTER TABLE actually mutating the Delta log) is covered by
the opt-in suite at ``tests/integration/test_spark_writers.py``.

Three core cases per ADR-0017's schema-evolution refinement:

  (a) Target missing a column the source has -> ALTER TABLE ADD COLUMNS
      fires with the correct DDL string.
  (b) Target has an extra column the source lacks -> no ALTER, no raise
      (MERGE will preserve the extra column naturally).
  (c) Type mismatch on an overlapping column -> raises ValueError without
      issuing any DDL.

Plus brand-new-path (no-op) and identical-schema (no ALTER) sanity checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa
import pytest
from pyspark.sql.types import (
    LongType,
    StringType,
    StructField,
    StructType,
)

from shared.delta_utils.spark_writers import spark_ensure_schema


@dataclass
class _FakeReader:
    """Fakes ``spark.read.format("delta").load(path)`` -> DataFrame."""

    schemas_by_path: dict[str, StructType]
    missing_paths: set[str] = field(default_factory=set)

    def format(self, fmt: str) -> "_FakeReader":
        assert fmt == "delta", fmt
        return self

    def load(self, path: str) -> "_FakeDataFrame":
        if path in self.missing_paths:
            raise FileNotFoundError(path)
        return _FakeDataFrame(self.schemas_by_path[path])


@dataclass
class _FakeDataFrame:
    schema: StructType

    def limit(self, n: int) -> "_FakeDataFrame":
        assert n == 0, n
        return self

    def collect(self) -> list[Any]:
        return []


class _FakeSparkSession:
    """Minimal SparkSession stand-in for spark_ensure_schema.

    Captures every ``spark.sql(...)`` invocation so tests can assert the
    exact ALTER TABLE DDL the gate produces (or its absence).
    """

    def __init__(
        self,
        schemas_by_path: dict[str, StructType] | None = None,
        missing_paths: set[str] | None = None,
    ) -> None:
        self.read = _FakeReader(
            schemas_by_path=schemas_by_path or {},
            missing_paths=missing_paths or set(),
        )
        self.sql_calls: list[str] = []

    def sql(self, statement: str) -> Any:
        self.sql_calls.append(statement)
        return None


@pytest.fixture
def fake_spark(monkeypatch: pytest.MonkeyPatch):
    """Install a fake SparkSession factory and return the session.

    The factory is reused across calls so any internal lookup of the
    active session inside spark_ensure_schema returns the same fake.
    """

    def _make(schemas=None, missing=None) -> _FakeSparkSession:
        session = _FakeSparkSession(
            schemas_by_path=schemas or {},
            missing_paths=missing or set(),
        )
        monkeypatch.setattr(
            "shared.delta_utils.spark_writers._get_spark",
            lambda: session,
        )
        # The probe uses the same `_FakeReader` so existence comes from
        # missing_paths; nothing else to monkeypatch.
        return session

    return _make


def _arrow_schema(*fields: tuple[str, pa.DataType]) -> pa.Schema:
    return pa.schema([pa.field(name, dtype) for name, dtype in fields])


# ---------- Case (a): missing column triggers ALTER ----------


def test_missing_column_in_target_fires_alter_table(fake_spark) -> None:
    path = "/Volumes/astroturf/demo/_lakehouse/bronze/raw_comments"
    existing = StructType([StructField("comment_id", StringType(), True)])
    spark = fake_spark(schemas={path: existing})

    expected = _arrow_schema(
        ("comment_id", pa.string()),
        ("source", pa.string()),
    )

    spark_ensure_schema(path, expected, allow_destructive=True)

    assert len(spark.sql_calls) == 1, spark.sql_calls
    ddl = spark.sql_calls[0]
    # Path is backtick-quoted; column is backtick-quoted; type is the
    # Spark simpleString form for an arrow string -> "string".
    assert ddl == (f"ALTER TABLE delta.`{path}` ADD COLUMNS (`source` string)"), ddl


def test_multiple_missing_columns_collapse_into_one_alter(fake_spark) -> None:
    path = "/Volumes/x/y/z/silver/parsed_comments"
    existing = StructType([StructField("comment_id", StringType(), True)])
    spark = fake_spark(schemas={path: existing})

    expected = _arrow_schema(
        ("comment_id", pa.string()),
        ("posted_date", pa.string()),
        ("submitter_name", pa.string()),
        ("raw_text", pa.string()),
    )

    spark_ensure_schema(path, expected, allow_destructive=True)

    assert len(spark.sql_calls) == 1
    ddl = spark.sql_calls[0]
    # The columns appear in the same order they were declared in the
    # expected arrow schema.
    assert "`posted_date` string" in ddl
    assert "`submitter_name` string" in ddl
    assert "`raw_text` string" in ddl
    # And single ALTER, not three:
    assert ddl.count("ALTER TABLE") == 1
    assert ddl.count("ADD COLUMNS") == 1


# ---------- Case (b): extra target column not in source is fine ----------


def test_extra_target_column_not_in_source_is_noop(fake_spark) -> None:
    """Source missing a column the target has must not raise or ALTER.

    Rationale: a producer can legitimately stop emitting a column without
    that being a destructive change at the table level — MERGE's
    whenMatchedUpdateAll() only touches columns the source provides, so
    the target's extra column is preserved as-is.
    """
    path = "/Volumes/x/y/z/silver/parsed_comments"
    existing = StructType(
        [
            StructField("comment_id", StringType(), True),
            StructField("legacy_only", StringType(), True),
        ]
    )
    spark = fake_spark(schemas={path: existing})

    expected = _arrow_schema(("comment_id", pa.string()))

    spark_ensure_schema(path, expected, allow_destructive=True)
    assert spark.sql_calls == []


# ---------- Case (c): type mismatch raises ----------


def test_type_mismatch_on_existing_column_raises(fake_spark) -> None:
    path = "/Volumes/x/y/z/silver/comment_embeddings"
    # On-disk: comment_id is long (e.g. some early ingest accidentally
    # wrote integer ids). Expected says it's a string.
    existing = StructType(
        [
            StructField("comment_id", LongType(), True),
        ]
    )
    spark = fake_spark(schemas={path: existing})

    expected = _arrow_schema(("comment_id", pa.string()))

    with pytest.raises(ValueError, match="non-additive type change"):
        spark_ensure_schema(path, expected, allow_destructive=True)
    assert spark.sql_calls == []  # no DDL issued on rejection


# ---------- Brand-new-path no-op ----------


def test_brand_new_path_is_noop(fake_spark) -> None:
    path = "/Volumes/x/y/z/bronze/raw_comments"
    spark = fake_spark(missing={path})
    expected = _arrow_schema(("comment_id", pa.string()))

    spark_ensure_schema(path, expected, allow_destructive=True)
    # No table on disk yet -> no schema read, no ALTER. The first
    # spark_merge will write with the source schema via mode("overwrite").
    assert spark.sql_calls == []


# ---------- Identical schema no-op ----------


def test_identical_schema_does_not_alter(fake_spark) -> None:
    path = "/Volumes/x/y/z/silver/comment_details"
    existing = StructType(
        [
            StructField("comment_id", StringType(), True),
            StructField("posted_date", StringType(), True),
        ]
    )
    spark = fake_spark(schemas={path: existing})

    expected = _arrow_schema(
        ("comment_id", pa.string()),
        ("posted_date", pa.string()),
    )
    spark_ensure_schema(path, expected, allow_destructive=True)
    assert spark.sql_calls == []
