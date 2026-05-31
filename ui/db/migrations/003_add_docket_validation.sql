-- 003_add_docket_validation.sql
-- Adds source-API validation tracking to docket_catalog so the UI can show a
-- "Validated against source API" badge and so synthetic / non-existent
-- fallback seeds can't masquerade as real public-comment dockets.
--
-- See scripts/validate_discoveries.py for the validator that populates these
-- columns by hitting regulations.gov v4 and FCC ECFS.

ALTER TABLE docket_catalog
  ADD COLUMN IF NOT EXISTS validation_status VARCHAR(50) NOT NULL DEFAULT 'unvalidated',
  ADD COLUMN IF NOT EXISTS validated_comment_count INTEGER,
  ADD COLUMN IF NOT EXISTS validated_at TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS validation_source VARCHAR(100);

-- Valid values for validation_status:
--   'unvalidated'        — never checked against the source API
--   'validated_real'     — source API confirmed the docket exists with >0 comments
--   'validated_empty'    — source API confirmed the docket exists but has 0 comments
--   'not_found'          — source API has no record of this docket; treat as
--                          synthetic/seed and hide from one-click request flow
--   'error'              — last validation attempt failed (rate limit, network, etc.)

CREATE INDEX IF NOT EXISTS idx_docket_catalog_validation_status
  ON docket_catalog(validation_status);
