-- Flat weekly rider contact reasons for Poland from 2026-01-01
-- One row per rider x week x contact_reason_code (mapped to human-readable name)
-- Python pivots this to rider-level wide format for the correlation matrix

SELECT
  content.rider_id                                          AS rider_id,
  DATE_TRUNC(DATE(timestamp), WEEK(MONDAY))                 AS week,
  CASE COALESCE(content.contact_reason_code, 'unknown')
    WHEN '15A.1'  THEN 'address_change'
    WHEN '15A.2'  THEN 'change_order_details'
    WHEN '15A.3'  THEN 'customer_feedback'
    WHEN '15A.4'  THEN 'id_check'
    WHEN '15A.5'  THEN 'access_customer_premises'
    WHEN '15A.6'  THEN 'refuse_accept_order'
    WHEN '15A.7'  THEN 'unable_contact_customer'
    WHEN '15A.8'  THEN 'unable_find_location'
    WHEN '15A.9'  THEN 'wrong_address'
    WHEN '15B.1'  THEN 'administrative_matter'
    WHEN '15B.2'  THEN 'chat_acknowledgment'
    WHEN '15C.1'  THEN 'checking_order_status'
    WHEN '15C.2'  THEN 'large_order'
    WHEN '15C.3'  THEN 'missing_item'
    WHEN '15C.4'  THEN 'spilled_damaged'
    WHEN '15C.5'  THEN 'stacked_order_dropoff'
    WHEN '15D.1'  THEN 'partner_closed'
    WHEN '15D.2'  THEN 'partner_device_issue'
    WHEN '15D.3'  THEN 'partner_no_order'
    WHEN '15D.4'  THEN 'partner_feedback'
    WHEN '15D.5'  THEN 'access_partner_premises'
    WHEN '15D.6'  THEN 'late_preparation'
    WHEN '15D.7'  THEN 'order_modification'
    WHEN '15D.8'  THEN 'order_taken_other_rider'
    WHEN '15D.9'  THEN 'product_unavailable'
    WHEN '15D.10' THEN 'partner_refuse_prepare'
    WHEN '15D.11' THEN 'unable_locate_partner'
    WHEN '15E.1'  THEN 'accident'
    WHEN '15E.2'  THEN 'app_issue'
    WHEN '15E.3'  THEN 'asks_order_assignment'
    WHEN '15E.4'  THEN 'asks_phone_number'
    WHEN '15E.5'  THEN 'break_request'
    WHEN '15E.6'  THEN 'break_status'
    WHEN '15E.7'  THEN 'callback_request'
    WHEN '15E.8'  THEN 'chat_reason_unknown'
    WHEN '15E.9'  THEN 'clicked_through'
    WHEN '15E.10' THEN 'cod_issue'
    WHEN '15E.11' THEN 'equipment_issue'
    WHEN '15E.12' THEN 'end_break'
    WHEN '15E.13' THEN 'not_willing_order'
    WHEN '15E.14' THEN 'shift_adjustment'
    WHEN '15E.15' THEN 'translations_needed'
    WHEN '15E.16' THEN 'updating_status'
    WHEN '20A.1'  THEN 'not_applicable'
    ELSE COALESCE(content.contact_reason_code, 'unknown')
  END                                                       AS contact_reason_code,
  COUNT(*)                                                  AS ticket_count

FROM `fulfillment-dwh-production.curated_data_shared_data_stream.rider_ticket_stream`

WHERE timestamp > TIMESTAMP('2026-01-01')
  AND content.global_entity_id = 'GV_PL'
  AND content.action = 'Create'
  AND content.rider_id IS NOT NULL

GROUP BY 1, 2, 3
ORDER BY rider_id, week