-- Weekly rider-level KPI features for Poland from 2026-01-01
-- Variables: orders, earnings, CPO, distances, stacking, no-shows, times, reassignments
-- Used as input for correlation matrix and ML feature engineering

WITH Rider_kpis AS (
  SELECT
    rkpi.country_code,
    city_name,
    rkpi.rider_id,
    vehicle_name,
    batch_number,
    DATE_TRUNC(created_date_local, WEEK(MONDAY)) AS week,
    SUM(rkpi.no_shows)    AS no_shows,
    SUM(rkpi.shifts_done) AS shifts_done,
    SUM(rkpi.all_shifts)  AS all_shifts,
    1.000 * SUM(rkpi.no_shows) / NULLIF(SUM(rkpi.all_shifts), 0) AS perc_no_show
  FROM `fulfillment-dwh-production.curated_data_shared.rider_kpi` AS rkpi
  WHERE rkpi.country_code = 'gv-pl'
    AND DATE(created_date_local) >= DATE('2026-01-01')
    AND rkpi.rider_id IS NOT NULL
  GROUP BY 1, 2, 3, 4, 5, 6
)

SELECT
  rp.glovo_country_code,
  rp.city_code,
  o.zone_name,
  o.rider_id,
  DATE_TRUNC(creation_date_local, WEEK(MONDAY)) AS week,

  -- Shift behaviour (from rider_kpi CTE)
  MAX(rkpi.no_shows)      AS no_shows,
  MAX(rkpi.shifts_done)   AS shifts_done,
  MAX(rkpi.all_shifts)    AS all_shifts,
  MAX(rkpi.perc_no_show)  AS perc_no_show,

  -- Order volume
  SUM(
    IF(
      (rp.order_final_status != 'cancelled' AND rp.is_dh_data)
      OR (rp.order_final_status = 'DeliveredStatus' AND rp.order_is_standard),
      rp.primary_delivery_count,
      NULL
    )
  ) AS total_orders_cpo,

  -- Bad-weather orders
  COUNT(DISTINCT
    CASE WHEN (rp.rain_bonus_cost_local_currency + rp.snow_bonus_cost_local_currency) > 0
              AND o.delivery_status = 'completed'
         THEN o.order_id
         ELSE NULL
    END
  ) AS total_bw_orders,

  -- Earnings
  SUM(total_compensation_local_currency) AS earning_per_week,

  SAFE_DIVIDE(
    SUM(total_compensation_local_currency),
    SUM(IF(
      (rp.order_final_status != 'cancelled' AND rp.is_dh_data)
      OR (rp.order_final_status = 'DeliveredStatus' AND rp.order_is_standard),
      rp.primary_delivery_count, NULL
    ))
  ) AS cpo_local_currency,

  SAFE_DIVIDE(
    SUM(rp.total_compensation_local_currency
        - rp.rain_bonus_cost_local_currency
        - rp.snow_bonus_cost_local_currency),
    SUM(IF(
      (rp.order_final_status != 'cancelled' AND rp.is_dh_data)
      OR (rp.order_final_status = 'DeliveredStatus' AND rp.order_is_standard),
      rp.primary_delivery_count, NULL
    ))
  ) AS net_cpo_lc,

  -- Stacking
  SAFE_DIVIDE(
    COUNT(CASE WHEN o.delivery_status = 'completed'
                    AND o.total_stacked_deliveries >= 1 THEN o.delivery_id END),
    COUNT(o.delivery_id)
  ) AS perc_stacking,

  -- Distances (km)
  AVG(pickup_distance_google_in_meters)  / 1000 AS avg_sp_distance_km,
  AVG(dropoff_distance_google_in_meters) / 1000 AS avg_pd_distance_km,
  AVG(dropoff_distance_google_in_meters + pickup_distance_google_in_meters) / 1000 AS avg_total_distance_km,

  -- Time at customer (minutes, manual transitions only)
  SAFE_DIVIDE(
    SUM(CASE WHEN o.auto_transition_dropoff IS NULL
                  AND CAST(o.at_customer_time_in_seconds AS FLOAT64) / 60.0 > 0
             THEN CAST(o.at_customer_time_in_seconds AS FLOAT64) / 60.0 END),
    COUNT(CASE WHEN o.auto_transition_dropoff IS NULL
                    AND CAST(o.at_customer_time_in_seconds AS FLOAT64) / 60.0 > 0
               THEN 1 END)
  ) AS at_customer_time_min,

  -- Time at vendor (minutes, only when near-restaurant triggered)
  SAFE_DIVIDE(
    SUM(CASE WHEN o.rider_near_restaurant_at IS NOT NULL
             THEN CAST(o.at_vendor_time_in_seconds AS FLOAT64) / 60.0 END),
    COUNT(CASE WHEN o.rider_near_restaurant_at IS NOT NULL THEN 1 END)
  ) AS at_vendor_time_min,

  -- Courier delivery time (minutes)
  SAFE_DIVIDE(
    SUM(o.courier_delivery_time_in_seconds),
    COUNT(o.courier_delivery_time_in_seconds)
  ) / 60.0 AS cdt_min,

  -- Reassignment rate
  SAFE_DIVIDE(
    SUM(o.total_reassignments),
    SUM(o.total_deliveries)
  ) AS perc_reassignments

FROM `fulfillment-dwh-production.curated_data_shared_glovo.logistics_orders__orders` AS o

LEFT JOIN `fulfillment-dwh-production.curated_data_shared_glovo.rider_compensations__payments_order_level` rp
  ON CAST(o.global_order_id AS STRING) = CAST(rp.global_order_id AS STRING)

LEFT JOIN Rider_kpis rkpi
  ON o.rider_id = rkpi.rider_id
 AND rkpi.country_code = o.country_code
 AND rkpi.week = DATE_TRUNC(creation_date_local, WEEK(MONDAY))

WHERE rp.country_code = 'gv-pl'
  AND creation_date_local >= DATE('2026-01-01')

GROUP BY 1, 2, 3, 4, 5
ORDER BY 1, 2, 3, 4, 5
