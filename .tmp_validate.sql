SELECT 'orders_deliveries' AS check_name, COUNT(1) AS n
FROM `fulfillment-dwh-production.curated_data_shared.orders` o, UNNEST(o.deliveries) d
WHERE CAST(d.rider_id AS STRING)='2664450'
  AND o.country_code='gv-pl'
  AND o.created_date BETWEEN DATE('2026-01-01') AND CURRENT_DATE()
  AND d.delivery_status='completed'
  AND d.is_primary=TRUE
  AND d.rider_dropped_off_at IS NOT NULL
UNION ALL
SELECT 'shifts', COUNT(1)
FROM `fulfillment-dwh-production.curated_data_shared.shifts` s
WHERE CAST(s.rider_id AS STRING)='2664450'
  AND s.country_code='gv-pl'
  AND s.created_date BETWEEN DATE('2026-01-01') AND CURRENT_DATE()
  AND s.shift_start_at IS NOT NULL
