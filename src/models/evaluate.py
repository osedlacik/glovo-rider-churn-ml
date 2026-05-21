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
    brier_score_loss,
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


def ranking_metrics_at_k(
    y_true: pd.Series | np.ndarray,
    y_prob: pd.Series | np.ndarray,
    k_values: list[int],
) -> pd.DataFrame:
    """Compute Precision@K, Recall@K, and Lift@K for operational cut points."""
    y_true_arr = np.asarray(y_true).astype(int)
    y_prob_arr = np.asarray(y_prob).astype(float)

    order = np.argsort(-y_prob_arr)
    y_sorted = y_true_arr[order]

    base_rate = float(y_true_arr.mean()) if len(y_true_arr) else np.nan
    total_positives = int(y_true_arr.sum())

    rows = []
    for k in k_values:
        k_eff = int(min(max(k, 1), len(y_sorted)))
        hits = int(y_sorted[:k_eff].sum())
        precision = float(hits / k_eff) if k_eff > 0 else np.nan
        recall = float(hits / total_positives) if total_positives > 0 else np.nan
        lift = float(precision / base_rate) if base_rate and np.isfinite(base_rate) and base_rate > 0 else np.nan

        rows.append(
            {
                "k": int(k),
                "cohort_size": k_eff,
                "true_positives_in_top_k": hits,
                "precision_at_k": precision,
                "recall_at_k": recall,
                "lift_at_k": lift,
                "base_positive_rate": base_rate,
            }
        )

    return pd.DataFrame(rows)


def threshold_capacity_table(
    y_true: pd.Series | np.ndarray,
    y_prob: pd.Series | np.ndarray,
    quantiles: list[float] | None = None,
) -> pd.DataFrame:
    """Map score threshold to expected intervention cohort size and precision."""
    y_true_arr = np.asarray(y_true).astype(int)
    y_prob_arr = np.asarray(y_prob).astype(float)

    if quantiles is None:
        quantiles = [
            0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.93, 0.95, 0.97, 0.98, 0.99,
        ]

    threshold_values = sorted({float(np.quantile(y_prob_arr, q)) for q in quantiles})

    rows = []
    for threshold in threshold_values:
        selected = y_prob_arr >= threshold
        size = int(selected.sum())
        precision = float(y_true_arr[selected].mean()) if size > 0 else np.nan
        rows.append(
            {
                "score_threshold": float(threshold),
                "expected_cohort_size": size,
                "expected_precision": precision,
            }
        )

    return pd.DataFrame(rows).sort_values("score_threshold", ascending=False).reset_index(drop=True)


def weekly_backtest_table(
    y_true: pd.Series | np.ndarray,
    y_prob: pd.Series | np.ndarray,
    event_week: pd.Series,
) -> pd.DataFrame:
    """Compute temporal backtest metrics by event_week cohort."""
    df = pd.DataFrame(
        {
            "y_true": np.asarray(y_true).astype(int),
            "y_prob": np.asarray(y_prob).astype(float),
            "event_week": pd.to_datetime(event_week, errors="coerce"),
        }
    ).dropna(subset=["event_week"])

    rows = []
    for week, part in df.groupby("event_week"):
        y_w = part["y_true"].to_numpy()
        p_w = part["y_prob"].to_numpy()
        has_two_classes = len(np.unique(y_w)) > 1
        has_positive = int(y_w.sum()) > 0
        rows.append(
            {
                "event_week": pd.Timestamp(week).date().isoformat(),
                "rows": int(len(part)),
                "positive_rate": float(y_w.mean()),
                "roc_auc": float(roc_auc_score(y_w, p_w)) if has_two_classes else np.nan,
                "avg_precision": float(average_precision_score(y_w, p_w)) if has_positive else np.nan,
                "brier_score": float(brier_score_loss(y_w, p_w)),
            }
        )

    return pd.DataFrame(rows).sort_values("event_week").reset_index(drop=True)


def calibration_table(
    y_true: pd.Series | np.ndarray,
    y_prob: pd.Series | np.ndarray,
    bins: int = 10,
) -> pd.DataFrame:
    """Summarize calibration by score bins for threshold reliability checks."""
    df = pd.DataFrame(
        {
            "y_true": np.asarray(y_true).astype(int),
            "y_prob": np.asarray(y_prob).astype(float),
        }
    )
    df["bin"] = pd.qcut(df["y_prob"], q=bins, labels=False, duplicates="drop")

    out = (
        df.groupby("bin")
        .agg(
            count=("y_true", "size"),
            mean_predicted=("y_prob", "mean"),
            observed_rate=("y_true", "mean"),
        )
        .reset_index()
        .sort_values("bin")
    )
    out["calibration_gap"] = out["mean_predicted"] - out["observed_rate"]
    return out
