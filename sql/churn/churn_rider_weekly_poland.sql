-- Efficient weekly churn labels for Poland, 2026-01-01 onward.
--
-- Optimisations vs original:
--   1. No DECLARE - plain SQL, wrappable with LIMIT.
--   2. Deliveries and slots aggregated to WEEKLY level before any join.
--   3. UNION ALL + cumulative MAX window replaces all three non-equi joins
--      (the original eligible_rider_weeks cross-join + two self-joins).
--   4. rider_hire / riders table removed (not needed for churn label).

WITH

-- ── Global first delivery per rider ────────────────────────────────────────
-- Scan from 2021 so tenure is correct for riders who predate 2026.
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

-- ── Weekly delivery summary per rider ──────────────────────────────────────
deliveries_weekly AS (
  SELECT
    d.rider_id,
    DATE_TRUNC(DATE(d.rider_dropped_off_at), WEEK(MONDAY)) AS week,
    MAX(DATE(d.rider_dropped_off_at))                       AS last_delivery_in_week
  FROM `fulfillment-dwh-production.curated_data_shared.orders` o,
  UNNEST(o.deliveries) d
  WHERE o.country_code  = 'gv-pl'
    AND o.created_date >= DATE('2026-01-01')
    AND d.rider_id IS NOT NULL
    AND d.delivery_status = 'completed'
    AND d.is_primary = TRUE
    AND d.rider_dropped_off_at IS NOT NULL
  GROUP BY d.rider_id, week
),

-- ── Weekly slot summary per rider ──────────────────────────────────────────
slots_weekly AS (
  SELECT
    rider_id,
    DATE_TRUNC(DATE(shift_start_at), WEEK(MONDAY)) AS week,
    MAX(DATE(shift_start_at))                       AS last_slot_in_week
  FROM `fulfillment-dwh-production.curated_data_shared.shifts`
  WHERE country_code  = 'gv-pl'
    AND created_date >= DATE('2026-01-01')
    AND rider_id IS NOT NULL
    AND shift_start_at IS NOT NULL
    AND shift_state IN ('EVALUATED','PUBLISHED','NO_SHOW','NO_SHOW_EXCUSED','CANCELLED')
  GROUP BY rider_id, week
),

-- ── Merge delivery + slot weeks into one timeline per rider ─────────────────
-- UNION ALL ensures slot-only weeks are included so the cumulative window
-- can carry forward the last slot date even into delivery-only weeks.
activity_weeks AS (
  SELECT rider_id, week, last_delivery_in_week, NULL AS last_slot_in_week
  FROM deliveries_weekly
  UNION ALL
  SELECT rider_id, week, NULL AS last_delivery_in_week, last_slot_in_week
  FROM slots_weekly
),

-- Collapse duplicate weeks (rider had both delivery and slot in same week)
activity_agg AS (
  SELECT
    rider_id,
    week,
    MAX(last_delivery_in_week) AS last_delivery_in_week,
    MAX(last_slot_in_week)     AS last_slot_in_week
  FROM activity_weeks
  GROUP BY rider_id, week
),

-- ── Cumulative running max – replaces all non-equi joins ───────────────────
rider_weekly AS (
  SELECT
    a.rider_id,
    a.week,
    a.last_delivery_in_week,
    -- Last delivery date seen in any week up to (and including) this week
    MAX(a.last_delivery_in_week) OVER w_cum AS last_delivery_date,
    -- Last slot date seen in any week up to (and including) this week
    MAX(a.last_slot_in_week)     OVER w_cum AS last_slot_date
  FROM activity_agg a
  WINDOW w_cum AS (
    PARTITION BY a.rider_id
    ORDER BY a.week
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
  )
)

-- ── Final output: only weeks where the rider made a delivery ───────────────
SELECT
  rw.rider_id,
  rw.week,
  fd.first_delivery_date,
  DATE_DIFF(rw.week, fd.first_delivery_date, DAY)       AS tenure_days,
  rw.last_delivery_date,
  DATE_TRUNC(rw.last_delivery_date, WEEK(MONDAY))        AS last_active_week,
  rw.last_slot_date,
  DATE_DIFF(rw.week, rw.last_slot_date, DAY)             AS days_since_last_slot,
  CASE WHEN DATE_DIFF(rw.week, fd.first_delivery_date, DAY) < 30
       THEN 'newbie' ELSE 'active_or_veteran' END         AS segment,
  CASE WHEN DATE_DIFF(rw.week, fd.first_delivery_date, DAY) < 30
       THEN 7 ELSE 14 END                                 AS churn_threshold_days,
  CASE
    WHEN rw.last_slot_date IS NULL                                                             THEN 1
    WHEN DATE_DIFF(rw.week, fd.first_delivery_date, DAY) < 30
         AND DATE_DIFF(rw.week, rw.last_slot_date, DAY) >= 7                                  THEN 1
    WHEN DATE_DIFF(rw.week, fd.first_delivery_date, DAY) >= 30
         AND DATE_DIFF(rw.week, rw.last_slot_date, DAY) >= 14                                 THEN 1
    ELSE 0
  END                                                     AS is_churned

FROM rider_weekly rw
JOIN first_delivery fd ON fd.rider_id = rw.rider_id
WHERE rw.last_delivery_in_week IS NOT NULL   -- eligible weeks only (had delivery this week)
ORDER BY rw.rider_id, rw.week