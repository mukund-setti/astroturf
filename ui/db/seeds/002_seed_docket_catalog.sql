-- Seed docket_catalog with the same canonical fallback dockets that
-- scripts/discover_dockets.py::generate_fallback_dockets() emits, plus the
-- two dockets we've actually run analysis against. Run this once against
-- Supabase to make /discoveries render real entries.
--
-- Idempotent: ON CONFLICT (docket_id) DO UPDATE refreshes everything except
-- created_at and user_requested_count (those are preserved so user activity
-- across re-seeds isn't lost).

INSERT INTO docket_catalog (
  docket_id, source, agency_id, topic_id, title, summary, status,
  comment_count_estimate, last_comment_date, freshness_label,
  priority_score, tags_json
) VALUES
  (
    'CFPB-2016-0025', 'regulations_gov', 'CFPB', 'consumer_finance',
    'Payday, Vehicle Title, and Certain High-Cost Installment Loans',
    'CFPB rulemaking on small-dollar lending; large-scale comment record with documented coordinated campaigns.',
    'analyzed', 211885, '2016-10-07T23:59:00Z', 'Analyzed',
    85.00, '["consumer_finance","CFPB","payday"]'::jsonb
  ),
  (
    '17-108', 'ecfs', 'FCC', 'telecom',
    'Restoring Internet Freedom (Net Neutrality)',
    'FCC NPRM repealing 2015 Open Internet Order. Best-known case study for coordinated public comment campaigns.',
    'analyzed', 21800000, '2018-08-30T23:59:00Z', 'Stale',
    90.00, '["telecom","FCC","net neutrality"]'::jsonb
  ),
  (
    'FTC-2024-0012', 'regulations_gov', 'FTC', 'ai_regulation',
    'Algorithmic Transparency & Consumer Safety Rulemaking',
    'Proposed rule requiring comprehensive audits and third-party risk analysis for large consumer-facing automated decision-making engines.',
    'discovered', 45000, '2026-05-20T18:00:00Z', 'Active',
    75.00, '["AI","transparency","consumer safety"]'::jsonb
  ),
  (
    'FTC-2023-0007', 'regulations_gov', 'FTC', 'labor',
    'Non-Compete Clause Ban and Workplace Freedom Rule',
    'Comprehensive regulatory action to ban non-compete clauses in employment contracts nationwide.',
    'discovered', 260000, '2026-05-24T14:30:00Z', 'Active',
    90.00, '["labor","workplace","competition","non-compete"]'::jsonb
  ),
  (
    'FDA-2023-N-1200', 'regulations_gov', 'FDA', 'healthcare',
    'Clinical Trial Software Quality and Device Interface Standards',
    'Oversight docket evaluating data reliability, electronic logging standards, and cybersecurity requirements for clinical trial hardware interfaces.',
    'discovered', 8500, '2026-04-15T09:00:00Z', 'Stale',
    50.00, '["healthcare","FDA","software","devices"]'::jsonb
  ),
  (
    '23-562', 'ecfs', 'FCC', 'ai_regulation',
    'Transparency and Disclosure in Algorithmic Ad Targeting',
    'Inquiry regarding the role of automated media distribution platforms and algorithm disclosures for broadcast/narrowcast cable providers.',
    'discovered', 1200, '2026-05-24T10:00:00Z', 'Active',
    45.00, '["FCC","ECFS","AI","media","ad targeting"]'::jsonb
  ),
  (
    '14-28', 'ecfs', 'FCC', 'privacy',
    'Robocall Spoofing Prevention and Caller ID Privacy Protections',
    'Active regulatory measures to implement STIR/SHAKEN standards and enforce severe penalty structures for predatory caller spoofing networks.',
    'discovered', 15000, '2026-05-22T17:45:00Z', 'Active',
    60.00, '["FCC","privacy","spoofing","robocalls"]'::jsonb
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
  updated_at = CURRENT_TIMESTAMP;

-- Verify
SELECT docket_id, source, agency_id, status, priority_score
FROM docket_catalog
ORDER BY priority_score DESC;
