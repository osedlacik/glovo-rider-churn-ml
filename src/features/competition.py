"""
Competition-related features.

KPIs:
- Average cash balance
- Undelivered orders ratio
- Fraud signals
"""

import pandas as pd
import numpy as np


def compute_competition_features(
    orders: pd.DataFrame,
    cash_balance: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute competition/fraud-related features per courier.

    Features:
        - avg_cash_balance: average outstanding cash balance
        - high_cash_balance_flag: cash balance above city threshold
        - undelivered_rate: orders marked undelivered by customer but delivered by courier
        - fraud_score: composite fraud risk indicator
    """
    # TODO: Implement competition features
    # High cash balance in manual payment markets is a churn risk factor
    raise NotImplementedError("Implement competition features")
