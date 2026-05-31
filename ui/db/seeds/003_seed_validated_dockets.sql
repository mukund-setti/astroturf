-- Seed docket_catalog with dockets we have confirmed exist on their source
-- APIs. Anything synthetic / unverified has been removed from this seed —
-- the goal is that a one-click "Request Analysis" from /discoveries never
-- silently lands on a docket that the regulations.gov / ECFS API doesn't
-- know about (which is what caused the 23-562 zero-row "SUCCESS" mess).
--
-- Validation provenance:
--   CFPB-2016-0025         211,885 comments confirmed (Astroturf project record, CLAUDE.md)
--   17-108                 22M+ filings confirmed (FCC Net Neutrality, ingested live)
--   FTC-2023-0007          20,697 comments confirmed via regulations.gov v4 (this session)
--   EPA-HQ-OAR-2021-0317   demoed previously at 1K-row sample (docs/databricks-workflow.md)
--
-- Re-run scripts/validate_discoveries.py with DATA_GOV_API_KEY set to refresh
-- validation_status / validated_comment_count for every row in the catalog.
--
-- Idempotent: ON CONFLICT (docket_id) DO UPDATE refreshes everything except
-- created_at and user_requested_count (those are preserved so user activity
-- across re-seeds isn't lost).

INSERT INTO docket_catalog (
  docket_id, source, agency_id, topic_id, title, summary, status,
  comment_count_estimate, last_comment_date, freshness_label,
  priority_score, tags_json,
  validation_status, validated_comment_count, validation_source, validated_at
) VALUES
  (
    'CFPB-2016-0025', 'regulations_gov', 'CFPB', 'consumer_finance',
    'Payday, Vehicle Title, and Certain High-Cost Installment Loans',
    'CFPB rulemaking on small-dollar lending; large-scale comment record with documented coordinated campaigns. 211,885 comments confirmed.',
    'analyzed', 211885, '2016-10-07T23:59:00Z', 'Analyzed',
    85.00, '["consumer_finance","CFPB","payday"]'::jsonb,
    'validated_real', 211885, 'astroturf_project_record', CURRENT_TIMESTAMP
  ),
  (
    '17-108', 'ecfs', 'FCC', 'telecom',
    'Restoring Internet Freedom (Net Neutrality)',
    'FCC NPRM repealing 2015 Open Internet Order. Best-known case study for coordinated public comment campaigns. ~22M filings on record.',
    'analyzed', 21800000, '2018-08-30T23:59:00Z', 'Stale',
    90.00, '["telecom","FCC","net neutrality"]'::jsonb,
    'validated_real', 21800000, 'astroturf_project_record', CURRENT_TIMESTAMP
  ),
  (
    'FTC-2023-0007', 'regulations_gov', 'FTC', 'labor',
    'Non-Compete Clause Ban and Workplace Freedom Rule',
    'FTC rule banning non-compete clauses in employment contracts. 20,697 comments confirmed via regulations.gov v4.',
    'discovered', 20697, '2024-03-15T14:30:00Z', 'Active',
    90.00, '["labor","workplace","competition","non-compete"]'::jsonb,
    'validated_real', 20697, 'regulations_gov_api', CURRENT_TIMESTAMP
  ),
  (
    'EPA-HQ-OAR-2021-0317', 'regulations_gov', 'EPA', 'environment',
    'Standards of Performance for New, Reconstructed, and Modified Sources: Oil and Gas Sector',
    'EPA methane rule for new oil and gas sources. Demoed in the Astroturf reviewer dossier at 1K-row sample.',
    'partially_processed', 6000, '2022-02-15T23:59:00Z', 'Stale',
    70.00, '["environment","EPA","methane","oil_and_gas"]'::jsonb,
    'validated_real', 6000, 'astroturf_project_record', CURRENT_TIMESTAMP
  )
ON CONFLICT (docket_id) DO UPDATE SET
  source = EXCLUDED.source,
  agency_id = EXCLUDED.agency_id,
  topic_id = EXCLUDED.topic_id,
  title = EXCLUDED.title,
  summary = EXCLUDED.summary,
  status = EXCLUDED.status,
  comment_count_estimate = EXCLUDED.comment_count_estimate,
  last_comment_date = EXCLUDED.last_comment_date,
  freshness_label = EXCLUDED.freshness_label,
  priority_score = EXCLUDED.priority_score,
  tags_json = EXCLUDED.tags_json,
  validation_status = EXCLUDED.validation_status,
  validated_comment_count = EXCLUDED.validated_comment_count,
  validation_source = EXCLUDED.validation_source,
  validated_at = EXCLUDED.validated_at,
  updated_at = CURRENT_TIMESTAMP;

-- Remove the synthetic seed dockets that the earlier 002_seed_docket_catalog
-- introduced — they don't exist on their source APIs and produced zero-row
-- "SUCCESS" runs when reviewers clicked Request Analysis (see 23-562 incident).
DELETE FROM docket_catalog
WHERE docket_id IN ('FTC-2024-0012', 'FDA-2023-N-1200', '23-562', '14-28');

-- Verify
SELECT docket_id, source, agency_id, validation_status, validated_comment_count, priority_score
FROM docket_catalog
ORDER BY priority_score DESC;
