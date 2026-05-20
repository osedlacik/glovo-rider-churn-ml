"""
Prediction pipeline: score couriers with trained model.
"""

import pandas as pd
import numpy as np
import shap
from loguru import logger

from src.models.train import load_model
from src.features.build_features import build_feature_matrix, FEATURE_COLUMNS


def predict_churn(
    feature_matrix: pd.DataFrame,
    model=None,
    model_path: str = "models/churn_model.joblib",
    threshold: float = 0.5,
) -> pd.DataFrame:
    """
    Score all couriers and return churn predictions with probabilities.

    Args:
        feature_matrix: DataFrame with all features (one row per courier)
        model: Trained model (loaded from disk if not provided)
        threshold: Probability threshold for high-risk flag

    Returns:
        DataFrame with:
            - courier_id
            - churn_probability (0-1)
            - is_high_risk (bool)
            - risk_rank (1 = highest risk)
    """
    if model is None:
        model = load_model(model_path)

    X = feature_matrix[FEATURE_COLUMNS]
    probabilities = model.predict_proba(X)[:, 1]

    results = feature_matrix[["courier_id", "city", "segment"]].copy()
    results["churn_probability"] = probabilities
    results["is_high_risk"] = probabilities >= threshold
    results["risk_rank"] = results["churn_probability"].rank(ascending=False, method="dense").astype(int)

    # Sort by probability descending
    results = results.sort_values("churn_probability", ascending=False).reset_index(drop=True)

    logger.info(
        f"Scored {len(results)} couriers: "
        f"{results['is_high_risk'].sum()} high-risk ({results['is_high_risk'].mean()*100:.1f}%)"
    )
    return results


def explain_predictions(
    feature_matrix: pd.DataFrame,
    model=None,
    model_path: str = "models/churn_model.joblib",
    top_n_features: int = 5,
) -> pd.DataFrame:
    """
    Generate SHAP-based explanations for each courier's churn prediction.
    Answers: "Why is this courier at risk?"

    Returns:
        DataFrame with courier_id and top N contributing features with their impact.
    """
    if model is None:
        model = load_model(model_path)

    X = feature_matrix[FEATURE_COLUMNS]

    # TODO: Compute SHAP values
    # explainer = shap.TreeExplainer(model)
    # shap_values = explainer.shap_values(X)

    # For each courier, find top N features driving their score
    # Return: courier_id, feature_1, impact_1, feature_2, impact_2, ...

    raise NotImplementedError("Implement SHAP explanations")


def get_city_summary(predictions: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate predictions at city level.
    
    Returns per city:
        - total_active_couriers
        - high_risk_count
        - high_risk_pct
        - avg_churn_probability
        - predicted_fleet_in_30d (estimated remaining active)
    """
    summary = predictions.groupby("city").agg(
        total_couriers=("courier_id", "count"),
        high_risk_count=("is_high_risk", "sum"),
        avg_churn_prob=("churn_probability", "mean"),
    ).reset_index()

    summary["high_risk_pct"] = (summary["high_risk_count"] / summary["total_couriers"] * 100).round(1)
    summary["predicted_fleet_30d"] = (
        summary["total_couriers"] - summary["high_risk_count"]
    )  # Simplified; refine with probability weighting

    return summary
