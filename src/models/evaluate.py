"""
Model evaluation and validation utilities.
"""

import pandas as pd
import numpy as np
from sklearn.metrics import (
    roc_auc_score,
    precision_recall_curve,
    average_precision_score,
    confusion_matrix,
    classification_report,
)
import matplotlib.pyplot as plt
from loguru import logger


def evaluate_model(y_true, y_prob, threshold: float = 0.5) -> dict:
    """
    Comprehensive model evaluation.

    Returns dict with:
        - roc_auc
        - avg_precision (PR-AUC)
        - precision_at_threshold
        - recall_at_threshold
        - confusion_matrix
        - optimal_threshold (F1-maximizing)
    """
    y_pred = (y_prob >= threshold).astype(int)

    # Find optimal threshold (maximize F1)
    precisions, recalls, thresholds = precision_recall_curve(y_true, y_prob)
    f1_scores = 2 * (precisions * recalls) / (precisions + recalls + 1e-8)
    optimal_idx = np.argmax(f1_scores)
    optimal_threshold = thresholds[optimal_idx] if optimal_idx < len(thresholds) else threshold

    metrics = {
        "roc_auc": roc_auc_score(y_true, y_prob),
        "avg_precision": average_precision_score(y_true, y_prob),
        "precision_at_threshold": precisions[optimal_idx],
        "recall_at_threshold": recalls[optimal_idx],
        "f1_at_threshold": f1_scores[optimal_idx],
        "optimal_threshold": optimal_threshold,
        "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
        "classification_report": classification_report(y_true, y_pred, output_dict=True),
    }

    logger.info(
        f"Evaluation — AUC: {metrics['roc_auc']:.4f}, "
        f"AP: {metrics['avg_precision']:.4f}, "
        f"Optimal threshold: {optimal_threshold:.3f}"
    )
    return metrics


def evaluate_by_segment(y_true, y_prob, segments: pd.Series, threshold: float = 0.5) -> dict:
    """
    Evaluate model performance separately per courier segment (newbie/active/veteran).
    Important: model may perform differently across segments.
    """
    results = {}
    for segment in segments.unique():
        mask = segments == segment
        if mask.sum() < 10:
            continue
        results[segment] = evaluate_model(y_true[mask], y_prob[mask], threshold)
        logger.info(f"  Segment '{segment}': AUC={results[segment]['roc_auc']:.4f}")
    return results


def feature_importance(model, feature_names: list) -> pd.DataFrame:
    """
    Extract and rank feature importances from trained model.

    Returns DataFrame sorted by importance (descending):
        - feature_name
        - importance
        - cumulative_importance
    """
    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
    else:
        raise ValueError("Model does not have feature_importances_ attribute")

    fi = pd.DataFrame({
        "feature": feature_names,
        "importance": importances,
    }).sort_values("importance", ascending=False).reset_index(drop=True)

    fi["cumulative_importance"] = fi["importance"].cumsum() / fi["importance"].sum()
    return fi
