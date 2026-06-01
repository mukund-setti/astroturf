-- 002_findings.sql
-- Curated, narratively-meaningful wrappers around clusters in the lakehouse.
--
-- A "finding" is one cluster plus a short headline and one_liner produced by
-- generateFindingFromCluster() (see ui/lib/findings-store.ts). The new
-- consumer-first UI navigates topic -> finding -> (optional) cluster drill-in,
-- so this table is what /topic/[slug] and /finding/[slug] read from.
--
-- One finding per cluster (UNIQUE cluster_id). The slug is derived
-- deterministically from cluster_id so re-running generation produces a
-- stable URL.

CREATE TABLE IF NOT EXISTS findings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id TEXT NOT NULL UNIQUE,
    docket_id TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    headline TEXT NOT NULL,
    one_liner TEXT NOT NULL,
    topic_slug TEXT NOT NULL,
    cluster_size INTEGER NOT NULL,
    posted_date_range TEXT,
    agency_id TEXT,
    is_featured BOOLEAN NOT NULL DEFAULT false,
    auto_generated BOOLEAN NOT NULL DEFAULT true,
    manually_edited BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS findings_topic_slug ON findings(topic_slug);
CREATE INDEX IF NOT EXISTS findings_docket_id ON findings(docket_id);
CREATE INDEX IF NOT EXISTS findings_cluster_size_desc ON findings(cluster_size DESC);
CREATE INDEX IF NOT EXISTS findings_is_featured ON findings(is_featured) WHERE is_featured = true;
