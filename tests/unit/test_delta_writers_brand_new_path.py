"""Brand-new-path coverage for the Delta writer dispatchers.

The "first write to a brand-new path" case is the single most likely
"works locally, breaks on Databricks" failure mode for the H1 work (see
the production-blocker plan, refinement 2). This file exercises that case
across all six dispatcher modules on the delta-rs backend, which is what
local Windows runs use today and what tests/CI exercise.

The Spark equivalent of these tests lives in
``tests/integration/test_spark_writers.py`` and is opt-in via the
``ASTROTURF_RUN_SPARK_TESTS=1`` environment variable so it does not slow
down the regular unit-test loop.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest
from deltalake import DeltaTable

from shared.delta_utils.attribution import merge_campaign_attributions
from shared.delta_utils.bronze import merge_comments
from shared.delta_utils.discovery import (
    merge_analysis_requests,
    merge_autopilot_runs,
    merge_docket_catalog,
    merge_watchlist,
)
from shared.delta_utils.gold import (
    delete_clustering_scope,
    merge_comment_cluster_memberships,
    merge_comment_clusters,
)
from shared.delta_utils.migration import merge_rule_migrations
from shared.delta_utils.silver import (
    merge_comment_attachments,
    merge_comment_details,
    merge_comment_embeddings,
    merge_parsed_comments,
)


@pytest.fixture(autouse=True)
def _force_delta_rs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the backend to delta_rs so tests don't pick up an ambient Spark
    session if one happens to be active in the test runner."""
    monkeypatch.setenv("ASTROTURF_DELTA_BACKEND", "delta_rs")


def _arrow_two_rows(
    key_name: str, extra_cols: dict[str, list] | None = None
) -> pa.Table:
    cols: dict[str, list] = {key_name: ["a1", "a2"]}
    if extra_cols:
        cols.update(extra_cols)
    return pa.Table.from_pydict(cols)


def test_merge_comments_first_write_creates_path(tmp_path: Path) -> None:
    path = tmp_path / "bronze" / "raw_comments"
    assert not path.exists()
    arrow = _arrow_two_rows("comment_id", {"text": ["hello", "world"]})
    metrics = merge_comments(path, arrow)
    assert metrics == {"inserted": 2, "updated": 0}
    assert DeltaTable.is_deltatable(str(path))
    # Re-merge with same rows: no new inserts. delta-rs's
    # when_matched_update_all always reports the matched row count as
    # `updated`, even when the source/target values are identical (Delta
    # MERGE does not do row-value comparisons in this dialect), so the
    # meaningful idempotency claim is "no new rows", not "no row writes".
    metrics = merge_comments(path, arrow)
    assert metrics["inserted"] == 0
    assert DeltaTable(str(path)).to_pyarrow_table().num_rows == 2


def test_merge_parsed_comments_first_write_creates_path(tmp_path: Path) -> None:
    path = tmp_path / "silver" / "parsed_comments"
    arrow = _arrow_two_rows("comment_id")
    metrics = merge_parsed_comments(path, arrow)
    assert metrics == {"inserted": 2, "updated": 0}
    assert DeltaTable.is_deltatable(str(path))


def test_merge_comment_details_first_write_creates_path(tmp_path: Path) -> None:
    path = tmp_path / "silver" / "comment_details"
    arrow = _arrow_two_rows("comment_id")
    metrics = merge_comment_details(path, arrow)
    assert metrics == {"inserted": 2, "updated": 0}


def test_merge_comment_attachments_first_write_creates_path(tmp_path: Path) -> None:
    path = tmp_path / "silver" / "comment_attachments"
    arrow = _arrow_two_rows("attachment_id")
    metrics = merge_comment_attachments(path, arrow)
    assert metrics == {"inserted": 2, "updated": 0}


def test_merge_comment_embeddings_first_write_creates_path(tmp_path: Path) -> None:
    path = tmp_path / "silver" / "comment_embeddings"
    arrow = pa.Table.from_pydict(
        {
            "comment_id": ["c1", "c2"],
            "embedding_model": ["m", "m"],
            "embedding": [[0.1, 0.2], [0.3, 0.4]],
        }
    )
    metrics = merge_comment_embeddings(path, arrow)
    assert metrics == {"inserted": 2, "updated": 0}


def test_merge_comment_clusters_first_write_creates_path(tmp_path: Path) -> None:
    path = tmp_path / "gold" / "comment_clusters"
    arrow = pa.Table.from_pydict({"cluster_id": ["c1", "c2"]})
    metrics = merge_comment_clusters(path, arrow)
    assert metrics == {"inserted": 2, "updated": 0}


def test_merge_comment_cluster_memberships_first_write_creates_path(
    tmp_path: Path,
) -> None:
    path = tmp_path / "gold" / "comment_cluster_memberships"
    arrow = pa.Table.from_pydict({"cluster_id": ["c1", "c1"], "comment_id": ["a", "b"]})
    metrics = merge_comment_cluster_memberships(path, arrow)
    assert metrics == {"inserted": 2, "updated": 0}


def test_merge_campaign_attributions_first_write_creates_path(
    tmp_path: Path,
) -> None:
    path = tmp_path / "gold" / "campaign_attributions"
    arrow = pa.Table.from_pydict({"attribution_id": ["a1"], "docket_id": ["d1"]})
    metrics = merge_campaign_attributions(path, arrow)
    assert metrics == {"inserted": 1, "updated": 0}


def test_merge_rule_migrations_first_write_creates_path(tmp_path: Path) -> None:
    path = tmp_path / "gold" / "rule_migrations"
    arrow = pa.Table.from_pydict(
        {
            "migration_id": ["m1"],
            "docket_id": ["d1"],
            "cluster_id": ["c1"],
            "caveat_text": ["heuristic"],
        }
    )
    metrics = merge_rule_migrations(path, arrow)
    assert metrics == {"inserted": 1, "updated": 0}


def test_merge_docket_catalog_first_write_creates_path(tmp_path: Path) -> None:
    path = tmp_path / "discovery" / "docket_catalog"
    arrow = pa.Table.from_pydict({"docket_id": ["d1", "d2"]})
    metrics = merge_docket_catalog(path, arrow)
    assert metrics == {"inserted": 2, "updated": 0}


def test_merge_watchlist_first_write_creates_path(tmp_path: Path) -> None:
    path = tmp_path / "discovery" / "watchlist"
    arrow = pa.Table.from_pydict({"watch_id": ["w1"], "docket_id": ["d1"]})
    metrics = merge_watchlist(path, arrow)
    assert metrics == {"inserted": 1, "updated": 0}


def test_merge_analysis_requests_first_write_creates_path(tmp_path: Path) -> None:
    path = tmp_path / "discovery" / "analysis_requests"
    arrow = pa.Table.from_pydict({"request_id": ["r1"], "docket_id": ["d1"]})
    metrics = merge_analysis_requests(path, arrow)
    assert metrics == {"inserted": 1, "updated": 0}


def test_merge_autopilot_runs_first_write_creates_path(tmp_path: Path) -> None:
    path = tmp_path / "discovery" / "autopilot_runs"
    arrow = pa.Table.from_pydict(
        {"run_id": ["ar1"], "docket_id": ["d1"], "status": ["ok"]}
    )
    metrics = merge_autopilot_runs(path, arrow)
    assert metrics == {"inserted": 1, "updated": 0}


def test_delete_clustering_scope_initializes_missing_path(tmp_path: Path) -> None:
    """Delete-on-missing-path should initialize the table (so subsequent merges
    have a target) and report 0 deleted rows."""
    path = tmp_path / "gold" / "comment_clusters"
    schema = pa.schema(
        [
            pa.field("cluster_id", pa.string()),
            pa.field("docket_id", pa.string()),
            pa.field("embedding_model", pa.string()),
            pa.field("clustering_version", pa.string()),
            pa.field("similarity_threshold", pa.float64()),
        ]
    )
    deleted = delete_clustering_scope(
        path,
        schema,
        docket_id="d1",
        embedding_model="m1",
        clustering_version="v1",
        similarity_threshold=0.92,
    )
    assert deleted == 0
    assert DeltaTable.is_deltatable(str(path))
