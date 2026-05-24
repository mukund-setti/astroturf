"""Unified access to all Delta Lake merge and evolution helpers."""

from __future__ import annotations

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
    merge_comment_clusters,
    merge_comment_cluster_memberships,
)
from shared.delta_utils.attribution import merge_campaign_attributions
from shared.delta_utils.migration import merge_rule_migrations

# Discovery merge utilities
from shared.delta_utils.discovery import (
    merge_docket_catalog,
    merge_watchlist,
    merge_analysis_requests,
    merge_autopilot_runs,
)

__all__ = [
    "merge_comments",
    "load_delta_as_pyarrow",
    "merge_parsed_comments",
    "merge_comment_details",
    "merge_comment_attachments",
    "merge_comment_embeddings",
    "ensure_schema",
    "merge_comment_clusters",
    "merge_comment_cluster_memberships",
    "merge_campaign_attributions",
    "merge_rule_migrations",
    # Discovery
    "merge_docket_catalog",
    "merge_watchlist",
    "merge_analysis_requests",
    "merge_autopilot_runs",
]
