-- Prospective weekly churn labels for Poland, 2026-01-01 onward.
--
-- Churn definition (forward-looking):
--   A rider is labeled churned at week T if their NEXT delivery is
--   more than N days away (newbie <30d tenure: N=7, veteran: N=14),
--   or if they have no future deliveries in the data window.
--
--   Weeks within 14 days of CURRENT_DATE are set NULL (right-censored:
--   not enough future data to observe churn yet).
--
-- This definition has real variance and is suitable for ML training.
-- Scans only the orders table - no shifts join needed.

WITH

-- Global first delivery per rider for tenure / newbie classification
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

-- One row per (rider, week) where rider made at least one delivery
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

labeled AS (
  SELECT
    dw.rider_id,
    dw.week,
    fd.first_delivery_date,
    DATE_DIFF(dw.week, fd.first_delivery_date, DAY) AS tenure_days,
    CASE
      WHEN DATE_DIFF(dw.week, fd.first_delivery_date, DAY) < 30
      THEN 'newbie' ELSE 'active_or_veteran'
    END AS segment,
    dw.last_delivery_in_week,
    -- Next delivery week for this rider (NULL = no future deliveries seen)
    LEAD(dw.week) OVER (PARTITION BY dw.rider_id ORDER BY dw.week) AS next_delivery_week,
    -- Days until next delivery (NULL if last week in data)
    DATE_DIFF(
      LEAD(dw.week) OVER (PARTITION BY dw.rider_id ORDER BY dw.week),
      dw.week, DAY
    ) AS days_to_next_delivery
  FROM deliveries_weekly dw
  JOIN first_delivery fd ON fd.rider_id = dw.rider_id
)

SELECT
  rider_id,
  week,
  first_delivery_date,
  tenure_days,
  segment,
  last_delivery_in_week,
  next_delivery_week,
  days_to_next_delivery,
  -- Prospective churn label
  CASE
    -- Too close to today: future not yet observable
    WHEN week >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)              THEN NULL
    -- No future delivery in data window
    WHEN next_delivery_week IS NULL                                       THEN 1
    -- Newbie gap > 7 days
    WHEN tenure_days < 30  AND days_to_next_delivery > 7                 THEN 1
    -- Veteran gap > 14 days
    WHEN tenure_days >= 30 AND days_to_next_delivery > 14                THEN 1
    ELSE 0
  END AS is_churned

FROM labeled
ORDER BY rider_id, week