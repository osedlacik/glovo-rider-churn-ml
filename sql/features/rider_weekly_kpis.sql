WITH Rider_kpis AS (
  SELECT
    rkpi.country_code,
    city_name,
    rkpi.rider_id,
    vehicle_name,
    batch_number,
    DATE_TRUNC(created_date_local, WEEK(MONDAY)) AS week,
    SUM(rkpi.no_shows)   AS no_shows,
    SUM(rkpi.shifts_done) AS shifts_done,
    SUM(rkpi.all_shifts)  AS all_shifts,
    SUM(working_time) / 60.00 AS hours_worked,
    1.000 * SUM(rkpi.no_shows) / NULLIF(SUM(rkpi.all_shifts), 0) AS perc_no_show
  FROM `fulfillment-dwh-production.curated_data_shared.rider_kpi` AS rkpi
  WHERE rkpi.country_code = 'gv-ci'
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

  SUM(IF(
    (rp.order_final_status != 'cancelled' AND rp.is_dh_data)
    OR (rp.order_final_status = 'DeliveredStatus' AND rp.order_is_standard),
    rp.primary_delivery_count, NULL
  )) AS total_orders_cpo,

  COUNT(DISTINCT CASE
    WHEN (rp.rain_bonus_cost_local_currency + rp.snow_bonus_cost_local_currency) > 0
      AND o.delivery_status = 'completed'
    THEN o.order_id ELSE NULL
  END) AS total_bw_orders,

  SUM(total_compensation_local_currency) AS total_earnings,

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

  SAFE_DIVIDE(
    COUNT(CASE WHEN o.delivery_status = 'completed' AND o.total_stacked_deliveries >= 1 THEN o.delivery_id END),
    COUNT(o.delivery_id)
  ) AS perc_stacking,

  AVG(pickup_distance_google_in_meters)  / 1000 AS avg_sp_distance_google,
  AVG(dropoff_distance_google_in_meters) / 1000 AS avg_pd_distance_google,
  AVG(dropoff_distance_google_in_meters + pickup_distance_google_in_meters) / 1000 AS avg_total_distance_google,

  SAFE_DIVIDE(
    SUM(CASE
      WHEN o.auto_transition_dropoff IS NULL
        AND CAST(o.at_customer_time_in_seconds AS FLOAT64) / 60.00 > 0
      THEN CAST(o.at_customer_time_in_seconds AS FLOAT64) / 60.00
    END),
    COUNT(CASE
      WHEN o.auto_transition_dropoff IS NULL
        AND CAST(o.at_customer_time_in_seconds AS FLOAT64) / 60.00 > 0
      THEN CAST(o.at_customer_time_in_seconds AS FLOAT64) / 60.00
    END)
  ) AS at_customer_time_in_minutes,

  SAFE_DIVIDE(
    SUM(CASE
      WHEN o.rider_near_restaurant_at IS NOT NULL
      THEN CAST(o.at_vendor_time_in_seconds AS FLOAT64) / 60.00
    END),
    COUNT(CASE
      WHEN o.rider_near_restaurant_at IS NOT NULL
      THEN CAST(o.at_vendor_time_in_seconds AS FLOAT64) / 60.00
    END)
  ) AS at_vendor_time_in_minutes,

  SAFE_DIVIDE(
    SUM(courier_delivery_time_in_seconds),
    COUNT(courier_delivery_time_in_seconds)
  ) / 60.00 AS cdt,

  SAFE_DIVIDE(
    SUM(o.total_reassignments),
    SUM(o.total_deliveries)
  ) AS perc_reas,

  SAFE_DIVIDE(
    SUM(rp.total_compensation_local_currency),
    AVG(rkpi.hours_worked)
  ) AS earning_per_hour,

  AVG(rkpi.no_shows)    AS no_shows,
  AVG(rkpi.shifts_done) AS shifts_done,
  AVG(rkpi.all_shifts)  AS all_shifts,
  AVG(rkpi.hours_worked) AS hours_worked,
  AVG(rkpi.perc_no_show) AS perc_no_show

FROM `fulfillment-dwh-production.curated_data_shared_glovo.logistics_orders__orders` AS o

LEFT JOIN `fulfillment-dwh-production.curated_data_shared_glovo.rider_compensations__payments_order_level` rp
  ON CAST(o.global_order_id AS STRING) = CAST(rp.global_order_id AS STRING)

LEFT JOIN Rider_kpis rkpi
  ON o.rider_id = rkpi.rider_id
 AND rkpi.country_code = o.country_code
 AND rkpi.week = DATE_TRUNC(creation_date_local, WEEK(MONDAY))

WHERE rp.country_code IN ('gv-ci')
  AND creation_date_local >= DATE('2026-01-01')

GROUP BY 1, 2, 3, 4, 5