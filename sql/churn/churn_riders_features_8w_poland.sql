-- =============================================================================
-- Riders Feature Table (8 Weeks) — Poland
-- =============================================================================
-- One row per eligible rider.
-- For churned riders, W0 = week_of_churn.
-- For non-churned riders, W0 = current week (DATE_TRUNC(timeframe_end, WEEK(MONDAY))).
-- W1 = 1 week before W0, ..., W7 = 7 weeks before W0.
--
-- Stable columns (single value per rider):
--   rider_id, glovo_country_code, city_code, zone_name, vehicle_name,
--   segment, first_order_date, last_order_date, week_of_churn, anchor_week, utm_source
--
-- Evolving weekly columns (_W0 ... _W7):
--   batch_number,
--   total_orders_cpo, total_bw_orders, total_earnings, cpo_local_currency,
--   net_cpo_lc, perc_stacking, avg_sp_distance_google, avg_pd_distance_google,
--   at_customer_time_in_minutes, at_vendor_time_in_minutes, cdt, perc_reas,
--   no_shows, shifts_done, all_shifts, hours_worked,
--   contacts_total_tickets, avg_sat_score,
--   compliance_total_violations, compliance_distinct_violation_types,
--   earnings_per_hour, city_median_earnings_per_hour,
--   earnings_vs_city_median_abs, earnings_vs_city_median_ratio,
--   slot_gap_mean_days, slot_gap_max_days,
--   holiday_days_in_week
-- =============================================================================

DECLARE timeframe_start DATE DEFAULT DATE('2026-01-01');
DECLARE timeframe_end DATE DEFAULT CURRENT_DATE();

WITH eligible_riders AS (
  SELECT DISTINCT CAST(d.rider_id AS STRING) AS rider_id
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

rider_attrs AS (
  SELECT
    CAST(rider_id AS STRING) AS rider_id,
    DATE(first_order_creation_datetime) AS first_order_date,
    DATE(last_order_creation_datetime) AS last_order_date
  FROM `fulfillment-dwh-production.curated_data_shared_glovo.rider_attributes__rider_attributes`
),

last_slot AS (
  SELECT
    CAST(s.rider_id AS STRING) AS rider_id,
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

churned_riders AS (
  SELECT
    er.rider_id,
    CASE
      WHEN DATE_DIFF(timeframe_end, ra.first_order_date, DAY) < 30 THEN 'newbie'
      ELSE 'active'
    END AS segment,
    CASE
      WHEN ls.last_slot_date IS NULL THEN DATE_TRUNC(ra.first_order_date, WEEK(MONDAY))
      WHEN DATE_DIFF(timeframe_end, ls.last_slot_date, DAY) >= 14 THEN DATE_TRUNC(ls.last_slot_date, WEEK(MONDAY))
      ELSE NULL
    END AS week_of_churn
  FROM eligible_riders er
  JOIN rider_attrs ra ON ra.rider_id = er.rider_id
  LEFT JOIN last_slot ls ON ls.rider_id = er.rider_id
  WHERE ls.last_slot_date IS NULL
     OR DATE_DIFF(timeframe_end, ls.last_slot_date, DAY) >= 14
),

rider_anchor AS (
  SELECT
    er.rider_id,
    CASE
      WHEN DATE_DIFF(timeframe_end, ra.first_order_date, DAY) < 30 THEN 'newbie'
      ELSE 'active'
    END AS segment,
    c.week_of_churn,
    COALESCE(c.week_of_churn, DATE_TRUNC(timeframe_end, WEEK(MONDAY))) AS anchor_week
  FROM eligible_riders er
  JOIN rider_attrs ra ON ra.rider_id = er.rider_id
  LEFT JOIN churned_riders c ON c.rider_id = er.rider_id
),

rider_weeks AS (
  SELECT
    a.rider_id,
    a.segment,
    a.week_of_churn,
    wk AS week_offset,
    DATE_SUB(a.anchor_week, INTERVAL wk WEEK) AS feature_week
  FROM rider_anchor a
  CROSS JOIN UNNEST(GENERATE_ARRAY(0, 7)) AS wk
),

slot_gap_weekly AS (
  WITH shifts_clean AS (
    SELECT
      CAST(s.rider_id AS STRING) AS rider_id,
      DATE(s.shift_start_at) AS shift_date,
      DATE_TRUNC(DATE(s.shift_start_at), WEEK(MONDAY)) AS week
    FROM `fulfillment-dwh-production.curated_data_shared.shifts` s
    WHERE s.country_code = 'gv-pl'
      AND s.rider_id IS NOT NULL
      AND s.shift_start_at IS NOT NULL
      AND DATE(s.shift_start_at) >= DATE_SUB(timeframe_start, INTERVAL 16 WEEK)
      AND DATE(s.shift_start_at) <= timeframe_end
      AND s.shift_state IN ('EVALUATED', 'PUBLISHED', 'NO_SHOW', 'NO_SHOW_EXCUSED', 'CANCELLED')
        AND CAST(s.rider_id AS STRING) IN (SELECT rider_id FROM eligible_riders)
  ),
  shifts_with_prev AS (
    SELECT
      rider_id,
      week,
      shift_date,
      LAG(shift_date) OVER (PARTITION BY rider_id ORDER BY shift_date) AS prev_shift_date
    FROM shifts_clean
  )
  SELECT
    rider_id,
    week,
    AVG(DATE_DIFF(shift_date, prev_shift_date, DAY)) AS slot_gap_mean_days,
    MAX(DATE_DIFF(shift_date, prev_shift_date, DAY)) AS slot_gap_max_days
  FROM shifts_with_prev
  WHERE prev_shift_date IS NOT NULL
  GROUP BY 1, 2
),

rider_kpis_weekly AS (
  SELECT
    CAST(rkpi.rider_id AS STRING) AS rider_id,
    'GV_PL' AS glovo_country_code,
    ANY_VALUE(rkpi.city_name) AS city_name,
    ANY_VALUE(rkpi.vehicle_name) AS vehicle_name,
    MAX(rkpi.batch_number) AS batch_number,
    DATE_TRUNC(DATE(rkpi.created_date_local), WEEK(MONDAY)) AS week,
    SUM(rkpi.no_shows) AS no_shows,
    SUM(rkpi.shifts_done) AS shifts_done,
    SUM(rkpi.all_shifts) AS all_shifts,
    SUM(rkpi.working_time) / 3600.0 AS hours_worked,
    SAFE_DIVIDE(SUM(rkpi.no_shows), SUM(rkpi.all_shifts)) AS perc_no_show
  FROM `fulfillment-dwh-production.curated_data_shared.rider_kpi` rkpi
  WHERE rkpi.country_code = 'gv-pl'
    AND DATE(rkpi.created_date_local) >= DATE_SUB(timeframe_start, INTERVAL 8 WEEK)
    AND DATE(rkpi.created_date_local) <= timeframe_end
    AND rkpi.rider_id IS NOT NULL
    AND CAST(rkpi.rider_id AS STRING) IN (SELECT rider_id FROM eligible_riders)
  GROUP BY 1, 2, 6
),

weekly_delivery_kpis AS (
  SELECT
    CAST(o.rider_id AS STRING) AS rider_id,
    'GV_PL' AS glovo_country_code,
    ANY_VALUE(rp.city_code) AS city_code,
    ANY_VALUE(o.zone_name) AS zone_name,
    DATE_TRUNC(DATE(o.report_date), WEEK(MONDAY)) AS week,

    SUM(IF(
      (rp.order_final_status != 'cancelled' AND rp.is_dh_data)
      OR (rp.order_final_status = 'DeliveredStatus' AND rp.order_is_standard),
      rp.primary_delivery_count,
      NULL
    )) AS total_orders_cpo,

    COUNT(DISTINCT CASE
      WHEN (rp.rain_bonus_cost_local_currency + rp.snow_bonus_cost_local_currency) > 0
        AND o.delivery_status = 'completed'
      THEN o.order_id
      ELSE NULL
    END) AS total_bw_orders,

    SUM(rp.total_compensation_local_currency) AS total_earnings,

    SAFE_DIVIDE(
      SUM(rp.total_compensation_local_currency),
      SUM(IF(
        (rp.order_final_status != 'cancelled' AND rp.is_dh_data)
        OR (rp.order_final_status = 'DeliveredStatus' AND rp.order_is_standard),
        rp.primary_delivery_count,
        NULL
      ))
    ) AS cpo_local_currency,

    SAFE_DIVIDE(
      SUM(
        rp.total_compensation_local_currency
        - rp.rain_bonus_cost_local_currency
        - rp.snow_bonus_cost_local_currency
      ),
      SUM(IF(
        (rp.order_final_status != 'cancelled' AND rp.is_dh_data)
        OR (rp.order_final_status = 'DeliveredStatus' AND rp.order_is_standard),
        rp.primary_delivery_count,
        NULL
      ))
    ) AS net_cpo_lc,

    SAFE_DIVIDE(
      COUNT(CASE
        WHEN o.delivery_status = 'completed' AND o.total_stacked_deliveries >= 1 THEN o.delivery_id
      END),
      COUNT(o.delivery_id)
    ) AS perc_stacking,

    AVG(o.pickup_distance_google_in_meters) / 1000.0 AS avg_sp_distance_google,
    AVG(o.dropoff_distance_google_in_meters) / 1000.0 AS avg_pd_distance_google,
    AVG(o.dropoff_distance_google_in_meters + o.pickup_distance_google_in_meters) / 1000.0 AS avg_total_distance_google,

    SAFE_DIVIDE(
      SUM(CASE
        WHEN o.auto_transition_dropoff IS NULL
          AND CAST(o.at_customer_time_in_seconds AS FLOAT64) / 60.0 > 0
        THEN CAST(o.at_customer_time_in_seconds AS FLOAT64) / 60.0
      END),
      COUNT(CASE
        WHEN o.auto_transition_dropoff IS NULL
          AND CAST(o.at_customer_time_in_seconds AS FLOAT64) / 60.0 > 0
        THEN 1
      END)
    ) AS at_customer_time_in_minutes,

    SAFE_DIVIDE(
      SUM(CASE
        WHEN o.rider_near_restaurant_at IS NOT NULL
        THEN CAST(o.at_vendor_time_in_seconds AS FLOAT64) / 60.0
      END),
      COUNT(CASE
        WHEN o.rider_near_restaurant_at IS NOT NULL THEN 1
      END)
    ) AS at_vendor_time_in_minutes,

    SAFE_DIVIDE(
      SUM(o.courier_delivery_time_in_seconds),
      COUNT(o.courier_delivery_time_in_seconds)
    ) / 60.0 AS cdt,

    SAFE_DIVIDE(
      SUM(o.total_reassignments),
      SUM(o.total_deliveries)
    ) AS perc_reas

  FROM `fulfillment-dwh-production.curated_data_shared_glovo.logistics_orders__orders` o
  LEFT JOIN `fulfillment-dwh-production.curated_data_shared_glovo.rider_compensations__payments_order_level` rp
    ON CAST(o.global_order_id AS STRING) = CAST(rp.global_order_id AS STRING)
  WHERE rp.country_code = 'gv-pl'
    AND o.country_code = 'gv-pl'
    AND DATE(o.report_date) >= DATE_SUB(timeframe_start, INTERVAL 8 WEEK)
    AND DATE(o.report_date) <= timeframe_end
    AND o.rider_id IS NOT NULL
    AND CAST(o.rider_id AS STRING) IN (SELECT rider_id FROM eligible_riders)
  GROUP BY 1, 5
),

contacts_weekly AS (
  SELECT
    CAST(ce.stakeholder_id AS STRING) AS rider_id,
    DATE_TRUNC(DATE(ce.creation_timestamp), WEEK(MONDAY)) AS week,
    COUNT(*) AS contacts_total_tickets,
    AVG(ce.sat_score) AS avg_sat_score
  FROM `fulfillment-dwh-production.curated_data_shared_glovo.contacts_extended__contacts_extended` ce
  WHERE ce.country_code = 'PL'
    AND ce.sat_score IS NOT NULL
    AND ce.stakeholder_id IS NOT NULL
    AND DATE(ce.creation_timestamp) >= DATE_SUB(timeframe_start, INTERVAL 8 WEEK)
    AND DATE(ce.creation_timestamp) <= timeframe_end
    AND CAST(ce.stakeholder_id AS STRING) IN (SELECT rider_id FROM eligible_riders)
  GROUP BY 1, 2
),

compliance_weekly AS (
  SELECT
    CAST(rider_id AS STRING) AS rider_id,
    DATE_TRUNC(DATE(created_at), WEEK(MONDAY)) AS week,
    COUNT(DISTINCT v.id) AS compliance_total_violations,
    COUNT(DISTINCT r.violation_type) AS compliance_distinct_violation_types
  FROM `fulfillment-dwh-production.curated_data_shared.rider_compliance`,
  UNNEST(violations) v,
  UNNEST(v.actions) a,
  UNNEST(v.rules) r
  WHERE country_code = 'gv-pl'
    AND DATE(created_date) >= DATE_SUB(timeframe_start, INTERVAL 8 WEEK)
    AND DATE(created_date) <= timeframe_end
    AND CAST(rider_id AS STRING) IN (SELECT rider_id FROM eligible_riders)
  GROUP BY 1, 2
),

applicant_source AS (
  SELECT
    CAST(rider_id AS STRING) AS rider_id,
    MIN(DATE(created_at)) AS registration_date,
    ARRAY_AGG(
      custom_non_pii_fields.utm.source
      ORDER BY created_at DESC
      LIMIT 1
    )[SAFE_OFFSET(0)] AS utm_source
  FROM `fulfillment-dwh-production.curated_data_shared.applicants`
  WHERE country_code = 'PL'
    AND rider_id IS NOT NULL
  GROUP BY rider_id
),

city_weekly_benchmarks AS (
  SELECT
    city_code,
    week,
    APPROX_QUANTILES(SAFE_DIVIDE(total_earnings, NULLIF(hours_worked, 0)), 100)[OFFSET(50)] AS city_median_earnings_per_hour,
    AVG(total_earnings) AS city_avg_total_earnings
  FROM (
    SELECT
      d.city_code,
      d.week,
      d.rider_id,
      d.total_earnings,
      k.hours_worked
    FROM weekly_delivery_kpis d
    LEFT JOIN rider_kpis_weekly k
      ON k.rider_id = d.rider_id
     AND k.week = d.week
    WHERE d.city_code IS NOT NULL
  )
  GROUP BY 1, 2
),

polish_holidays AS (
  SELECT holiday_date, holiday_name FROM UNNEST([
    STRUCT(DATE '2025-11-01' AS holiday_date, 'All Saints Day' AS holiday_name),
    STRUCT(DATE '2025-11-11' AS holiday_date, 'Independence Day' AS holiday_name),
    STRUCT(DATE '2025-12-25' AS holiday_date, 'Christmas Day' AS holiday_name),
    STRUCT(DATE '2025-12-26' AS holiday_date, 'Second Day of Christmas' AS holiday_name),
    STRUCT(DATE '2026-01-01' AS holiday_date, 'New Year Day' AS holiday_name),
    STRUCT(DATE '2026-01-06' AS holiday_date, 'Epiphany' AS holiday_name),
    STRUCT(DATE '2026-04-05' AS holiday_date, 'Easter Sunday' AS holiday_name),
    STRUCT(DATE '2026-04-06' AS holiday_date, 'Easter Monday' AS holiday_name),
    STRUCT(DATE '2026-05-01' AS holiday_date, 'Labour Day' AS holiday_name),
    STRUCT(DATE '2026-05-03' AS holiday_date, 'Constitution Day' AS holiday_name),
    STRUCT(DATE '2026-05-24' AS holiday_date, 'Pentecost' AS holiday_name),
    STRUCT(DATE '2026-06-04' AS holiday_date, 'Corpus Christi' AS holiday_name),
    STRUCT(DATE '2026-08-15' AS holiday_date, 'Assumption Day' AS holiday_name),
    STRUCT(DATE '2026-11-01' AS holiday_date, 'All Saints Day' AS holiday_name),
    STRUCT(DATE '2026-11-11' AS holiday_date, 'Independence Day' AS holiday_name),
    STRUCT(DATE '2026-12-25' AS holiday_date, 'Christmas Day' AS holiday_name),
    STRUCT(DATE '2026-12-26' AS holiday_date, 'Second Day of Christmas' AS holiday_name)
  ])
),

holiday_weekly AS (
  SELECT
    DATE_TRUNC(holiday_date, WEEK(MONDAY)) AS week,
    COUNT(*) AS holiday_days_in_week
  FROM polish_holidays
  GROUP BY 1
),

newbie_early_features AS (
  WITH first_order AS (
    SELECT
      ra.rider_id,
      ra.first_order_date,
      DATE_TRUNC(ra.first_order_date, WEEK(MONDAY)) AS first_order_week
    FROM rider_attrs ra
    JOIN rider_anchor a ON a.rider_id = ra.rider_id
    WHERE a.segment = 'newbie'
      AND ra.first_order_date IS NOT NULL
  ),
  orders_after_first AS (
    SELECT
      fo.rider_id,
      COUNTIF(DATE_DIFF(DATE(d.rider_dropped_off_at), fo.first_order_date, DAY) BETWEEN 0 AND 6) AS orders_first_7d,
      COUNTIF(DATE_DIFF(DATE(d.rider_dropped_off_at), fo.first_order_date, DAY) BETWEEN 0 AND 29) AS orders_first_30d
    FROM first_order fo
    JOIN `fulfillment-dwh-production.curated_data_shared.orders` o
      ON o.country_code = 'gv-pl'
     AND o.created_date >= DATE_SUB(timeframe_end, INTERVAL 60 DAY)
     AND o.created_date <= timeframe_end
    CROSS JOIN UNNEST(o.deliveries) d
    WHERE d.delivery_status = 'completed'
      AND d.is_primary = TRUE
      AND d.rider_dropped_off_at IS NOT NULL
      AND CAST(d.rider_id AS STRING) = fo.rider_id
    GROUP BY 1
  ),
  compliance_30d AS (
    SELECT
      fo.rider_id,
      COUNT(DISTINCT v.id) AS compliance_events_first_30d
    FROM first_order fo
    LEFT JOIN `fulfillment-dwh-production.curated_data_shared.rider_compliance` rc
      ON CAST(rc.rider_id AS STRING) = fo.rider_id
     AND rc.country_code = 'gv-pl'
     AND DATE(rc.created_date) BETWEEN fo.first_order_date AND DATE_ADD(fo.first_order_date, INTERVAL 29 DAY)
    LEFT JOIN UNNEST(rc.violations) v
    GROUP BY 1
  ),
  first_week_earnings AS (
    SELECT
      fo.rider_id,
      SUM(d.total_earnings) AS first_week_earnings,
      AVG(cb.city_avg_total_earnings) AS city_avg_earnings_first_week
    FROM first_order fo
    LEFT JOIN weekly_delivery_kpis d
      ON d.rider_id = fo.rider_id
     AND d.week = fo.first_order_week
    LEFT JOIN city_weekly_benchmarks cb
      ON cb.city_code = d.city_code
     AND cb.week = d.week
    GROUP BY 1
  )
  SELECT
    fo.rider_id,
    fo.first_order_date,
    apl.registration_date,
    DATE_DIFF(fo.first_order_date, apl.registration_date, DAY) AS days_registration_to_first_order,
    o.orders_first_7d,
    o.orders_first_30d,
    c.compliance_events_first_30d,
    fwe.first_week_earnings,
    fwe.city_avg_earnings_first_week,
    SAFE_DIVIDE(fwe.first_week_earnings, NULLIF(fwe.city_avg_earnings_first_week, 0)) AS first_week_earnings_vs_city_avg_ratio
  FROM first_order fo
  LEFT JOIN applicant_source apl ON apl.rider_id = fo.rider_id
  LEFT JOIN orders_after_first o ON o.rider_id = fo.rider_id
  LEFT JOIN compliance_30d c ON c.rider_id = fo.rider_id
  LEFT JOIN first_week_earnings fwe ON fwe.rider_id = fo.rider_id
),

weekly_combined AS (
  SELECT
    crw.rider_id,
    crw.segment,
    crw.week_of_churn,
    crw.week_offset,
    crw.feature_week,

    'GV_PL' AS glovo_country_code,
    COALESCE(d.city_code, k.city_name) AS city_code,
    d.zone_name,
    k.vehicle_name,
    k.batch_number,

    d.total_orders_cpo,
    d.total_bw_orders,
    d.total_earnings,
    d.cpo_local_currency,
    d.net_cpo_lc,
    d.perc_stacking,
    d.avg_sp_distance_google,
    d.avg_pd_distance_google,
    d.at_customer_time_in_minutes,
    d.at_vendor_time_in_minutes,
    d.cdt,
    d.perc_reas,
    d.avg_total_distance_google,

    k.no_shows,
    k.shifts_done,
    k.all_shifts,
    k.hours_worked,
    k.perc_no_show,

    c.contacts_total_tickets,
    c.avg_sat_score,
    comp.compliance_total_violations,
    comp.compliance_distinct_violation_types,

    SAFE_DIVIDE(d.total_earnings, NULLIF(k.hours_worked, 0)) AS earnings_per_hour,
    cb.city_median_earnings_per_hour,
    SAFE_DIVIDE(d.total_earnings, NULLIF(k.hours_worked, 0)) - cb.city_median_earnings_per_hour AS earnings_vs_city_median_abs,
    SAFE_DIVIDE(SAFE_DIVIDE(d.total_earnings, NULLIF(k.hours_worked, 0)), NULLIF(cb.city_median_earnings_per_hour, 0)) AS earnings_vs_city_median_ratio,

    sg.slot_gap_mean_days,
    sg.slot_gap_max_days,
    COALESCE(hw.holiday_days_in_week, 0) AS holiday_days_in_week,

    CASE
      WHEN EXTRACT(MONTH FROM crw.feature_week) IN (12, 1, 2) THEN 'winter'
      WHEN EXTRACT(MONTH FROM crw.feature_week) IN (3, 4, 5) THEN 'spring'
      WHEN EXTRACT(MONTH FROM crw.feature_week) IN (6, 7, 8) THEN 'summer'
      ELSE 'autumn'
    END AS season_name

  FROM rider_weeks crw
  LEFT JOIN weekly_delivery_kpis d
    ON d.rider_id = crw.rider_id
   AND d.week = crw.feature_week
  LEFT JOIN rider_kpis_weekly k
    ON k.rider_id = crw.rider_id
   AND k.week = crw.feature_week
  LEFT JOIN contacts_weekly c
    ON c.rider_id = crw.rider_id
   AND c.week = crw.feature_week
  LEFT JOIN compliance_weekly comp
    ON comp.rider_id = crw.rider_id
   AND comp.week = crw.feature_week
  LEFT JOIN city_weekly_benchmarks cb
    ON cb.city_code = d.city_code
   AND cb.week = crw.feature_week
  LEFT JOIN slot_gap_weekly sg
    ON sg.rider_id = crw.rider_id
   AND sg.week = crw.feature_week
  LEFT JOIN holiday_weekly hw
    ON hw.week = crw.feature_week
)

SELECT
  wc.rider_id,
  COALESCE(
    MAX(IF(wc.week_offset = 0, wc.glovo_country_code, NULL)),
    MAX(wc.glovo_country_code)
  ) AS glovo_country_code,
  COALESCE(
    MAX(IF(wc.week_offset = 0, wc.city_code, NULL)),
    MAX(wc.city_code)
  ) AS city_code,
  COALESCE(
    MAX(IF(wc.week_offset = 0, wc.zone_name, NULL)),
    MAX(wc.zone_name)
  ) AS zone_name,
  COALESCE(
    MAX(IF(wc.week_offset = 0, wc.vehicle_name, NULL)),
    MAX(wc.vehicle_name)
  ) AS vehicle_name,
  MAX(wc.segment) AS segment,
  MAX(ra.first_order_date) AS first_order_date,
  MAX(ra.last_order_date) AS last_order_date,
  MAX(wc.week_of_churn) AS week_of_churn,
  MAX(IF(wc.week_offset = 0, wc.feature_week, NULL)) AS anchor_week,
  MAX(apl.utm_source) AS utm_source,

  MAX(IF(wc.week_offset = 0, wc.batch_number, NULL)) AS batch_number_W0,
  MAX(IF(wc.week_offset = 1, wc.batch_number, NULL)) AS batch_number_W1,
  MAX(IF(wc.week_offset = 2, wc.batch_number, NULL)) AS batch_number_W2,
  MAX(IF(wc.week_offset = 3, wc.batch_number, NULL)) AS batch_number_W3,
  MAX(IF(wc.week_offset = 4, wc.batch_number, NULL)) AS batch_number_W4,
  MAX(IF(wc.week_offset = 5, wc.batch_number, NULL)) AS batch_number_W5,
  MAX(IF(wc.week_offset = 6, wc.batch_number, NULL)) AS batch_number_W6,
  MAX(IF(wc.week_offset = 7, wc.batch_number, NULL)) AS batch_number_W7,

  MAX(IF(wc.week_offset = 0, wc.total_orders_cpo, NULL)) AS total_orders_cpo_W0,
  MAX(IF(wc.week_offset = 1, wc.total_orders_cpo, NULL)) AS total_orders_cpo_W1,
  MAX(IF(wc.week_offset = 2, wc.total_orders_cpo, NULL)) AS total_orders_cpo_W2,
  MAX(IF(wc.week_offset = 3, wc.total_orders_cpo, NULL)) AS total_orders_cpo_W3,
  MAX(IF(wc.week_offset = 4, wc.total_orders_cpo, NULL)) AS total_orders_cpo_W4,
  MAX(IF(wc.week_offset = 5, wc.total_orders_cpo, NULL)) AS total_orders_cpo_W5,
  MAX(IF(wc.week_offset = 6, wc.total_orders_cpo, NULL)) AS total_orders_cpo_W6,
  MAX(IF(wc.week_offset = 7, wc.total_orders_cpo, NULL)) AS total_orders_cpo_W7,

  MAX(IF(wc.week_offset = 0, wc.total_bw_orders, NULL)) AS total_bw_orders_W0,
  MAX(IF(wc.week_offset = 1, wc.total_bw_orders, NULL)) AS total_bw_orders_W1,
  MAX(IF(wc.week_offset = 2, wc.total_bw_orders, NULL)) AS total_bw_orders_W2,
  MAX(IF(wc.week_offset = 3, wc.total_bw_orders, NULL)) AS total_bw_orders_W3,
  MAX(IF(wc.week_offset = 4, wc.total_bw_orders, NULL)) AS total_bw_orders_W4,
  MAX(IF(wc.week_offset = 5, wc.total_bw_orders, NULL)) AS total_bw_orders_W5,
  MAX(IF(wc.week_offset = 6, wc.total_bw_orders, NULL)) AS total_bw_orders_W6,
  MAX(IF(wc.week_offset = 7, wc.total_bw_orders, NULL)) AS total_bw_orders_W7,

  MAX(IF(wc.week_offset = 0, wc.total_earnings, NULL)) AS total_earnings_W0,
  MAX(IF(wc.week_offset = 1, wc.total_earnings, NULL)) AS total_earnings_W1,
  MAX(IF(wc.week_offset = 2, wc.total_earnings, NULL)) AS total_earnings_W2,
  MAX(IF(wc.week_offset = 3, wc.total_earnings, NULL)) AS total_earnings_W3,
  MAX(IF(wc.week_offset = 4, wc.total_earnings, NULL)) AS total_earnings_W4,
  MAX(IF(wc.week_offset = 5, wc.total_earnings, NULL)) AS total_earnings_W5,
  MAX(IF(wc.week_offset = 6, wc.total_earnings, NULL)) AS total_earnings_W6,
  MAX(IF(wc.week_offset = 7, wc.total_earnings, NULL)) AS total_earnings_W7,

  MAX(IF(wc.week_offset = 0, wc.cpo_local_currency, NULL)) AS cpo_local_currency_W0,
  MAX(IF(wc.week_offset = 1, wc.cpo_local_currency, NULL)) AS cpo_local_currency_W1,
  MAX(IF(wc.week_offset = 2, wc.cpo_local_currency, NULL)) AS cpo_local_currency_W2,
  MAX(IF(wc.week_offset = 3, wc.cpo_local_currency, NULL)) AS cpo_local_currency_W3,
  MAX(IF(wc.week_offset = 4, wc.cpo_local_currency, NULL)) AS cpo_local_currency_W4,
  MAX(IF(wc.week_offset = 5, wc.cpo_local_currency, NULL)) AS cpo_local_currency_W5,
  MAX(IF(wc.week_offset = 6, wc.cpo_local_currency, NULL)) AS cpo_local_currency_W6,
  MAX(IF(wc.week_offset = 7, wc.cpo_local_currency, NULL)) AS cpo_local_currency_W7,

  MAX(IF(wc.week_offset = 0, wc.net_cpo_lc, NULL)) AS net_cpo_lc_W0,
  MAX(IF(wc.week_offset = 1, wc.net_cpo_lc, NULL)) AS net_cpo_lc_W1,
  MAX(IF(wc.week_offset = 2, wc.net_cpo_lc, NULL)) AS net_cpo_lc_W2,
  MAX(IF(wc.week_offset = 3, wc.net_cpo_lc, NULL)) AS net_cpo_lc_W3,
  MAX(IF(wc.week_offset = 4, wc.net_cpo_lc, NULL)) AS net_cpo_lc_W4,
  MAX(IF(wc.week_offset = 5, wc.net_cpo_lc, NULL)) AS net_cpo_lc_W5,
  MAX(IF(wc.week_offset = 6, wc.net_cpo_lc, NULL)) AS net_cpo_lc_W6,
  MAX(IF(wc.week_offset = 7, wc.net_cpo_lc, NULL)) AS net_cpo_lc_W7,

  MAX(IF(wc.week_offset = 0, wc.perc_stacking, NULL)) AS perc_stacking_W0,
  MAX(IF(wc.week_offset = 1, wc.perc_stacking, NULL)) AS perc_stacking_W1,
  MAX(IF(wc.week_offset = 2, wc.perc_stacking, NULL)) AS perc_stacking_W2,
  MAX(IF(wc.week_offset = 3, wc.perc_stacking, NULL)) AS perc_stacking_W3,
  MAX(IF(wc.week_offset = 4, wc.perc_stacking, NULL)) AS perc_stacking_W4,
  MAX(IF(wc.week_offset = 5, wc.perc_stacking, NULL)) AS perc_stacking_W5,
  MAX(IF(wc.week_offset = 6, wc.perc_stacking, NULL)) AS perc_stacking_W6,
  MAX(IF(wc.week_offset = 7, wc.perc_stacking, NULL)) AS perc_stacking_W7,

  MAX(IF(wc.week_offset = 0, wc.avg_sp_distance_google, NULL)) AS avg_sp_distance_google_W0,
  MAX(IF(wc.week_offset = 1, wc.avg_sp_distance_google, NULL)) AS avg_sp_distance_google_W1,
  MAX(IF(wc.week_offset = 2, wc.avg_sp_distance_google, NULL)) AS avg_sp_distance_google_W2,
  MAX(IF(wc.week_offset = 3, wc.avg_sp_distance_google, NULL)) AS avg_sp_distance_google_W3,
  MAX(IF(wc.week_offset = 4, wc.avg_sp_distance_google, NULL)) AS avg_sp_distance_google_W4,
  MAX(IF(wc.week_offset = 5, wc.avg_sp_distance_google, NULL)) AS avg_sp_distance_google_W5,
  MAX(IF(wc.week_offset = 6, wc.avg_sp_distance_google, NULL)) AS avg_sp_distance_google_W6,
  MAX(IF(wc.week_offset = 7, wc.avg_sp_distance_google, NULL)) AS avg_sp_distance_google_W7,

  MAX(IF(wc.week_offset = 0, wc.avg_pd_distance_google, NULL)) AS avg_pd_distance_google_W0,
  MAX(IF(wc.week_offset = 1, wc.avg_pd_distance_google, NULL)) AS avg_pd_distance_google_W1,
  MAX(IF(wc.week_offset = 2, wc.avg_pd_distance_google, NULL)) AS avg_pd_distance_google_W2,
  MAX(IF(wc.week_offset = 3, wc.avg_pd_distance_google, NULL)) AS avg_pd_distance_google_W3,
  MAX(IF(wc.week_offset = 4, wc.avg_pd_distance_google, NULL)) AS avg_pd_distance_google_W4,
  MAX(IF(wc.week_offset = 5, wc.avg_pd_distance_google, NULL)) AS avg_pd_distance_google_W5,
  MAX(IF(wc.week_offset = 6, wc.avg_pd_distance_google, NULL)) AS avg_pd_distance_google_W6,
  MAX(IF(wc.week_offset = 7, wc.avg_pd_distance_google, NULL)) AS avg_pd_distance_google_W7,

  MAX(IF(wc.week_offset = 0, wc.at_customer_time_in_minutes, NULL)) AS at_customer_time_in_minutes_W0,
  MAX(IF(wc.week_offset = 1, wc.at_customer_time_in_minutes, NULL)) AS at_customer_time_in_minutes_W1,
  MAX(IF(wc.week_offset = 2, wc.at_customer_time_in_minutes, NULL)) AS at_customer_time_in_minutes_W2,
  MAX(IF(wc.week_offset = 3, wc.at_customer_time_in_minutes, NULL)) AS at_customer_time_in_minutes_W3,
  MAX(IF(wc.week_offset = 4, wc.at_customer_time_in_minutes, NULL)) AS at_customer_time_in_minutes_W4,
  MAX(IF(wc.week_offset = 5, wc.at_customer_time_in_minutes, NULL)) AS at_customer_time_in_minutes_W5,
  MAX(IF(wc.week_offset = 6, wc.at_customer_time_in_minutes, NULL)) AS at_customer_time_in_minutes_W6,
  MAX(IF(wc.week_offset = 7, wc.at_customer_time_in_minutes, NULL)) AS at_customer_time_in_minutes_W7,

  MAX(IF(wc.week_offset = 0, wc.at_vendor_time_in_minutes, NULL)) AS at_vendor_time_in_minutes_W0,
  MAX(IF(wc.week_offset = 1, wc.at_vendor_time_in_minutes, NULL)) AS at_vendor_time_in_minutes_W1,
  MAX(IF(wc.week_offset = 2, wc.at_vendor_time_in_minutes, NULL)) AS at_vendor_time_in_minutes_W2,
  MAX(IF(wc.week_offset = 3, wc.at_vendor_time_in_minutes, NULL)) AS at_vendor_time_in_minutes_W3,
  MAX(IF(wc.week_offset = 4, wc.at_vendor_time_in_minutes, NULL)) AS at_vendor_time_in_minutes_W4,
  MAX(IF(wc.week_offset = 5, wc.at_vendor_time_in_minutes, NULL)) AS at_vendor_time_in_minutes_W5,
  MAX(IF(wc.week_offset = 6, wc.at_vendor_time_in_minutes, NULL)) AS at_vendor_time_in_minutes_W6,
  MAX(IF(wc.week_offset = 7, wc.at_vendor_time_in_minutes, NULL)) AS at_vendor_time_in_minutes_W7,

  MAX(IF(wc.week_offset = 0, wc.cdt, NULL)) AS cdt_W0,
  MAX(IF(wc.week_offset = 1, wc.cdt, NULL)) AS cdt_W1,
  MAX(IF(wc.week_offset = 2, wc.cdt, NULL)) AS cdt_W2,
  MAX(IF(wc.week_offset = 3, wc.cdt, NULL)) AS cdt_W3,
  MAX(IF(wc.week_offset = 4, wc.cdt, NULL)) AS cdt_W4,
  MAX(IF(wc.week_offset = 5, wc.cdt, NULL)) AS cdt_W5,
  MAX(IF(wc.week_offset = 6, wc.cdt, NULL)) AS cdt_W6,
  MAX(IF(wc.week_offset = 7, wc.cdt, NULL)) AS cdt_W7,

  MAX(IF(wc.week_offset = 0, wc.perc_reas, NULL)) AS perc_reas_W0,
  MAX(IF(wc.week_offset = 1, wc.perc_reas, NULL)) AS perc_reas_W1,
  MAX(IF(wc.week_offset = 2, wc.perc_reas, NULL)) AS perc_reas_W2,
  MAX(IF(wc.week_offset = 3, wc.perc_reas, NULL)) AS perc_reas_W3,
  MAX(IF(wc.week_offset = 4, wc.perc_reas, NULL)) AS perc_reas_W4,
  MAX(IF(wc.week_offset = 5, wc.perc_reas, NULL)) AS perc_reas_W5,
  MAX(IF(wc.week_offset = 6, wc.perc_reas, NULL)) AS perc_reas_W6,
  MAX(IF(wc.week_offset = 7, wc.perc_reas, NULL)) AS perc_reas_W7,

  MAX(IF(wc.week_offset = 0, wc.no_shows, NULL)) AS no_shows_W0,
  MAX(IF(wc.week_offset = 1, wc.no_shows, NULL)) AS no_shows_W1,
  MAX(IF(wc.week_offset = 2, wc.no_shows, NULL)) AS no_shows_W2,
  MAX(IF(wc.week_offset = 3, wc.no_shows, NULL)) AS no_shows_W3,
  MAX(IF(wc.week_offset = 4, wc.no_shows, NULL)) AS no_shows_W4,
  MAX(IF(wc.week_offset = 5, wc.no_shows, NULL)) AS no_shows_W5,
  MAX(IF(wc.week_offset = 6, wc.no_shows, NULL)) AS no_shows_W6,
  MAX(IF(wc.week_offset = 7, wc.no_shows, NULL)) AS no_shows_W7,

  MAX(IF(wc.week_offset = 0, wc.shifts_done, NULL)) AS shifts_done_W0,
  MAX(IF(wc.week_offset = 1, wc.shifts_done, NULL)) AS shifts_done_W1,
  MAX(IF(wc.week_offset = 2, wc.shifts_done, NULL)) AS shifts_done_W2,
  MAX(IF(wc.week_offset = 3, wc.shifts_done, NULL)) AS shifts_done_W3,
  MAX(IF(wc.week_offset = 4, wc.shifts_done, NULL)) AS shifts_done_W4,
  MAX(IF(wc.week_offset = 5, wc.shifts_done, NULL)) AS shifts_done_W5,
  MAX(IF(wc.week_offset = 6, wc.shifts_done, NULL)) AS shifts_done_W6,
  MAX(IF(wc.week_offset = 7, wc.shifts_done, NULL)) AS shifts_done_W7,

  MAX(IF(wc.week_offset = 0, wc.all_shifts, NULL)) AS all_shifts_W0,
  MAX(IF(wc.week_offset = 1, wc.all_shifts, NULL)) AS all_shifts_W1,
  MAX(IF(wc.week_offset = 2, wc.all_shifts, NULL)) AS all_shifts_W2,
  MAX(IF(wc.week_offset = 3, wc.all_shifts, NULL)) AS all_shifts_W3,
  MAX(IF(wc.week_offset = 4, wc.all_shifts, NULL)) AS all_shifts_W4,
  MAX(IF(wc.week_offset = 5, wc.all_shifts, NULL)) AS all_shifts_W5,
  MAX(IF(wc.week_offset = 6, wc.all_shifts, NULL)) AS all_shifts_W6,
  MAX(IF(wc.week_offset = 7, wc.all_shifts, NULL)) AS all_shifts_W7,

  MAX(IF(wc.week_offset = 0, wc.hours_worked, NULL)) AS hours_worked_W0,
  MAX(IF(wc.week_offset = 1, wc.hours_worked, NULL)) AS hours_worked_W1,
  MAX(IF(wc.week_offset = 2, wc.hours_worked, NULL)) AS hours_worked_W2,
  MAX(IF(wc.week_offset = 3, wc.hours_worked, NULL)) AS hours_worked_W3,
  MAX(IF(wc.week_offset = 4, wc.hours_worked, NULL)) AS hours_worked_W4,
  MAX(IF(wc.week_offset = 5, wc.hours_worked, NULL)) AS hours_worked_W5,
  MAX(IF(wc.week_offset = 6, wc.hours_worked, NULL)) AS hours_worked_W6,
  MAX(IF(wc.week_offset = 7, wc.hours_worked, NULL)) AS hours_worked_W7,

  MAX(IF(wc.week_offset = 0, wc.contacts_total_tickets, NULL)) AS contacts_total_tickets_W0,
  MAX(IF(wc.week_offset = 1, wc.contacts_total_tickets, NULL)) AS contacts_total_tickets_W1,
  MAX(IF(wc.week_offset = 2, wc.contacts_total_tickets, NULL)) AS contacts_total_tickets_W2,
  MAX(IF(wc.week_offset = 3, wc.contacts_total_tickets, NULL)) AS contacts_total_tickets_W3,
  MAX(IF(wc.week_offset = 4, wc.contacts_total_tickets, NULL)) AS contacts_total_tickets_W4,
  MAX(IF(wc.week_offset = 5, wc.contacts_total_tickets, NULL)) AS contacts_total_tickets_W5,
  MAX(IF(wc.week_offset = 6, wc.contacts_total_tickets, NULL)) AS contacts_total_tickets_W6,
  MAX(IF(wc.week_offset = 7, wc.contacts_total_tickets, NULL)) AS contacts_total_tickets_W7,

  MAX(IF(wc.week_offset = 0, wc.avg_sat_score, NULL)) AS avg_sat_score_W0,
  MAX(IF(wc.week_offset = 1, wc.avg_sat_score, NULL)) AS avg_sat_score_W1,
  MAX(IF(wc.week_offset = 2, wc.avg_sat_score, NULL)) AS avg_sat_score_W2,
  MAX(IF(wc.week_offset = 3, wc.avg_sat_score, NULL)) AS avg_sat_score_W3,
  MAX(IF(wc.week_offset = 4, wc.avg_sat_score, NULL)) AS avg_sat_score_W4,
  MAX(IF(wc.week_offset = 5, wc.avg_sat_score, NULL)) AS avg_sat_score_W5,
  MAX(IF(wc.week_offset = 6, wc.avg_sat_score, NULL)) AS avg_sat_score_W6,
  MAX(IF(wc.week_offset = 7, wc.avg_sat_score, NULL)) AS avg_sat_score_W7,

  MAX(IF(wc.week_offset = 0, wc.compliance_total_violations, NULL)) AS compliance_total_violations_W0,
  MAX(IF(wc.week_offset = 1, wc.compliance_total_violations, NULL)) AS compliance_total_violations_W1,
  MAX(IF(wc.week_offset = 2, wc.compliance_total_violations, NULL)) AS compliance_total_violations_W2,
  MAX(IF(wc.week_offset = 3, wc.compliance_total_violations, NULL)) AS compliance_total_violations_W3,
  MAX(IF(wc.week_offset = 4, wc.compliance_total_violations, NULL)) AS compliance_total_violations_W4,
  MAX(IF(wc.week_offset = 5, wc.compliance_total_violations, NULL)) AS compliance_total_violations_W5,
  MAX(IF(wc.week_offset = 6, wc.compliance_total_violations, NULL)) AS compliance_total_violations_W6,
  MAX(IF(wc.week_offset = 7, wc.compliance_total_violations, NULL)) AS compliance_total_violations_W7,

  MAX(IF(wc.week_offset = 0, wc.compliance_distinct_violation_types, NULL)) AS compliance_distinct_violation_types_W0,
  MAX(IF(wc.week_offset = 1, wc.compliance_distinct_violation_types, NULL)) AS compliance_distinct_violation_types_W1,
  MAX(IF(wc.week_offset = 2, wc.compliance_distinct_violation_types, NULL)) AS compliance_distinct_violation_types_W2,
  MAX(IF(wc.week_offset = 3, wc.compliance_distinct_violation_types, NULL)) AS compliance_distinct_violation_types_W3,
  MAX(IF(wc.week_offset = 4, wc.compliance_distinct_violation_types, NULL)) AS compliance_distinct_violation_types_W4,
  MAX(IF(wc.week_offset = 5, wc.compliance_distinct_violation_types, NULL)) AS compliance_distinct_violation_types_W5,
  MAX(IF(wc.week_offset = 6, wc.compliance_distinct_violation_types, NULL)) AS compliance_distinct_violation_types_W6,
  MAX(IF(wc.week_offset = 7, wc.compliance_distinct_violation_types, NULL)) AS compliance_distinct_violation_types_W7,

  MAX(IF(wc.week_offset = 0, wc.earnings_per_hour, NULL)) AS earnings_per_hour_W0,
  MAX(IF(wc.week_offset = 1, wc.earnings_per_hour, NULL)) AS earnings_per_hour_W1,
  MAX(IF(wc.week_offset = 2, wc.earnings_per_hour, NULL)) AS earnings_per_hour_W2,
  MAX(IF(wc.week_offset = 3, wc.earnings_per_hour, NULL)) AS earnings_per_hour_W3,
  MAX(IF(wc.week_offset = 4, wc.earnings_per_hour, NULL)) AS earnings_per_hour_W4,
  MAX(IF(wc.week_offset = 5, wc.earnings_per_hour, NULL)) AS earnings_per_hour_W5,
  MAX(IF(wc.week_offset = 6, wc.earnings_per_hour, NULL)) AS earnings_per_hour_W6,
  MAX(IF(wc.week_offset = 7, wc.earnings_per_hour, NULL)) AS earnings_per_hour_W7,

  MAX(IF(wc.week_offset = 0, wc.city_median_earnings_per_hour, NULL)) AS city_median_earnings_per_hour_W0,
  MAX(IF(wc.week_offset = 1, wc.city_median_earnings_per_hour, NULL)) AS city_median_earnings_per_hour_W1,
  MAX(IF(wc.week_offset = 2, wc.city_median_earnings_per_hour, NULL)) AS city_median_earnings_per_hour_W2,
  MAX(IF(wc.week_offset = 3, wc.city_median_earnings_per_hour, NULL)) AS city_median_earnings_per_hour_W3,
  MAX(IF(wc.week_offset = 4, wc.city_median_earnings_per_hour, NULL)) AS city_median_earnings_per_hour_W4,
  MAX(IF(wc.week_offset = 5, wc.city_median_earnings_per_hour, NULL)) AS city_median_earnings_per_hour_W5,
  MAX(IF(wc.week_offset = 6, wc.city_median_earnings_per_hour, NULL)) AS city_median_earnings_per_hour_W6,
  MAX(IF(wc.week_offset = 7, wc.city_median_earnings_per_hour, NULL)) AS city_median_earnings_per_hour_W7,

  MAX(IF(wc.week_offset = 0, wc.earnings_vs_city_median_abs, NULL)) AS earnings_vs_city_median_abs_W0,
  MAX(IF(wc.week_offset = 1, wc.earnings_vs_city_median_abs, NULL)) AS earnings_vs_city_median_abs_W1,
  MAX(IF(wc.week_offset = 2, wc.earnings_vs_city_median_abs, NULL)) AS earnings_vs_city_median_abs_W2,
  MAX(IF(wc.week_offset = 3, wc.earnings_vs_city_median_abs, NULL)) AS earnings_vs_city_median_abs_W3,
  MAX(IF(wc.week_offset = 4, wc.earnings_vs_city_median_abs, NULL)) AS earnings_vs_city_median_abs_W4,
  MAX(IF(wc.week_offset = 5, wc.earnings_vs_city_median_abs, NULL)) AS earnings_vs_city_median_abs_W5,
  MAX(IF(wc.week_offset = 6, wc.earnings_vs_city_median_abs, NULL)) AS earnings_vs_city_median_abs_W6,
  MAX(IF(wc.week_offset = 7, wc.earnings_vs_city_median_abs, NULL)) AS earnings_vs_city_median_abs_W7,

  MAX(IF(wc.week_offset = 0, wc.earnings_vs_city_median_ratio, NULL)) AS earnings_vs_city_median_ratio_W0,
  MAX(IF(wc.week_offset = 1, wc.earnings_vs_city_median_ratio, NULL)) AS earnings_vs_city_median_ratio_W1,
  MAX(IF(wc.week_offset = 2, wc.earnings_vs_city_median_ratio, NULL)) AS earnings_vs_city_median_ratio_W2,
  MAX(IF(wc.week_offset = 3, wc.earnings_vs_city_median_ratio, NULL)) AS earnings_vs_city_median_ratio_W3,
  MAX(IF(wc.week_offset = 4, wc.earnings_vs_city_median_ratio, NULL)) AS earnings_vs_city_median_ratio_W4,
  MAX(IF(wc.week_offset = 5, wc.earnings_vs_city_median_ratio, NULL)) AS earnings_vs_city_median_ratio_W5,
  MAX(IF(wc.week_offset = 6, wc.earnings_vs_city_median_ratio, NULL)) AS earnings_vs_city_median_ratio_W6,
  MAX(IF(wc.week_offset = 7, wc.earnings_vs_city_median_ratio, NULL)) AS earnings_vs_city_median_ratio_W7,

  MAX(IF(wc.week_offset = 0, wc.slot_gap_mean_days, NULL)) AS slot_gap_mean_days_W0,
  MAX(IF(wc.week_offset = 1, wc.slot_gap_mean_days, NULL)) AS slot_gap_mean_days_W1,
  MAX(IF(wc.week_offset = 2, wc.slot_gap_mean_days, NULL)) AS slot_gap_mean_days_W2,
  MAX(IF(wc.week_offset = 3, wc.slot_gap_mean_days, NULL)) AS slot_gap_mean_days_W3,
  MAX(IF(wc.week_offset = 4, wc.slot_gap_mean_days, NULL)) AS slot_gap_mean_days_W4,
  MAX(IF(wc.week_offset = 5, wc.slot_gap_mean_days, NULL)) AS slot_gap_mean_days_W5,
  MAX(IF(wc.week_offset = 6, wc.slot_gap_mean_days, NULL)) AS slot_gap_mean_days_W6,
  MAX(IF(wc.week_offset = 7, wc.slot_gap_mean_days, NULL)) AS slot_gap_mean_days_W7,

  MAX(IF(wc.week_offset = 0, wc.slot_gap_max_days, NULL)) AS slot_gap_max_days_W0,
  MAX(IF(wc.week_offset = 1, wc.slot_gap_max_days, NULL)) AS slot_gap_max_days_W1,
  MAX(IF(wc.week_offset = 2, wc.slot_gap_max_days, NULL)) AS slot_gap_max_days_W2,
  MAX(IF(wc.week_offset = 3, wc.slot_gap_max_days, NULL)) AS slot_gap_max_days_W3,
  MAX(IF(wc.week_offset = 4, wc.slot_gap_max_days, NULL)) AS slot_gap_max_days_W4,
  MAX(IF(wc.week_offset = 5, wc.slot_gap_max_days, NULL)) AS slot_gap_max_days_W5,
  MAX(IF(wc.week_offset = 6, wc.slot_gap_max_days, NULL)) AS slot_gap_max_days_W6,
  MAX(IF(wc.week_offset = 7, wc.slot_gap_max_days, NULL)) AS slot_gap_max_days_W7,

  MAX(IF(wc.week_offset = 0, wc.holiday_days_in_week, NULL)) AS holiday_days_in_week_W0,
  MAX(IF(wc.week_offset = 1, wc.holiday_days_in_week, NULL)) AS holiday_days_in_week_W1,
  MAX(IF(wc.week_offset = 2, wc.holiday_days_in_week, NULL)) AS holiday_days_in_week_W2,
  MAX(IF(wc.week_offset = 3, wc.holiday_days_in_week, NULL)) AS holiday_days_in_week_W3,
  MAX(IF(wc.week_offset = 4, wc.holiday_days_in_week, NULL)) AS holiday_days_in_week_W4,
  MAX(IF(wc.week_offset = 5, wc.holiday_days_in_week, NULL)) AS holiday_days_in_week_W5,
  MAX(IF(wc.week_offset = 6, wc.holiday_days_in_week, NULL)) AS holiday_days_in_week_W6,
  MAX(IF(wc.week_offset = 7, wc.holiday_days_in_week, NULL)) AS holiday_days_in_week_W7,

  MAX(IF(wc.week_offset = 0, wc.season_name, NULL)) AS season_name_W0,

  -- Evolution features: short-term shift (W0-W1) and full-window shift (W0-W7)
  MAX(IF(wc.week_offset = 0, wc.batch_number, NULL)) - MAX(IF(wc.week_offset = 1, wc.batch_number, NULL)) AS batch_number_delta_W0_W1,
  MAX(IF(wc.week_offset = 0, wc.batch_number, NULL)) - MAX(IF(wc.week_offset = 7, wc.batch_number, NULL)) AS batch_number_delta_W0_W7,

  MAX(IF(wc.week_offset = 0, wc.total_orders_cpo, NULL)) - MAX(IF(wc.week_offset = 1, wc.total_orders_cpo, NULL)) AS total_orders_cpo_delta_W0_W1,
  MAX(IF(wc.week_offset = 0, wc.total_orders_cpo, NULL)) - MAX(IF(wc.week_offset = 7, wc.total_orders_cpo, NULL)) AS total_orders_cpo_delta_W0_W7,

  MAX(IF(wc.week_offset = 0, wc.total_earnings, NULL)) - MAX(IF(wc.week_offset = 1, wc.total_earnings, NULL)) AS total_earnings_delta_W0_W1,
  MAX(IF(wc.week_offset = 0, wc.total_earnings, NULL)) - MAX(IF(wc.week_offset = 7, wc.total_earnings, NULL)) AS total_earnings_delta_W0_W7,

  MAX(IF(wc.week_offset = 0, wc.cpo_local_currency, NULL)) - MAX(IF(wc.week_offset = 1, wc.cpo_local_currency, NULL)) AS cpo_local_currency_delta_W0_W1,
  MAX(IF(wc.week_offset = 0, wc.cpo_local_currency, NULL)) - MAX(IF(wc.week_offset = 7, wc.cpo_local_currency, NULL)) AS cpo_local_currency_delta_W0_W7,

  MAX(IF(wc.week_offset = 0, wc.no_shows, NULL)) - MAX(IF(wc.week_offset = 1, wc.no_shows, NULL)) AS no_shows_delta_W0_W1,
  MAX(IF(wc.week_offset = 0, wc.no_shows, NULL)) - MAX(IF(wc.week_offset = 7, wc.no_shows, NULL)) AS no_shows_delta_W0_W7,

  MAX(IF(wc.week_offset = 0, wc.hours_worked, NULL)) - MAX(IF(wc.week_offset = 1, wc.hours_worked, NULL)) AS hours_worked_delta_W0_W1,
  MAX(IF(wc.week_offset = 0, wc.hours_worked, NULL)) - MAX(IF(wc.week_offset = 7, wc.hours_worked, NULL)) AS hours_worked_delta_W0_W7,

  MAX(IF(wc.week_offset = 0, wc.contacts_total_tickets, NULL)) - MAX(IF(wc.week_offset = 1, wc.contacts_total_tickets, NULL)) AS contacts_total_tickets_delta_W0_W1,
  MAX(IF(wc.week_offset = 0, wc.contacts_total_tickets, NULL)) - MAX(IF(wc.week_offset = 7, wc.contacts_total_tickets, NULL)) AS contacts_total_tickets_delta_W0_W7,

  MAX(IF(wc.week_offset = 0, wc.avg_sat_score, NULL)) - MAX(IF(wc.week_offset = 1, wc.avg_sat_score, NULL)) AS avg_sat_score_delta_W0_W1,
  MAX(IF(wc.week_offset = 0, wc.avg_sat_score, NULL)) - MAX(IF(wc.week_offset = 7, wc.avg_sat_score, NULL)) AS avg_sat_score_delta_W0_W7,

  MAX(IF(wc.week_offset = 0, wc.compliance_total_violations, NULL)) - MAX(IF(wc.week_offset = 1, wc.compliance_total_violations, NULL)) AS compliance_total_violations_delta_W0_W1,
  MAX(IF(wc.week_offset = 0, wc.compliance_total_violations, NULL)) - MAX(IF(wc.week_offset = 7, wc.compliance_total_violations, NULL)) AS compliance_total_violations_delta_W0_W7,

  -- RFM assembly across rolling windows
  DATE_DIFF(MAX(IF(wc.week_offset = 0, wc.feature_week, NULL)), MAX(ra.last_order_date), DAY) AS r_recency_days_at_anchor,
  (
    COALESCE(MAX(IF(wc.week_offset = 0, wc.total_orders_cpo, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 1, wc.total_orders_cpo, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 2, wc.total_orders_cpo, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 3, wc.total_orders_cpo, NULL)), 0)
  ) AS f_orders_4w,
  (
    COALESCE(MAX(IF(wc.week_offset = 0, wc.total_orders_cpo, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 1, wc.total_orders_cpo, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 2, wc.total_orders_cpo, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 3, wc.total_orders_cpo, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 4, wc.total_orders_cpo, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 5, wc.total_orders_cpo, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 6, wc.total_orders_cpo, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 7, wc.total_orders_cpo, NULL)), 0)
  ) AS f_orders_8w,
  (
    COALESCE(MAX(IF(wc.week_offset = 0, wc.total_earnings, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 1, wc.total_earnings, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 2, wc.total_earnings, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 3, wc.total_earnings, NULL)), 0)
  ) AS m_earnings_4w,
  (
    COALESCE(MAX(IF(wc.week_offset = 0, wc.total_earnings, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 1, wc.total_earnings, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 2, wc.total_earnings, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 3, wc.total_earnings, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 4, wc.total_earnings, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 5, wc.total_earnings, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 6, wc.total_earnings, NULL)), 0)
    + COALESCE(MAX(IF(wc.week_offset = 7, wc.total_earnings, NULL)), 0)
  ) AS m_earnings_8w,

  SAFE_DIVIDE(
    (
      COALESCE(MAX(IF(wc.week_offset = 0, wc.total_earnings, NULL)), 0)
      + COALESCE(MAX(IF(wc.week_offset = 1, wc.total_earnings, NULL)), 0)
      + COALESCE(MAX(IF(wc.week_offset = 2, wc.total_earnings, NULL)), 0)
      + COALESCE(MAX(IF(wc.week_offset = 3, wc.total_earnings, NULL)), 0)
    ),
    NULLIF(
      (
        COALESCE(MAX(IF(wc.week_offset = 4, wc.total_earnings, NULL)), 0)
        + COALESCE(MAX(IF(wc.week_offset = 5, wc.total_earnings, NULL)), 0)
        + COALESCE(MAX(IF(wc.week_offset = 6, wc.total_earnings, NULL)), 0)
        + COALESCE(MAX(IF(wc.week_offset = 7, wc.total_earnings, NULL)), 0)
      ),
      0
    )
  ) AS m_earnings_recent4w_vs_prev4w_ratio,

  SAFE_DIVIDE(
    (
      COALESCE(MAX(IF(wc.week_offset = 0, wc.total_orders_cpo, NULL)), 0)
      + COALESCE(MAX(IF(wc.week_offset = 1, wc.total_orders_cpo, NULL)), 0)
      + COALESCE(MAX(IF(wc.week_offset = 2, wc.total_orders_cpo, NULL)), 0)
      + COALESCE(MAX(IF(wc.week_offset = 3, wc.total_orders_cpo, NULL)), 0)
    ),
    NULLIF(
      (
        COALESCE(MAX(IF(wc.week_offset = 4, wc.total_orders_cpo, NULL)), 0)
        + COALESCE(MAX(IF(wc.week_offset = 5, wc.total_orders_cpo, NULL)), 0)
        + COALESCE(MAX(IF(wc.week_offset = 6, wc.total_orders_cpo, NULL)), 0)
        + COALESCE(MAX(IF(wc.week_offset = 7, wc.total_orders_cpo, NULL)), 0)
      ),
      0
    )
  ) AS f_orders_recent4w_vs_prev4w_ratio,

  -- Fuel/cost proxy from effective distance economics
  SAFE_DIVIDE(
    (
      COALESCE(MAX(IF(wc.week_offset = 0, wc.total_earnings, NULL)), 0)
      + COALESCE(MAX(IF(wc.week_offset = 1, wc.total_earnings, NULL)), 0)
      + COALESCE(MAX(IF(wc.week_offset = 2, wc.total_earnings, NULL)), 0)
      + COALESCE(MAX(IF(wc.week_offset = 3, wc.total_earnings, NULL)), 0)
      + COALESCE(MAX(IF(wc.week_offset = 4, wc.total_earnings, NULL)), 0)
      + COALESCE(MAX(IF(wc.week_offset = 5, wc.total_earnings, NULL)), 0)
      + COALESCE(MAX(IF(wc.week_offset = 6, wc.total_earnings, NULL)), 0)
      + COALESCE(MAX(IF(wc.week_offset = 7, wc.total_earnings, NULL)), 0)
    ),
    NULLIF(
      (
        COALESCE(MAX(IF(wc.week_offset = 0, wc.avg_total_distance_google * wc.total_orders_cpo, NULL)), 0)
        + COALESCE(MAX(IF(wc.week_offset = 1, wc.avg_total_distance_google * wc.total_orders_cpo, NULL)), 0)
        + COALESCE(MAX(IF(wc.week_offset = 2, wc.avg_total_distance_google * wc.total_orders_cpo, NULL)), 0)
        + COALESCE(MAX(IF(wc.week_offset = 3, wc.avg_total_distance_google * wc.total_orders_cpo, NULL)), 0)
        + COALESCE(MAX(IF(wc.week_offset = 4, wc.avg_total_distance_google * wc.total_orders_cpo, NULL)), 0)
        + COALESCE(MAX(IF(wc.week_offset = 5, wc.avg_total_distance_google * wc.total_orders_cpo, NULL)), 0)
        + COALESCE(MAX(IF(wc.week_offset = 6, wc.avg_total_distance_google * wc.total_orders_cpo, NULL)), 0)
        + COALESCE(MAX(IF(wc.week_offset = 7, wc.avg_total_distance_google * wc.total_orders_cpo, NULL)), 0)
      ),
      0
    )
  ) AS earnings_per_km_8w,

  -- Early lifecycle/newbie predictors
  MAX(nef.days_registration_to_first_order) AS days_registration_to_first_order,
  MAX(nef.orders_first_7d) AS orders_first_7d,
  MAX(nef.orders_first_30d) AS orders_first_30d,
  MAX(nef.compliance_events_first_30d) AS compliance_events_first_30d,
  MAX(nef.first_week_earnings) AS first_week_earnings,
  MAX(nef.city_avg_earnings_first_week) AS city_avg_earnings_first_week,
  MAX(nef.first_week_earnings_vs_city_avg_ratio) AS first_week_earnings_vs_city_avg_ratio

FROM weekly_combined wc
LEFT JOIN rider_attrs ra ON ra.rider_id = wc.rider_id
LEFT JOIN applicant_source apl ON apl.rider_id = wc.rider_id
LEFT JOIN newbie_early_features nef ON nef.rider_id = wc.rider_id
GROUP BY wc.rider_id
ORDER BY wc.rider_id;
