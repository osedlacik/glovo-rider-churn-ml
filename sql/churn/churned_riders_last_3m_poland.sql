-- Riders who churned at least once in the last 3 months (Poland).
-- Returns one row per rider: their rider_id and the last week they were
-- labelled as churned.
--
-- "Churned" reuses the same threshold logic as churn_rider_weekly_poland.sql:
--   • newbie  (tenure < 30 d) : no slot activity in the previous 7 days
--   • veteran (tenure ≥ 30 d) : no slot activity in the previous 14 days

WITH

first_delivery AS (
  SELECT
    d.rider_id,
    MIN(DATE(d.rider_dropped_off_at)) AS first_delivery_date
  FROM `fulfillment-dwh-production.curated_data_shared.orders` o,
  UNNEST(o.deliveries) d
  WHERE o.country_code  = 'gv-pl'
    AND o.created_date >= DATE('2021-01-01')
    AND d.rider_id IS NOT NULL
    AND d.delivery_status = 'completed'
    AND d.is_primary = TRUE
    AND d.rider_dropped_off_at IS NOT NULL
  GROUP BY d.rider_id
),

deliveries_weekly AS (
  SELECT
    d.rider_id,
    DATE_TRUNC(DATE(d.rider_dropped_off_at), WEEK(MONDAY)) AS week,
    MAX(DATE(d.rider_dropped_off_at))                       AS last_delivery_in_week
  FROM `fulfillment-dwh-production.curated_data_shared.orders` o,
  UNNEST(o.deliveries) d
  WHERE o.country_code  = 'gv-pl'
    AND o.created_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 MONTH)
    AND d.rider_id IS NOT NULL
    AND d.delivery_status = 'completed'
    AND d.is_primary = TRUE
    AND d.rider_dropped_off_at IS NOT NULL
  GROUP BY d.rider_id, week
),

slots_weekly AS (
  SELECT
    rider_id,
    DATE_TRUNC(DATE(shift_start_at), WEEK(MONDAY)) AS week,
    MAX(DATE(shift_start_at))                       AS last_slot_in_week
  FROM `fulfillment-dwh-production.curated_data_shared.shifts`
  WHERE country_code  = 'gv-pl'
    AND created_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 MONTH)
    AND rider_id IS NOT NULL
    AND shift_start_at IS NOT NULL
    AND shift_state IN ('EVALUATED','PUBLISHED','NO_SHOW','NO_SHOW_EXCUSED','CANCELLED')
  GROUP BY rider_id, week
),

activity_weeks AS (
  SELECT rider_id, week, last_delivery_in_week, NULL AS last_slot_in_week
  FROM deliveries_weekly
  UNION ALL
  SELECT rider_id, week, NULL AS last_delivery_in_week, last_slot_in_week
  FROM slots_weekly
),

activity_agg AS (
  SELECT
    rider_id,
    week,
    MAX(last_delivery_in_week) AS last_delivery_in_week,
    MAX(last_slot_in_week)     AS last_slot_in_week
  FROM activity_weeks
  GROUP BY rider_id, week
),

rider_weekly AS (
  SELECT
    a.rider_id,
    a.week,
    a.last_delivery_in_week,
    MAX(a.last_delivery_in_week) OVER w_cum AS last_delivery_date,
    MAX(a.last_slot_in_week)     OVER w_cum AS last_slot_date
  FROM activity_agg a
  WINDOW w_cum AS (
    PARTITION BY a.rider_id
    ORDER BY a.week
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
  )
),

-- Apply churn label to every eligible week in the 3-month window
churn_weekly AS (
  SELECT
    rw.rider_id,
    rw.week,
    CASE
      WHEN rw.last_slot_date IS NULL                                                           THEN 1
      WHEN DATE_DIFF(rw.week, fd.first_delivery_date, DAY) < 30
           AND DATE_DIFF(rw.week, rw.last_slot_date, DAY) >= 7                                THEN 1
      WHEN DATE_DIFF(rw.week, fd.first_delivery_date, DAY) >= 30
           AND DATE_DIFF(rw.week, rw.last_slot_date, DAY) >= 14                               THEN 1
      ELSE 0
    END AS is_churned
  FROM rider_weekly rw
  JOIN first_delivery fd ON fd.rider_id = rw.rider_id
  WHERE rw.last_delivery_in_week IS NOT NULL   -- eligible weeks only
    AND rw.week >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 MONTH)
)

-- One row per rider: last week they were churned within the window
SELECT
  rider_id,
  MAX(week) AS last_churned_week
FROM churn_weekly
WHERE is_churned = 1
GROUP BY rider_id
ORDER BY last_churned_week DESC, rider_id
