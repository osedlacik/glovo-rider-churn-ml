"""
Label generation: determine which couriers have churned based on slot booking gaps.
"""

import pandas as pd
from loguru import logger


def label_churn(
    slot_bookings: pd.DataFrame,
    courier_base: pd.DataFrame,
    threshold_active_days: int = 14,
    threshold_newbie_days: int = 7,
    newbie_max_tenure_days: int = 30,
) -> pd.DataFrame:
    """
    Label each courier as churned (1) or not (0).

    Logic:
    - Newbie (tenure < 30 days): churned if no slot booked in last 7 days
    - Active/Veteran (tenure >= 30 days): churned if no slot booked in last 14 days

    Args:
        slot_bookings: DataFrame with courier_id, slot_date
        courier_base: DataFrame with courier_id, tenure_days
        threshold_active_days: Days without booking to flag active couriers
        threshold_newbie_days: Days without booking to flag newbies
        newbie_max_tenure_days: Max tenure to be considered a newbie

    Returns:
        DataFrame with courier_id, is_churned (0/1), days_since_last_booking, segment
    """
    # TODO: Implement labeling logic
    # 1. Find last booking date per courier
    # 2. Calculate days since last booking
    # 3. Determine segment (newbie vs active/veteran)
    # 4. Apply appropriate threshold
    raise NotImplementedError("Implement churn labeling")


def create_train_test_split(
    labeled_data: pd.DataFrame,
    test_size: float = 0.2,
    time_based: bool = True,
) -> tuple:
    """
    Split data into train and test sets.

    Prefer time-based split (train on older data, test on recent) over random
    to avoid data leakage and simulate real deployment.

    Args:
        labeled_data: Full labeled dataset
        test_size: Fraction for test set
        time_based: If True, split by time rather than random

    Returns:
        (X_train, X_test, y_train, y_test)
    """
    # TODO: Implement split logic
    # Time-based: train on weeks 1-N, test on week N+1
    # This better simulates production where we predict future churn
    raise NotImplementedError("Implement train/test split")
