-- Flat weekly rider contact reasons for Poland from 2026-01-01
-- One row per rider x week x contact_reason_code
-- Python pivots this to wide format for the correlation matrix

SELECT
  content.rider_id                                         AS rider_id,
  DATE_TRUNC(DATE(timestamp), WEEK(MONDAY))                AS week,
  COALESCE(content.contact_reason_code, 'unknown')         AS contact_reason_code,
  COUNT(*)                                                  AS ticket_count

FROM `fulfillment-dwh-production.curated_data_shared_data_stream.rider_ticket_stream`

WHERE timestamp > TIMESTAMP('2026-01-01')
  AND content.global_entity_id = 'GV_PL'
  AND content.action = 'Create'
  AND content.rider_id IS NOT NULL

GROUP BY 1, 2, 3
ORDER BY rider_id, week
