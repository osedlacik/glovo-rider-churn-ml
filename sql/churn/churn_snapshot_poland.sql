-- Rider churn snapshot as of a chosen date
-- Definition:
--   Eligible rider: at least 1 completed primary delivery since 2026-01-01
--   Churned: no booked slot for threshold days as of as_of_date
--     - newbie (<30 tenure days): 7 days
--     - active/veteran (>=30 tenure days): 14 days
-- Scope: Poland only (country_code = 'gv-pl'), data from 2026-01-01 onward

DECLARE as_of_date DATE DEFAULT CURRENT_DATE();

WITH rider_hire AS (
  SELECT
    r.rider_id,
    MIN(DATE(c.start_at)) AS first_contract_start_date,
    DATE(r.created_at) AS rider_created_date
  FROM `fulfillment-dwh-production.curated_data_shared.riders` r
  LEFT JOIN UNNEST(r.contracts) c
  WHERE r.country_code IN ('gv-pl', 'PL')
  GROUP BY r.rider_id, rider_created_date
),

rider_base AS (
  SELECT
    rider_id,
    COALESCE(first_contract_start_date, rider_created_date) AS hire_date
  FROM rider_hire
),

delivered_orders AS (
  SELECT
    d.rider_id,
    MAX(DATE(d.rider_dropped_off_at)) AS last_delivered_order_date,
    COUNT(DISTINCT o.order_id) AS delivered_orders_cnt
  FROM `fulfillment-dwh-production.curated_data_shared.orders` o,
  UNNEST(o.deliveries) d
  WHERE o.country_code = 'gv-pl'
    AND o.created_date >= DATE('2026-01-01')
    AND o.created_date <= as_of_date
    AND d.rider_id IS NOT NULL
    AND d.delivery_status = 'completed'
    AND d.is_primary = TRUE
    AND d.rider_dropped_off_at IS NOT NULL
  GROUP BY d.rider_id
),

slot_bookings AS (
  SELECT
    s.rider_id,
    MAX(DATE(s.shift_start_at)) AS last_slot_booking_date,
    COUNT(*) AS booked_slots_cnt
  FROM `fulfillment-dwh-production.curated_data_shared.shifts` s
  WHERE s.country_code = 'gv-pl'
    AND s.created_date >= DATE('2026-01-01')
    AND s.created_date <= as_of_date
    AND s.rider_id IS NOT NULL
    AND s.shift_state IN ('EVALUATED', 'PUBLISHED', 'NO_SHOW', 'NO_SHOW_EXCUSED', 'CANCELLED')
  GROUP BY s.rider_id
),

churn_base AS (
  SELECT
    o.rider_id,
    rb.hire_date,
    o.last_delivered_order_date,
    s.last_slot_booking_date,
    o.delivered_orders_cnt,
    s.booked_slots_cnt,
    DATE_DIFF(as_of_date, rb.hire_date, DAY) AS tenure_days,
    DATE_DIFF(as_of_date, s.last_slot_booking_date, DAY) AS days_since_last_slot_booking
  FROM delivered_orders o
  LEFT JOIN slot_bookings s USING (rider_id)
  LEFT JOIN rider_base rb USING (rider_id)
)

SELECT
  rider_id,
  hire_date,
  last_delivered_order_date,
  last_slot_booking_date,
  tenure_days,
  delivered_orders_cnt,
  booked_slots_cnt,
  days_since_last_slot_booking,
  CASE WHEN tenure_days < 30 THEN 'newbie' ELSE 'active_or_veteran' END AS segment,
  CASE WHEN tenure_days < 30 THEN 7 ELSE 14 END AS churn_threshold_days,
  CASE
    WHEN last_slot_booking_date IS NULL THEN 1
    WHEN tenure_days < 30 AND days_since_last_slot_booking >= 7 THEN 1
    WHEN tenure_days >= 30 AND days_since_last_slot_booking >= 14 THEN 1
    ELSE 0
  END AS is_churned
FROM churn_base;
