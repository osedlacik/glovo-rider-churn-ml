"""
Earnings-related features for churn prediction.

KPIs:
- Orders delivered per courier (per time frame / slot)
- Total earnings per courier (lifetime)
- Earnings per Hour (EpH)
- Earnings per Day (EpD)
- Earnings per Week (EpW)
- % Stacking (grouped orders)
- Average hours worked per day over lifespan
- % orders with Rush Bonus
- Glovo Plus flag
"""

import pandas as pd
import numpy as np


def compute_earnings_features(orders: pd.DataFrame, slots: pd.DataFrame) -> pd.DataFrame:
    """
    Compute earnings-related features per courier.

    Input: order-level and slot-level data
    Output: one row per courier with all earnings features

    Features:
        - total_orders: lifetime order count
        - orders_last_7d, orders_last_14d, orders_last_30d
        - total_earnings: lifetime total
        - earnings_per_hour: total earnings / total hours worked
        - earnings_per_day: avg daily earnings (active days only)
        - earnings_per_week: avg weekly earnings
        - earnings_trend_7d: % change in EpH last 7d vs prior 7d
        - pct_stacked_orders: % orders that were part of a batch
        - pct_rush_bonus: % orders with rush bonus
        - avg_hours_per_day: average hours worked per active day
        - hours_trend_7d: % change in hours last 7d vs prior 7d
    """
    # TODO: Implement feature calculations
    # Key: compute TRENDS (week-over-week changes) as these are strong churn signals
    raise NotImplementedError("Implement earnings features")


def compute_earnings_trends(orders: pd.DataFrame, windows: list = [7, 14, 28]) -> pd.DataFrame:
    """
    Compute rolling window trends for earnings metrics.
    Declining trends are strong churn predictors.

    Returns: courier_id, metric, window, current_value, previous_value, pct_change
    """
    # TODO: Week-over-week and multi-week trends
    raise NotImplementedError("Implement earnings trends")
