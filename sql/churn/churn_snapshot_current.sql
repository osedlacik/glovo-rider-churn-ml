-- Fast churn snapshot for correlation matrix (current state per rider)
-- Uses a single pass over recent data — no weekly loop.
-- Poland only, 2026-01-01+

SELECT
  d.rider_id,
  MIN(DATE(d.rider_dropped_off_at))                     AS first_delivery_date,
  MAX(DATE(d.rider_dropped_off_at))                     AS last_delivery_date,
  DATE_DIFF(CURRENT_DATE(), MIN(DATE(d.rider_dropped_off_at)), DAY) AS tenure_days,
  MAX(s.last_slot)                                      AS last_slot_date,
  DATE_DIFF(CURRENT_DATE(), MAX(s.last_slot), DAY)      AS days_since_last_slot,
  CASE WHEN DATE_DIFF(CURRENT_DATE(), MIN(DATE(d.rider_dropped_off_at)), DAY) < 30 THEN 'newbie'
       ELSE 'active_or_veteran' END                     AS segment,
  CASE
    WHEN MAX(s.last_slot) IS NULL THEN 1
    WHEN DATE_DIFF(CURRENT_DATE(), MIN(DATE(d.rider_dropped_off_at)), DAY) < 30
         AND DATE_DIFF(CURRENT_DATE(), MAX(s.last_slot), DAY) >= 7  THEN 1
    WHEN DATE_DIFF(CURRENT_DATE(), MIN(DATE(d.rider_dropped_off_at)), DAY) >= 30
         AND DATE_DIFF(CURRENT_DATE(), MAX(s.last_slot), DAY) >= 14 THEN 1
    ELSE 0
  END                                                   AS is_churned

FROM `fulfillment-dwh-production.curated_data_shared.orders` o,
UNNEST(o.deliveries) d

LEFT JOIN (
  SELECT rider_id, MAX(DATE(shift_start_at)) AS last_slot
  FROM `fulfillment-dwh-production.curated_data_shared.shifts`
  WHERE country_code = 'gv-pl'
    AND created_date >= DATE('2026-01-01')
    AND shift_state IN ('EVALUATED', 'PUBLISHED', 'NO_SHOW', 'NO_SHOW_EXCUSED', 'CANCELLED')
  GROUP BY rider_id
) s ON s.rider_id = d.rider_id

WHERE o.country_code = 'gv-pl'
  AND o.created_date >= DATE('2026-01-01')
  AND d.rider_id IS NOT NULL
  AND d.delivery_status = 'completed'
  AND d.is_primary = TRUE
  AND d.rider_dropped_off_at IS NOT NULL

GROUP BY d.rider_id