-- Initial Astroturf Control Plane Migration Schema
-- Creates initial relational metadata storage tables for hosted production.

-- 1. Docket Catalog Cache Table
CREATE TABLE IF NOT EXISTS docket_catalog (
    docket_id VARCHAR(100) PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    agency_id VARCHAR(50) NOT NULL,
    topic_id VARCHAR(100) NOT NULL,
    title VARCHAR(255) NOT NULL,
    summary TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'discovered',
    comment_count_estimate INTEGER NOT NULL DEFAULT 0,
    last_comment_date TIMESTAMP WITH TIME ZONE,
    last_ingested_at TIMESTAMP WITH TIME ZONE,
    last_analyzed_at TIMESTAMP WITH TIME ZONE,
    freshness_label VARCHAR(100) NOT NULL DEFAULT 'Active',
    priority_score NUMERIC(5, 2) NOT NULL DEFAULT 0.00,
    user_requested_count INTEGER NOT NULL DEFAULT 0,
    tags_json JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata_json JSONB NOT NULL DEFAULT '{}'
);

-- Indexing docket catalog status and priority score for fast dashboard fetches
CREATE INDEX IF NOT EXISTS idx_docket_catalog_status ON docket_catalog(status);
CREATE INDEX IF NOT EXISTS idx_docket_catalog_priority ON docket_catalog(priority_score DESC);

-- 2. Analysis Requests Tracking Table
CREATE TABLE IF NOT EXISTS analysis_requests (
    request_id VARCHAR(50) PRIMARY KEY,
    docket_id VARCHAR(100) NOT NULL,
    source VARCHAR(50) NOT NULL,
    topic_id VARCHAR(100) NOT NULL,
    agency_id VARCHAR(50) NOT NULL,
    title VARCHAR(255) NOT NULL,
    date_start DATE,
    date_end DATE,
    expected_scale INTEGER NOT NULL DEFAULT 1000,
    notes TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    databricks_run_id VARCHAR(100),
    error_message TEXT,
    result_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata_json JSONB NOT NULL DEFAULT '{}'
);

-- Indexing analysis requests docket and status
CREATE INDEX IF NOT EXISTS idx_analysis_requests_docket ON analysis_requests(docket_id);
CREATE INDEX IF NOT EXISTS idx_analysis_requests_status ON analysis_requests(status);

-- 3. Watchlist Items Table
CREATE TABLE IF NOT EXISTS watchlist_items (
    watch_id VARCHAR(50) PRIMARY KEY,
    kind VARCHAR(50) NOT NULL,
    value VARCHAR(255) NOT NULL,
    label VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_checked_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata_json JSONB NOT NULL DEFAULT '{}',
    CONSTRAINT unique_watchlist_item UNIQUE (kind, value)
);

-- Indexing watchlist items status and kind
CREATE INDEX IF NOT EXISTS idx_watchlist_items_status ON watchlist_items(status);
CREATE INDEX IF NOT EXISTS idx_watchlist_items_kind_val ON watchlist_items(kind, value);

-- 4. Autopilot Workflow Runs Table
CREATE TABLE IF NOT EXISTS autopilot_runs (
    run_id VARCHAR(50) PRIMARY KEY,
    status VARCHAR(50) NOT NULL DEFAULT 'running',
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP WITH TIME ZONE,
    discovered_count INTEGER NOT NULL DEFAULT 0,
    queued_count INTEGER NOT NULL DEFAULT 0,
    triggered_count INTEGER NOT NULL DEFAULT 0,
    databricks_run_id VARCHAR(100),
    error_message TEXT,
    metadata_json JSONB NOT NULL DEFAULT '{}'
);

-- Indexing autopilot runs status
CREATE INDEX IF NOT EXISTS idx_autopilot_runs_status ON autopilot_runs(status);
