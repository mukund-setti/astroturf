export type Source = "semantic" | "exact_hash";

export interface StatsPayload {
  total_comments: number;
  cluster_count: number;
  comments_in_clusters: number;
  largest_cluster_size: number;
  docket_id: string;
}

export interface ClusterSummary {
  cluster_id: string;
  cluster_size: number;
  similarity_threshold: number;
  embedding_model: string;
  representative_comment_id: string;
  rep_text_preview: string | null;
  rep_submitter_name: string | null;
  rep_posted_date: string | null;
  earliest_posted_date: string | null;
  latest_posted_date: string | null;
}

export interface ClusterRow {
  cluster_id: string;
  cluster_size: number;
  similarity_threshold: number;
  embedding_model: string;
  representative_comment_id: string;
  comment_id: string;
  is_representative: boolean;
  text_source: string | null;
  text_preview: string | null;
  submitter_name: string | null;
  posted_date: string | null;
  source: Source;
  exported_at: string | null;
  // Optional attribution / migration evidence — populated when
  // AttributionAgent / MigrationAgent have run (ADR-0015). Treat absence as
  // "Not yet analyzed"; never render as accusation.
  candidate_entity_name?: string | null;
  candidate_entity_type?: string | null;
  attribution_confidence?: number | null;
  attribution_evidence_url?: string | null;
  migration_match_type?: string | null;
  migration_section?: string | null;
  migration_similarity?: number | null;
  migration_claim_scope?: string | null;
}

export interface ClusterDetailPayload {
  cluster_id: string;
  rows: ClusterRow[];
}

export interface ApiError {
  error: string;
}
