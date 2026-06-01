-- 004_analysis_requests_user_tracking.sql
-- Extends analysis_requests so the consumer-facing "queue this for me" flow
-- can track who requested what and surface that request back to the same
-- user via the astroturf_uid HTTP-only cookie.
--
-- requested_by  : opaque UUID minted by lib/user-session.ts on first visit
-- query_text    : the free-text the user typed (for diagnostics + the badge)
-- topic_slug    : the new-taxonomy slug (topics.ts) the request was tagged
--                 with at queue time, distinct from the legacy topic_id
--                 column which is keyed off fallback-data.ts.

ALTER TABLE analysis_requests
  ADD COLUMN IF NOT EXISTS requested_by TEXT,
  ADD COLUMN IF NOT EXISTS query_text TEXT,
  ADD COLUMN IF NOT EXISTS topic_slug TEXT;

CREATE INDEX IF NOT EXISTS analysis_requests_requested_by
  ON analysis_requests(requested_by);
