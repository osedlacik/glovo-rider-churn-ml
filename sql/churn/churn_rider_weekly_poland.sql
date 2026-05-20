-- Rider-week churn labels for modeling
-- Definition at each week:
--   Eligible rider: at least 1 completed primary delivery up to week
--   Churned at week: no slot booking in last threshold days up to week
--     - newbie  (<30 days since FIRST DELIVERY): 7 days
--     - veteran (>=30 days since first delivery): 14 days
-- Newbie tenure is from first_delivery_date, not hire_date.
-- Scope: Poland only (country_code = 'gv-pl'), data from 2026-01-01 onward

DECLARE start_date DATE DEFAULT DATE('2026-01-01');
DECLARE end_date   DATE DEFAULT CURRENT_DATE();

WITH

-- Global first delivery date per rider (no start_date filter so tenure is
-- accurate for riders who started delivering before 2026-01-01)
first_delivery AS (
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

rider_hire AS (
  SELECT
    r.rider_id,
    MIN(DATE(c.start_at)) AS first_contract_start_date,
    DATE(r.created_at)    AS rider_created_date
  FROM `fulfillment-dwh-production.curated_data_shared.riders` r
  LEFT JOIN UNNEST(r.contracts) c
  WHERE r.country_code IN ('gv-pl', 'PL')
  GROUP BY r.rider_id, rider_created_date
),

rider_base AS (
  SELECT
    rh.rider_id,
    COALESCE(rh.first_contract_start_date, rh.rider_created_date) AS hire_date,
    fd.first_delivery_date
  FROM rider_hire rh
  LEFT JOIN first_delivery fd ON fd.rider_id = rh.rider_id
),

deliveries_daily AS (
  SELECT
    d.rider_id,
    DATE(d.rider_dropped_off_at) AS delivery_date
  FROM `fulfillment-dwh-production.curated_data_shared.orders` o,
  UNNEST(o.deliveries) d
  WHERE o.country_code = 'gv-pl'
    AND o.created_date >= start_date
    AND o.created_date <= end_date
    AND d.rider_id IS NOT NULL
    AND d.delivery_status = 'completed'
    AND d.is_primary = TRUE
    AND d.rider_dropped_off_at IS NOT NULL
),

slots_daily AS (
  SELECT
    s.rider_id,
    DATE(s.shift_start_at) AS slot_date
  FROM `fulfillment-dwh-production.curated_data_shared.shifts` s
  WHERE s.country_code = 'gv-pl'
    AND s.created_date >= start_date
    AND s.created_date <= end_date
    AND s.rider_id IS NOT NULL
    AND s.shift_state IN ('EVALUATED', 'PUBLISHED', 'NO_SHOW', 'NO_SHOW_EXCUSED', 'CANCELLED')
),

weeks AS (
  SELECT week_start
  FROM UNNEST(GENERATE_DATE_ARRAY(start_date, end_date, INTERVAL 7 DAY)) AS week_start
),

eligible_rider_weeks AS (
  SELECT
    w.week_start,
    d.rider_id
  FROM weeks w
  JOIN deliveries_daily d
    ON d.delivery_date <= w.week_start
  GROUP BY w.week_start, d.rider_id
),

rider_week_features AS (
  SELECT
    erw.week_start,
    erw.rider_id,
    rb.hire_date,
    rb.first_delivery_date,
    -- Tenure from first delivery date for newbie classification
    DATE_DIFF(erw.week_start, rb.first_delivery_date, DAY) AS tenure_days,
    MAX(d.delivery_date) AS last_delivery_date,
    MAX(s.slot_date)     AS last_slot_date
  FROM eligible_rider_weeks erw
  LEFT JOIN rider_base rb
    ON rb.rider_id = erw.rider_id
  LEFT JOIN deliveries_daily d
    ON d.rider_id = erw.rider_id
   AND d.delivery_date <= erw.week_start
  LEFT JOIN slots_daily s
    ON s.rider_id = erw.rider_id
   AND s.slot_date <= erw.week_start
  GROUP BY erw.week_start, erw.rider_id, rb.hire_date, rb.first_delivery_date
)

SELECT
  week_start                                          AS week,
  rider_id,
  hire_date,
  first_delivery_date,
  tenure_days,
  last_delivery_date,
  DATE_TRUNC(last_delivery_date, WEEK(MONDAY))        AS last_active_week,
  last_slot_date,
  DATE_DIFF(week_start, last_slot_date, DAY)          AS days_since_last_slot,
  CASE WHEN tenure_days < 30 THEN 'newbie' ELSE 'active_or_veteran' END AS segment,
  CASE WHEN tenure_days < 30 THEN 7 ELSE 14 END       AS churn_threshold_days,
  CASE
    WHEN last_slot_date IS NULL                                                THEN 1
    WHEN tenure_days < 30  AND DATE_DIFF(week_start, last_slot_date, DAY) >= 7  THEN 1
    WHEN tenure_days >= 30 AND DATE_DIFF(week_start, last_slot_date, DAY) >= 14 THEN 1
    ELSE 0
  END AS is_churned

FROM rider_week_features
