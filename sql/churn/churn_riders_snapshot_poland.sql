-- Canonical rider-level churn snapshot for Poland.
-- Segmentation:
--   - newbie: tenure_days < 30
--   - active: tenure_days >= 30
-- Churn definition:
--   - is_churned = 1 when rider has no slot booking in the previous 14 days as of timeframe_end.
-- Output columns:
--   rider_id | segment | start_week_of_tenure | tenure_days | week_of_churn | days_since_last_slot | is_churned | churn

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
      WHEN DATE_DIFF(timeframe_end, fd.first_delivery_date, DAY) < 30 THEN 'newbie'
      ELSE 'active'
    END AS segment,
    DATE_TRUNC(fd.first_delivery_date, WEEK(MONDAY)) AS start_week_of_tenure,
    DATE_DIFF(timeframe_end, fd.first_delivery_date, DAY) AS tenure_days,
    CASE
      WHEN ls.last_slot_date IS NULL THEN DATE_TRUNC(fd.first_delivery_date, WEEK(MONDAY))
      WHEN DATE_DIFF(timeframe_end, ls.last_slot_date, DAY) >= 14 THEN DATE_TRUNC(ls.last_slot_date, WEEK(MONDAY))
      ELSE NULL
    END AS week_of_churn,
    CASE
      WHEN ls.last_slot_date IS NULL THEN DATE_DIFF(timeframe_end, fd.first_delivery_date, DAY)
      ELSE DATE_DIFF(timeframe_end, ls.last_slot_date, DAY)
    END AS days_since_last_slot,
    CASE
      WHEN ls.last_slot_date IS NULL THEN 1
      WHEN DATE_DIFF(timeframe_end, ls.last_slot_date, DAY) >= 14 THEN 1
      ELSE 0
    END AS is_churned,
    CASE
      WHEN ls.last_slot_date IS NULL THEN 1
      WHEN DATE_DIFF(timeframe_end, ls.last_slot_date, DAY) >= 14 THEN 1
      ELSE 0
    END AS churn
  FROM eligible_riders er
  JOIN first_delivery fd ON fd.rider_id = er.rider_id
  LEFT JOIN last_slot ls ON ls.rider_id = er.rider_id
)

SELECT
  rider_id,
  segment,
  start_week_of_tenure,
  tenure_days,
  week_of_churn,
  days_since_last_slot,
  is_churned,
  churn
FROM rider_snapshot
ORDER BY rider_id;