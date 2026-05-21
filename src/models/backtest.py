"""Rolling-origin backtest and drift diagnostics for phase12 dataset."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline

from src.models.train import _build_preprocessor, _candidate_models


def _precision_at_k(y_true: pd.Series, y_prob: np.ndarray, k: int = 500) -> float:
    k_eff = min(k, len(y_true))
    if k_eff <= 0:
        return float("nan")
    order = np.argsort(-y_prob)
    top = y_true.to_numpy()[order][:k_eff]
    return float(np.mean(top))


def _ece_score(y_true: pd.Series, y_prob: np.ndarray, bins: int = 10) -> float:
    # Equal-frequency bins keep calibration robust under imbalance.
    df = pd.DataFrame({"y": y_true.to_numpy().astype(float), "p": y_prob.astype(float)})
    df["bin"] = pd.qcut(df["p"], q=bins, labels=False, duplicates="drop")
    ece = 0.0
    total = len(df)
    if total == 0:
        return float("nan")
    for _, grp in df.groupby("bin"):
        w = len(grp) / total
        ece += w * abs(float(grp["p"].mean()) - float(grp["y"].mean()))
    return float(ece)


@dataclass
class BacktestArtifacts:
    stability_path: str
    drift_path: str
    label_rate_path: str


def run_rolling_origin_backtest(
    dataset: pd.DataFrame,
    date_col: str = "event_week",
    selection_metric: str = "avg_precision",
    random_state: int = 42,
    model_name: str | None = "lightgbm",
    time_series_only: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Train up to week t, test on week t+1, repeat across available weeks."""
    data = dataset.copy()
    data[date_col] = pd.to_datetime(data[date_col], errors="coerce")
    data = data.dropna(subset=[date_col]).sort_values(date_col)

    weeks = sorted(pd.Series(data[date_col].dt.date.unique()).tolist())
    if len(weeks) < 3:
        raise ValueError("Need at least 3 distinct weeks for rolling-origin backtest")

    stability_rows: list[dict[str, Any]] = []

    for i in range(1, len(weeks) - 0):
        train_weeks = weeks[:i]
        test_week = weeks[i]

        train_part = data[data[date_col].dt.date.isin(train_weeks)]
        test_part = data[data[date_col].dt.date == test_week]
        if train_part.empty or test_part.empty:
            continue

        y_train = train_part["is_churned"].astype(int)
        y_test = test_part["is_churned"].astype(int)
        if y_train.nunique() < 2:
            logger.warning(f"Skipping test week {test_week}: training has one class")
            continue

        X_train = train_part.drop(columns=["is_churned"])
        X_test = test_part.drop(columns=["is_churned"])

        preprocessor = _build_preprocessor(X_train)
        candidates = _candidate_models(random_state=random_state)
        chosen = model_name if model_name in candidates else next(iter(candidates.keys()))
        pipeline = Pipeline(steps=[("prep", preprocessor), ("model", candidates[chosen])])
        pipeline.fit(X_train, y_train)
        probs = pipeline.predict_proba(X_test)[:, 1]
        has_two_classes = y_test.nunique() > 1

        stability_rows.append(
            {
                "test_week": str(test_week),
                "train_start_week": str(train_weeks[0]),
                "train_end_week": str(train_weeks[-1]),
                "train_rows": int(len(train_part)),
                "test_rows": int(len(test_part)),
                "model_used": chosen,
                "positive_rate_test": float(y_test.mean()),
                "roc_auc": float(roc_auc_score(y_test, probs)) if has_two_classes else np.nan,
                "pr_auc": float(average_precision_score(y_test, probs)) if int(y_test.sum()) > 0 else np.nan,
                "precision_at_500": _precision_at_k(y_test, probs, k=500),
                "brier_score": float(brier_score_loss(y_test, probs)),
                "ece_10": _ece_score(y_test, probs, bins=10),
            }
        )

    stability_df = pd.DataFrame(stability_rows)

    if time_series_only:
        label_rate_df = (
            data.assign(event_week=data[date_col].dt.date.astype(str))
            .groupby(["event_week"], as_index=False)
            .agg(rows=("is_churned", "size"), positive_rate=("is_churned", "mean"))
        )
    else:
        label_rate_df = (
            data.assign(
                event_week=data[date_col].dt.date.astype(str),
                glovo_country_code=data.get("glovo_country_code", "UNKNOWN"),
                segment=data.get("segment", "unknown"),
            )
            .groupby(["event_week", "glovo_country_code", "segment"], as_index=False)
            .agg(rows=("is_churned", "size"), positive_rate=("is_churned", "mean"))
        )

    numeric_cols = [
        c
        for c in data.select_dtypes(include=["number", "bool"]).columns
        if c not in {"is_churned"}
    ]
    drift_rows: list[dict[str, Any]] = []
    if time_series_only:
        weekly_stats = data.groupby([date_col], as_index=False)[numeric_cols].mean(numeric_only=True)
        weekly_stats = weekly_stats.sort_values([date_col])

        prev = None
        for _, row in weekly_stats.iterrows():
            if prev is None:
                prev = row
                continue
            diffs = []
            for c in numeric_cols:
                a = float(prev[c]) if pd.notna(prev[c]) else np.nan
                b = float(row[c]) if pd.notna(row[c]) else np.nan
                if np.isfinite(a) and np.isfinite(b):
                    diffs.append(abs(b - a))
            drift_rows.append(
                {
                    "event_week": str(pd.Timestamp(row[date_col]).date()),
                    "feature_count_compared": int(len(diffs)),
                    "feature_drift_mean_abs": float(np.mean(diffs)) if diffs else np.nan,
                    "feature_drift_max_abs": float(np.max(diffs)) if diffs else np.nan,
                }
            )
            prev = row
    else:
        grp_cols = [date_col, "glovo_country_code", "segment"]
        for col in ["glovo_country_code", "segment"]:
            if col not in data.columns:
                data[col] = "unknown"

        weekly_stats = data.groupby(grp_cols, as_index=False)[numeric_cols].mean(numeric_only=True)
        weekly_stats = weekly_stats.sort_values(["glovo_country_code", "segment", date_col])

        for (country, segment), part in weekly_stats.groupby(["glovo_country_code", "segment"]):
            part = part.sort_values(date_col)
            prev = None
            for _, row in part.iterrows():
                if prev is None:
                    prev = row
                    continue
                diffs = []
                for c in numeric_cols:
                    a = float(prev[c]) if pd.notna(prev[c]) else np.nan
                    b = float(row[c]) if pd.notna(row[c]) else np.nan
                    if np.isfinite(a) and np.isfinite(b):
                        diffs.append(abs(b - a))
                drift_rows.append(
                    {
                        "event_week": str(pd.Timestamp(row[date_col]).date()),
                        "glovo_country_code": country,
                        "segment": segment,
                        "feature_count_compared": int(len(diffs)),
                        "feature_drift_mean_abs": float(np.mean(diffs)) if diffs else np.nan,
                        "feature_drift_max_abs": float(np.max(diffs)) if diffs else np.nan,
                    }
                )
                prev = row

    drift_df = pd.DataFrame(drift_rows)
    return stability_df, drift_df, label_rate_df


def save_backtest_artifacts(
    stability_df: pd.DataFrame,
    drift_df: pd.DataFrame,
    label_rate_df: pd.DataFrame,
    out_dir: str = "reports",
    prefix: str = "phase12",
) -> BacktestArtifacts:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    stability_path = str(Path(out_dir) / f"{prefix}_rolling_origin_stability.csv")
    drift_path = str(Path(out_dir) / f"{prefix}_feature_drift_by_week.csv")
    label_rate_path = str(Path(out_dir) / f"{prefix}_label_rate_drift_by_week.csv")

    stability_df.to_csv(stability_path, index=False)
    drift_df.to_csv(drift_path, index=False)
    label_rate_df.to_csv(label_rate_path, index=False)

    logger.info(f"Saved rolling-origin stability -> {stability_path}")
    logger.info(f"Saved feature drift report -> {drift_path}")
    logger.info(f"Saved label-rate drift report -> {label_rate_path}")

    return BacktestArtifacts(
        stability_path=stability_path,
        drift_path=drift_path,
        label_rate_path=label_rate_path,
    )
