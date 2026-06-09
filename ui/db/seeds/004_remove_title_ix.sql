-- Remove the ED-2018-OCR-0064 Title IX sexual harassment docket and any
-- findings generated from its clusters. This docket was politically charged
-- and not appropriate for a public, recruiter-facing demo; the smart-queue
-- script and topic catalog no longer reference it. This seed cleans up any
-- rows the autopilot or earlier runs already wrote.
--
-- Idempotent: deletes by docket_id; safe to re-run.

DELETE FROM findings WHERE docket_id = 'ED-2018-OCR-0064';

DELETE FROM analysis_requests WHERE docket_id = 'ED-2018-OCR-0064';

DELETE FROM docket_catalog WHERE docket_id = 'ED-2018-OCR-0064';

-- Verify
SELECT 'findings'        AS table_name, COUNT(*) AS remaining FROM findings        WHERE docket_id = 'ED-2018-OCR-0064'
UNION ALL
SELECT 'analysis_requests',             COUNT(*)              FROM analysis_requests WHERE docket_id = 'ED-2018-OCR-0064'
UNION ALL
SELECT 'docket_catalog',                COUNT(*)              FROM docket_catalog    WHERE docket_id = 'ED-2018-OCR-0064';
