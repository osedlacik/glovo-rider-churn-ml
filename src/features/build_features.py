"""
Feature pipeline: orchestrates all feature computations into a single feature matrix.
"""

import pandas as pd
from loguru import logger

from src.features.earnings import compute_earnings_features
from src.features.rider_experience import compute_experience_features
from src.features.engagement import compute_engagement_features
from src.features.competition import compute_competition_features


def build_feature_matrix(raw_data: dict) -> pd.DataFrame:
    """
    Build the full feature matrix from raw extracted data.

    Args:
        raw_data: dict with keys: orders, slots, contacts, compliance, 
                  courier_base, cash_balance

    Returns:
        DataFrame with one row per courier and all computed features.
        Columns: courier_id, city, segment, [all feature columns]
    """
    logger.info("Building feature matrix...")

    # TODO: Call each feature module and merge results
    # earnings = compute_earnings_features(raw_data["orders"], raw_data["slots"])
    # experience = compute_experience_features(raw_data["orders"], raw_data["contacts"], raw_data["slots"])
    # engagement = compute_engagement_features(raw_data["orders"], raw_data["slots"], raw_data["compliance"], raw_data["courier_base"])
    # competition = compute_competition_features(raw_data["orders"], raw_data["cash_balance"])

    # Merge all feature sets on courier_id
    # feature_matrix = courier_base.merge(earnings).merge(experience).merge(engagement).merge(competition)

    raise NotImplementedError("Implement feature matrix assembly")


# All features expected in the final matrix
FEATURE_COLUMNS = [
    # Earnings
    "total_orders",
    "orders_last_7d",
    "orders_last_14d",
    "orders_last_30d",
    "total_earnings",
    "earnings_per_hour",
    "earnings_per_day",
    "earnings_per_week",
    "earnings_trend_7d",
    "pct_stacked_orders",
    "pct_rush_bonus",
    "avg_hours_per_day",
    "hours_trend_7d",
    # Rider Experience
    "pct_bw_orders",
    "avg_contacts_per_week",
    "contact_trend",
    "avg_rsat",
    "rsat_trend",
    "avg_total_distance_km",
    "avg_sp_distance_km",
    "avg_pd_distance_km",
    "avg_cdt_minutes",
    "avg_waiting_pickup_min",
    "avg_waiting_delivery_min",
    "pct_peak_slots",
    "avg_batch_number",
    # Engagement
    "pct_reassignment",
    "pct_no_shows",
    "no_show_trend",
    "pct_fail_courier",
    "pct_fail_customer",
    "pct_fail_vendor",
    "slots_booked_trend_7d",
    "slots_booked_trend_14d",
    "days_since_last_booking",
    "booking_regularity",
    "slot_utilization",
    "total_violations",
    "violations_per_order",
    # Competition
    "avg_cash_balance",
    "high_cash_balance_flag",
    "undelivered_rate",
    # Metadata (categorical, will be encoded)
    "vehicle_type",
    "onboarding_channel",
    "tenure_days",
    "segment",
]
