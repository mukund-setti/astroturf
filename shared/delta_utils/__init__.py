"""Unified access to all Delta Lake merge and evolution helpers.

Every public writer here transparently dispatches to either delta-rs (for
local Windows runs) or Spark (for Databricks notebook execution) based on
the resolved backend in :mod:`shared.delta_utils.backend`. See ADR-0017 for
the local-vs-Databricks split and why we keep both backends.
"""

from __future__ import annotations

from shared.delta_utils.backend import (
    Backend,
    BackendChoice,
    ENV_VAR,
    get_configured_backend,
    looks_like_databricks_path,
    resolve_backend,
    should_use_spark,
)
from shared.delta_utils.bronze import merge_comments
from shared.delta_utils.silver import (
    load_delta_as_pyarrow,
    merge_parsed_comments,
    merge_comment_details,
    merge_comment_attachments,
    merge_comment_embeddings,
    ensure_schema,
)
from shared.delta_utils.gold import (
    delete_clustering_scope,
    merge_comment_clusters,
    merge_comment_cluster_memberships,
)
from shared.delta_utils.attribution import (
    delete_attribution_scope,
    merge_campaign_attributions,
)
from shared.delta_utils.migration import (
    delete_migration_scope,
    merge_rule_migrations,
)
from shared.delta_utils.discovery import (
    merge_docket_catalog,
    merge_watchlist,
    merge_analysis_requests,
    merge_autopilot_runs,
)

__all__ = [
    # Backend dispatch surface (callers normally never touch this).
    "Backend",
    "BackendChoice",
    "ENV_VAR",
    "get_configured_backend",
    "looks_like_databricks_path",
    "resolve_backend",
    "should_use_spark",
    # Bronze
    "merge_comments",
    # Silver
    "load_delta_as_pyarrow",
    "merge_parsed_comments",
    "merge_comment_details",
    "merge_comment_attachments",
    "merge_comment_embeddings",
    "ensure_schema",
    # Gold
    "delete_clustering_scope",
    "merge_comment_clusters",
    "merge_comment_cluster_memberships",
    # Attribution / migration
    "delete_attribution_scope",
    "merge_campaign_attributions",
    "delete_migration_scope",
    "merge_rule_migrations",
    # Discovery
    "merge_docket_catalog",
    "merge_watchlist",
    "merge_analysis_requests",
    "merge_autopilot_runs",
]
