-- Weekly rider compliance violations for Poland from 2026-01-01
-- One row per rider x week x violation_type x action_type
-- Python pivots this to rider-level wide format for the correlation matrix

SELECT
  rider_id,
  DATE_TRUNC(created_date, WEEK(MONDAY)) AS week,
  r.violation_type,
  a.type AS action_type,
  COUNT(DISTINCT v.id) AS violations_count
FROM
  `fulfillment-dwh-production.curated_data_shared.rider_compliance`,
  UNNEST(violations) AS v,
  UNNEST(v.actions) AS a,
  UNNEST(v.rules) AS r
WHERE
  country_code = 'gv-pl'
  AND created_at >= '2026-01-01'
GROUP BY 1, 2, 3, 4
ORDER BY rider_id, week