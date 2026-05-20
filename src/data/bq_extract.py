"""
BigQuery data extraction for rider churn prediction.

Pulls courier-level behavioral data from BigQuery for feature engineering.
"""

from google.cloud import bigquery
import pandas as pd
import yaml
from loguru import logger


def load_config(path: str = "config/config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def get_bq_client(config: dict) -> bigquery.Client:
    """Initialize BigQuery client."""
    return bigquery.Client(
        project=config["bigquery"]["project_id"],
        # credentials_path used for service account in scheduled runs
    )


def extract_courier_base(client: bigquery.Client, city: str, lookback_days: int = 90) -> pd.DataFrame:
    """
    Extract base courier data: courier_id, city, hire_date, vehicle_type, 
    onboarding_channel, segment (newbie/active/veteran).
    """
    query = f"""
    -- TODO: Replace with actual table/schema names
    SELECT
        courier_id,
        city_code,
        hire_date,
        vehicle_type,
        onboarding_channel,
        DATE_DIFF(CURRENT_DATE(), hire_date, DAY) AS tenure_days
    FROM `{{project}}.{{dataset}}.couriers`
    WHERE city_code = @city
      AND DATE_DIFF(CURRENT_DATE(), hire_date, DAY) <= @lookback_days
      AND total_orders >= 1
    """
    logger.info(f"Extracting courier base for {city}")
    # TODO: Parameterize and execute query
    raise NotImplementedError("Wire up actual BQ query")


def extract_slot_bookings(client: bigquery.Client, city: str, lookback_days: int = 90) -> pd.DataFrame:
    """
    Extract slot booking history per courier.
    Used to determine churn (14 days without booking for active, 7 for newbies).
    """
    query = """
    -- TODO: Replace with actual table/schema names
    SELECT
        courier_id,
        slot_date,
        slot_start_time,
        slot_end_time,
        was_no_show
    FROM `{project}.{dataset}.slot_bookings`
    WHERE city_code = @city
      AND slot_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @lookback_days DAY)
    """
    logger.info(f"Extracting slot bookings for {city}")
    raise NotImplementedError("Wire up actual BQ query")


def extract_order_data(client: bigquery.Client, city: str, lookback_days: int = 90) -> pd.DataFrame:
    """
    Extract order-level data per courier for earnings, distance, delivery time features.
    """
    query = """
    -- TODO: Replace with actual table/schema names
    SELECT
        courier_id,
        order_id,
        order_date,
        earnings,
        is_stacked,
        is_rush_bonus,
        total_distance_km,
        start_to_pickup_distance_km,
        pickup_to_delivery_distance_km,
        delivery_time_minutes,
        waiting_time_pickup_minutes,
        waiting_time_delivery_minutes,
        is_failed,
        fail_reason,  -- courier / customer / vendor / tech
        is_undelivered,
        batch_number
    FROM `{project}.{dataset}.orders`
    WHERE city_code = @city
      AND order_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @lookback_days DAY)
    """
    logger.info(f"Extracting order data for {city}")
    raise NotImplementedError("Wire up actual BQ query")


def extract_contacts(client: bigquery.Client, city: str, lookback_days: int = 90) -> pd.DataFrame:
    """
    Extract rider support contacts and outcomes.
    """
    query = """
    -- TODO: Replace with actual table/schema names
    SELECT
        courier_id,
        contact_date,
        contact_reason,
        contact_outcome,
        rsat_score
    FROM `{project}.{dataset}.rider_contacts`
    WHERE city_code = @city
      AND contact_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @lookback_days DAY)
    """
    logger.info(f"Extracting contacts for {city}")
    raise NotImplementedError("Wire up actual BQ query")


def extract_compliance(client: bigquery.Client, city: str, lookback_days: int = 90) -> pd.DataFrame:
    """
    Extract compliance violations per courier.
    """
    query = """
    -- TODO: Replace with actual table/schema names
    SELECT
        courier_id,
        violation_date,
        violation_type,
        severity
    FROM `{project}.{dataset}.compliance_violations`
    WHERE city_code = @city
      AND violation_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @lookback_days DAY)
    """
    logger.info(f"Extracting compliance data for {city}")
    raise NotImplementedError("Wire up actual BQ query")


def extract_cash_balance(client: bigquery.Client, city: str) -> pd.DataFrame:
    """
    Extract current cash balance per courier (relevant for cash-on-delivery markets).
    """
    query = """
    -- TODO: Replace with actual table/schema names
    SELECT
        courier_id,
        cash_balance,
        last_settlement_date
    FROM `{project}.{dataset}.courier_cash_balance`
    WHERE city_code = @city
    """
    logger.info(f"Extracting cash balance for {city}")
    raise NotImplementedError("Wire up actual BQ query")


def build_dataset(city: str, config: dict = None) -> pd.DataFrame:
    """
    Orchestrator: extract all data sources and merge into a single courier-level dataset.
    Returns one row per courier with all raw fields needed for feature engineering.
    """
    if config is None:
        config = load_config()

    client = get_bq_client(config)

    # TODO: Extract, join, and return combined dataset
    # courier_base = extract_courier_base(client, city)
    # slots = extract_slot_bookings(client, city)
    # orders = extract_order_data(client, city)
    # contacts = extract_contacts(client, city)
    # compliance = extract_compliance(client, city)
    # cash = extract_cash_balance(client, city)
    # return merge_all(courier_base, slots, orders, contacts, compliance, cash)

    raise NotImplementedError("Implement full data pipeline")
