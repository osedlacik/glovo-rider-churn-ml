-- Count of churned riders in Poland using the canonical snapshot logic.
-- Logic is aligned with churn_riders_snapshot_poland.sql.

DECLARE timeframe_start DATE DEFAULT DATE('2026-01-01');
DECLARE timeframe_end DATE DEFAULT CURRENT_DATE();

WITH first_delivery AS (
  SELECT
    d.rider_id,
    MIN(DATE(d.rider_dropped_off_at)) AS first_delivery_date
  FROM `fulfillment-dwh-production.curated_data_shared.orders` o,
  UNNEST(o.deliveries) d
  WHERE o.country_code = 'gv-pl'
    AND o.created_date >= DATE('2021-01-01')
    AND d.rider_id IS NOT NULL
    AND d.delivery_status = 'completed'
    AND d.is_primary = TRUE
    AND d.rider_dropped_off_at IS NOT NULL
  GROUP BY d.rider_id
),

eligible_riders AS (
  SELECT DISTINCT d.rider_id
  FROM `fulfillment-dwh-production.curated_data_shared.orders` o,
  UNNEST(o.deliveries) d
  WHERE o.country_code = 'gv-pl'
    AND o.created_date >= timeframe_start
    AND o.created_date <= timeframe_end
    AND d.rider_id IS NOT NULL
    AND d.delivery_status = 'completed'
    AND d.is_primary = TRUE
    AND d.rider_dropped_off_at IS NOT NULL
),

last_slot AS (
  SELECT
    s.rider_id,
    MAX(DATE(s.shift_start_at)) AS last_slot_date
  FROM `fulfillment-dwh-production.curated_data_shared.shifts` s
  WHERE s.country_code = 'gv-pl'
    AND s.created_date >= timeframe_start
    AND s.created_date <= timeframe_end
    AND s.rider_id IS NOT NULL
    AND s.shift_start_at IS NOT NULL
    AND s.shift_state IN ('EVALUATED', 'PUBLISHED', 'NO_SHOW', 'NO_SHOW_EXCUSED', 'CANCELLED')
  GROUP BY s.rider_id
),

rider_snapshot AS (
  SELECT
    er.rider_id,
    CASE
      WHEN ls.last_slot_date IS NULL THEN 1
      WHEN DATE_DIFF(timeframe_end, ls.last_slot_date, DAY) >= 14 THEN 1
      ELSE 0
    END AS is_churned
  FROM eligible_riders er
  JOIN first_delivery fd ON fd.rider_id = er.rider_id
  LEFT JOIN last_slot ls ON ls.rider_id = er.rider_id
)

SELECT
  COUNT(DISTINCT rider_id) AS churned_riders_in_timeframe
FROM rider_snapshot
WHERE is_churned = 1;
