r"""Opt-in Spark integration tests for the H1 dispatcher.

These tests spin up a local Spark session with delta-spark configured and
exercise ``spark_writers.spark_merge`` / ``spark_delete`` against
filesystem paths. They cover the "first write to brand-new path" gotcha
on the Spark backend that the production-blocker plan called out as the
most likely "works locally, breaks on Databricks" failure mode.

They are gated behind ``ASTROTURF_RUN_SPARK_TESTS=1`` because spinning up
a local Spark session takes ~10-20s and requires Java, which is fine for
explicit pre-merge / pre-deploy validation but too heavy for every unit
test run. Run them with::

    $env:ASTROTURF_RUN_SPARK_TESTS = "1"
    .uv-test-venv\Scripts\python.exe -m pytest tests/integration -q

**Windows note.** PySpark on Windows requires ``HADOOP_HOME`` plus a
``winutils.exe`` binary to start; without those, every Spark session
construction fails with
``java.io.FileNotFoundException: HADOOP_HOME and hadoop.home.dir are unset``.
ADR-0002 deliberately keeps local Windows runs on delta-rs to avoid that
exact friction, so these Spark tests are expected to be run from WSL,
macOS, or Linux. The on-Databricks acceptance path for the H1 Spark
backend is the FCC 17-108 5K smoke run (production-blocker plan H1 gate),
not this file.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyarrow as pa
import pytest

_SHOULD_RUN = os.environ.get("ASTROTURF_RUN_SPARK_TESTS", "").lower() in {
    "1",
    "true",
    "yes",
}

pytestmark = pytest.mark.skipif(
    not _SHOULD_RUN,
    reason=(
        "Spark integration tests are opt-in. Set ASTROTURF_RUN_SPARK_TESTS=1 "
        "to enable them."
    ),
)


@pytest.fixture(scope="session")
def spark_session():
    """Local Spark with delta-spark wired up. Session-scoped so we pay the
    ~15s startup cost once per pytest invocation."""
    from delta import configure_spark_with_delta_pip
    from pyspark.sql import SparkSession

    builder = (
        SparkSession.builder.appName("astroturf-spark-writers-tests")
        .master("local[2]")
        .config(
            "spark.sql.extensions",
            "io.delta.sql.DeltaSparkSessionExtension",
        )
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        # Quiet down the local-mode warnings about Hive support / event log.
        .config("spark.ui.showConsoleProgress", "false")
    )
    spark = configure_spark_with_delta_pip(builder).getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    try:
        yield spark
    finally:
        spark.stop()


@pytest.fixture(autouse=True)
def _force_spark_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the backend to spark for every test in this module."""
    monkeypatch.setenv("ASTROTURF_DELTA_BACKEND", "spark")


def test_spark_merge_first_write_creates_path(
    spark_session,  # noqa: ARG001  (fixture present so the session is up)
    tmp_path: Path,
) -> None:
    """Brand-new path: spark_merge initializes a Delta table and reports
    the source row count as 'inserted'."""
    from shared.delta_utils.spark_writers import spark_merge

    path = tmp_path / "bronze_first_write"
    arrow = pa.Table.from_pydict(
        {"comment_id": ["c1", "c2"], "text": ["hello", "world"]}
    )
    metrics = spark_merge(path, arrow, "target.comment_id = source.comment_id")
    assert metrics == {"inserted": 2, "updated": 0}
    # Path now exists and has a Delta log.
    log_path = path / "_delta_log"
    assert log_path.exists(), f"Expected Delta log at {log_path}"


def test_spark_merge_second_write_idempotent(
    spark_session,  # noqa: ARG001
    tmp_path: Path,
) -> None:
    from shared.delta_utils.spark_writers import spark_merge

    path = tmp_path / "bronze_second_write"
    arrow = pa.Table.from_pydict(
        {"comment_id": ["c1", "c2"], "text": ["hello", "world"]}
    )
    spark_merge(path, arrow, "target.comment_id = source.comment_id")
    # Re-merge the same rows: should report 0/0 (idempotent).
    metrics = spark_merge(path, arrow, "target.comment_id = source.comment_id")
    assert metrics == {"inserted": 0, "updated": 0}


def test_spark_merge_additive_schema_evolution(
    spark_session,
    tmp_path: Path,
) -> None:
    """A second merge with an extra column triggers ALTER TABLE ADD COLUMNS.

    Validates the post-H1-first-cut design: schema evolution is driven by
    an explicit ``spark_ensure_schema`` call (issuing
    ``ALTER TABLE delta.``<path>`` ADD COLUMNS (...)``), not the
    ``spark.databricks.delta.schema.autoMerge.enabled`` session conf that
    Databricks Serverless rejects with ``[CONFIG_NOT_AVAILABLE]``.
    """
    from shared.delta_utils.spark_writers import spark_merge

    path = tmp_path / "bronze_evolve"
    v1 = pa.Table.from_pydict({"comment_id": ["c1"], "text": ["hello"]})
    spark_merge(path, v1, "target.comment_id = source.comment_id")
    schema_before = spark_session.read.format("delta").load(str(path)).schema
    assert {f.name for f in schema_before.fields} == {"comment_id", "text"}

    v2 = pa.Table.from_pydict(
        {"comment_id": ["c2"], "text": ["world"], "extra": ["new"]}
    )
    metrics = spark_merge(path, v2, "target.comment_id = source.comment_id")

    # 1 inserted (c2). c1 stays untouched.
    assert metrics == {"inserted": 1, "updated": 0}
    schema_after = spark_session.read.format("delta").load(str(path)).schema
    assert "extra" in {f.name for f in schema_after.fields}, (
        "ALTER TABLE ADD COLUMNS did not produce the new 'extra' column "
        "in the on-disk Delta schema."
    )


def test_spark_ensure_schema_type_mismatch_raises_before_merge(
    spark_session,  # noqa: ARG001
    tmp_path: Path,
) -> None:
    """Non-additive type change on an overlapping column must raise.

    Regression guard for the ADR-0004 contract: destructive changes
    (type narrowing, rename, drop) require an explicit migration. The
    Spark backend enforces this by raising before any DDL fires.
    """
    from shared.delta_utils.spark_writers import spark_ensure_schema, spark_merge

    path = tmp_path / "bronze_type_change"
    # Seed with comment_id as string.
    v1 = pa.Table.from_pydict({"comment_id": ["c1"], "text": ["hello"]})
    spark_merge(path, v1, "target.comment_id = source.comment_id")

    # Now claim comment_id should be int64 — that's a destructive change.
    bad_schema = pa.schema(
        [
            pa.field("comment_id", pa.int64()),
            pa.field("text", pa.string()),
        ]
    )
    with pytest.raises(ValueError, match="non-additive type change"):
        spark_ensure_schema(str(path), bad_schema, allow_destructive=True)


def test_spark_merge_empty_source_short_circuits(
    spark_session,  # noqa: ARG001
    tmp_path: Path,
) -> None:
    """An empty source must not produce a no-op MERGE that still writes a log
    entry (this is the 15-empty-MERGEs-per-page pattern the diagnosis
    flagged for the IngestionAgent loop)."""
    from shared.delta_utils.spark_writers import spark_merge

    path = tmp_path / "bronze_empty"
    # Seed an existing table so we'd otherwise go down the MERGE path.
    seed = pa.Table.from_pydict({"comment_id": ["c0"]})
    spark_merge(path, seed, "target.comment_id = source.comment_id")
    history_before = spark_session.sql(f"DESCRIBE HISTORY delta.`{path}`").count()
    empty = pa.Table.from_pydict({"comment_id": []}, schema=seed.schema)
    metrics = spark_merge(path, empty, "target.comment_id = source.comment_id")
    assert metrics == {"inserted": 0, "updated": 0}
    history_after = spark_session.sql(f"DESCRIBE HISTORY delta.`{path}`").count()
    assert history_before == history_after, (
        "Empty-source MERGE wrote a new Delta log entry; the short-circuit "
        "in spark_merge regressed."
    )


def test_spark_delete_missing_path_returns_zero(
    spark_session,  # noqa: ARG001
    tmp_path: Path,
) -> None:
    from shared.delta_utils.spark_writers import spark_delete

    path = tmp_path / "never_written"
    deleted = spark_delete(path, "docket_id = 'd1'")
    assert deleted == 0
    # Important: spark_delete does NOT create the path on its own (that's
    # spark_ensure_path_initialized's job). It just no-ops cleanly.
    assert not (path / "_delta_log").exists()
