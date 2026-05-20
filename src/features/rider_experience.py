"""
Rider experience features for churn prediction.

KPIs:
- % BW (bad weather) orders delivered per courier
- % Stacking (grouped orders)
- Average # rider contacts (and reasons/outcomes)
- RSAT (rider satisfaction score)
- % CR (cancellation rate) for city/country
- Average total distance per order
- Average SP distance (start → pickup)
- Average PD distance (pickup → delivery)
- CDT (average courier delivery time)
- Waiting time at pickup
- Waiting time at delivery
- BW (bad weather impact)
- Time of slots (peak / off-peak split)
- Average batch number
"""

import pandas as pd
import numpy as np


def compute_experience_features(
    orders: pd.DataFrame,
    contacts: pd.DataFrame,
    slots: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute rider experience features per courier.

    Features:
        - pct_bw_orders: % of orders during bad weather
        - pct_stacked: % stacked/batched orders
        - avg_contacts_per_week: rider support contact frequency
        - contact_trend: increasing contacts = frustration signal
        - avg_rsat: average rider satisfaction score
        - rsat_trend: declining RSAT is a churn signal
        - avg_total_distance_km: average order distance
        - avg_sp_distance_km: avg start-to-pickup distance
        - avg_pd_distance_km: avg pickup-to-delivery distance
        - avg_cdt_minutes: average courier delivery time
        - avg_waiting_pickup_min: avg wait at pickup
        - avg_waiting_delivery_min: avg wait at delivery
        - pct_peak_slots: % of slots booked during peak hours
        - avg_batch_number: average batch assignment
    """
    # TODO: Implement feature calculations
    raise NotImplementedError("Implement experience features")


def compute_contact_features(contacts: pd.DataFrame) -> pd.DataFrame:
    """
    Detailed contact analysis: frequency, reasons, outcomes.
    High contact frequency with negative outcomes signals frustration → churn.
    """
    # TODO: Contact reason categorization and trend analysis
    raise NotImplementedError("Implement contact features")
