"""
Model training pipeline for rider churn prediction.

Trains multiple models (XGBoost, LightGBM, Random Forest), evaluates them,
and selects the best performer.
"""

import pandas as pd
import numpy as np
from sklearn.model_selection import cross_val_score
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from sklearn.metrics import (
    classification_report,
    roc_auc_score,
    precision_recall_curve,
    average_precision_score,
)
from loguru import logger
import joblib
from pathlib import Path


MODELS = {
    "xgboost": XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        scale_pos_weight=1,  # TODO: set based on class imbalance ratio
        random_state=42,
        use_label_encoder=False,
        eval_metric="logloss",
    ),
    "lightgbm": LGBMClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        class_weight="balanced",
        random_state=42,
        verbose=-1,
    ),
    "random_forest": RandomForestClassifier(
        n_estimators=200,
        max_depth=10,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    ),
}


def train_models(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    models: dict = None,
) -> dict:
    """
    Train all candidate models and return results.

    Args:
        X_train, y_train: Training data
        X_test, y_test: Test data
        models: Dict of model_name -> estimator (defaults to MODELS)

    Returns:
        Dict with model_name -> {model, metrics, predictions}
    """
    if models is None:
        models = MODELS

    results = {}
    for name, model in models.items():
        logger.info(f"Training {name}...")
        model.fit(X_train, y_train)

        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]

        metrics = {
            "roc_auc": roc_auc_score(y_test, y_prob),
            "avg_precision": average_precision_score(y_test, y_prob),
            "classification_report": classification_report(y_test, y_pred, output_dict=True),
        }

        results[name] = {
            "model": model,
            "metrics": metrics,
            "predictions": y_prob,
        }
        logger.info(f"{name} — AUC: {metrics['roc_auc']:.4f}, AP: {metrics['avg_precision']:.4f}")

    return results


def select_best_model(results: dict, metric: str = "roc_auc") -> tuple:
    """
    Select the best model based on a given metric.
    Returns (model_name, model_object).
    """
    best_name = max(results, key=lambda k: results[k]["metrics"][metric])
    logger.info(f"Best model: {best_name} ({metric}={results[best_name]['metrics'][metric]:.4f})")
    return best_name, results[best_name]["model"]


def save_model(model, path: str = "models/churn_model.joblib"):
    """Save trained model to disk."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    logger.info(f"Model saved to {path}")


def load_model(path: str = "models/churn_model.joblib"):
    """Load trained model from disk."""
    return joblib.load(path)
