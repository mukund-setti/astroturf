"""Unified access to all bronze, silver, gold, and discovery schemas."""

from __future__ import annotations

from shared.schemas.comments import (
    RawComment,
    raw_comment_arrow_schema,
    raw_comment_struct,
)
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
from shared.schemas.comment_embeddings import (
    CommentEmbedding,
    comment_embedding_arrow_schema,
    comment_embedding_struct,
)
from shared.schemas.comment_clusters import (
    CommentCluster,
    comment_cluster_arrow_schema,
    comment_cluster_struct,
)
from shared.schemas.cluster_review_export import (
    ClusterReviewExportRow,
    cluster_review_export_arrow_schema,
    cluster_review_export_struct,
)
from shared.schemas.campaign_attributions import (
    CampaignAttribution,
    campaign_attributions_arrow_schema,
    campaign_attributions_struct,
)
from shared.schemas.rule_migrations import (
    RuleMigration,
    rule_migrations_arrow_schema,
    rule_migrations_struct,
)

# Discovery schemas
from shared.schemas.docket_catalog import (
    DiscoveredDocket,
    docket_catalog_arrow_schema,
    docket_catalog_struct,
)
from shared.schemas.watchlist import (
    WatchlistItem,
    watchlist_arrow_schema,
    watchlist_struct,
)
from shared.schemas.analysis_requests import (
    AnalysisRequestModel,
    analysis_requests_arrow_schema,
    analysis_requests_struct,
)
from shared.schemas.autopilot_runs import (
    AutopilotRun,
    autopilot_runs_arrow_schema,
    autopilot_runs_struct,
)

__all__ = [
    "RawComment",
    "raw_comment_arrow_schema",
    "raw_comment_struct",
    "ParsedComment",
    "parsed_comment_arrow_schema",
    "parsed_comment_struct",
    "CommentDetail",
    "comment_detail_arrow_schema",
    "comment_detail_struct",
    "CommentAttachment",
    "comment_attachment_arrow_schema",
    "comment_attachment_struct",
    "CommentEmbedding",
    "comment_embedding_arrow_schema",
    "comment_embedding_struct",
    "CommentCluster",
    "comment_cluster_arrow_schema",
    "comment_cluster_struct",
    "ClusterReviewExportRow",
    "cluster_review_export_arrow_schema",
    "cluster_review_export_struct",
    "CampaignAttribution",
    "campaign_attributions_arrow_schema",
    "campaign_attributions_struct",
    "RuleMigration",
    "rule_migrations_arrow_schema",
    "rule_migrations_struct",
    # Discovery
    "DiscoveredDocket",
    "docket_catalog_arrow_schema",
    "docket_catalog_struct",
    "WatchlistItem",
    "watchlist_arrow_schema",
    "watchlist_struct",
    "AnalysisRequestModel",
    "analysis_requests_arrow_schema",
    "analysis_requests_struct",
    "AutopilotRun",
    "autopilot_runs_arrow_schema",
    "autopilot_runs_struct",
]
