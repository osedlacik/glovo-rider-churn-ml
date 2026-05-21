"""
Phase 1/2 model training utilities.

Phase 1:
- Train quick baseline models from exported CSV datasets.

Phase 2:
- Time-aware validation split when enough temporal anchors are present.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from loguru import logger
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


def _to_str_id(df: pd.DataFrame, col: str = "rider_id") -> pd.DataFrame:
    out = df.copy()
    if col in out.columns:
        out[col] = out[col].astype(str)
    return out


def _weekly_prefixes(columns: list[str]) -> list[str]:
    found: dict[str, set[int]] = {}
    for col in columns:
        match = re.match(r"^(.*)_W([0-7])$", col)
        if match:
            prefix = match.group(1)
            # Skip already-derived features; only raw weekly measures should be expanded.
            if (
                "_delta_" in prefix
                or "_wow_delta_" in prefix
                or "_trend_" in prefix
            ):
                continue
            idx = int(match.group(2))
            found.setdefault(prefix, set()).add(idx)
    return sorted([k for k, v in found.items() if len(v) >= 2])


def add_wow_trends(df: pd.DataFrame) -> pd.DataFrame:
    """Add week-over-week deltas and 8-week trend slopes for *_W0..*_W7 columns."""
    out = df.copy()
    prefixes = _weekly_prefixes(list(out.columns))

    for prefix in prefixes:
        week_cols = [f"{prefix}_W{i}" for i in range(8) if f"{prefix}_W{i}" in out.columns]

        # WoW deltas: W0-W1, W1-W2, ... W6-W7
        for i in range(0, 7):
            c0 = f"{prefix}_W{i}"
            c1 = f"{prefix}_W{i+1}"
            if c0 in out.columns and c1 in out.columns:
                out[f"{prefix}_wow_delta_W{i}_W{i+1}"] = out[c0] - out[c1]

        # Trend slope over chronological order W7 -> W0
        if len(week_cols) >= 3:
            chrono_cols = [f"{prefix}_W{i}" for i in range(7, -1, -1) if f"{prefix}_W{i}" in out.columns]
            arr = out[chrono_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
            x = np.arange(len(chrono_cols), dtype=float)

            slopes = np.full(arr.shape[0], np.nan)
            for r in range(arr.shape[0]):
                y = arr[r]
                mask = np.isfinite(y)
                if mask.sum() >= 3:
                    slopes[r] = np.polyfit(x[mask], y[mask], 1)[0]
            out[f"{prefix}_trend_slope_8w"] = slopes

    return out


def add_normalized_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add normalized per-order ratios for count/cost features."""
    out = df.copy()
    denom_prefix = "total_orders_cpo"

    numerators = [
        "total_earnings",
        "total_bw_orders",
        "no_shows",
        "shifts_done",
        "all_shifts",
        "contacts_total_tickets",
        "compliance_total_violations",
    ]

    for i in range(8):
        denom_col = f"{denom_prefix}_W{i}"
        if denom_col not in out.columns:
            continue
        denom = pd.to_numeric(out[denom_col], errors="coerce")
        safe_denom = denom.replace(0, np.nan)

        for num_prefix in numerators:
            num_col = f"{num_prefix}_W{i}"
            if num_col in out.columns:
                num = pd.to_numeric(out[num_col], errors="coerce")
                out[f"{num_prefix}_per_order_W{i}"] = num / safe_denom

    return out


def load_phase12_dataset(features_csv: str, snapshot_csv: str) -> pd.DataFrame:
    """Load and merge exported features with snapshot labels."""
    features = pd.read_csv(features_csv)
    snapshot = pd.read_csv(snapshot_csv)

    features = _to_str_id(features)
    snapshot = _to_str_id(snapshot)

    if "is_churned" not in snapshot.columns:
        if "churn" in snapshot.columns:
            snapshot["is_churned"] = snapshot["churn"]
        else:
            raise ValueError("Snapshot CSV must include is_churned or churn column")

    keep_cols = [
        c
        for c in [
            "rider_id",
            "is_churned",
            "segment",
            "tenure_days",
        ]
        if c in snapshot.columns
    ]

    labeled = snapshot[keep_cols].copy()
    merged = labeled.merge(features, on="rider_id", how="left", suffixes=("", "_feat"))

    merged["is_churned"] = pd.to_numeric(merged["is_churned"], errors="coerce").fillna(0).astype(int)
    if "week_of_churn" in merged.columns:
        merged["week_of_churn"] = pd.to_datetime(merged["week_of_churn"], errors="coerce")
    if "anchor_week" in merged.columns:
        merged["anchor_week"] = pd.to_datetime(merged["anchor_week"], errors="coerce")

    # Remove columns that leak target timing or churn-label construction logic.
    leakage_cols = [
        "days_since_last_slot",
        "week_of_churn",
        "week_of_churn_feat",
        "last_order_date",
    ]
    merged = merged.drop(columns=[c for c in leakage_cols if c in merged.columns], errors="ignore")

    merged = add_normalized_features(merged)
    merged = add_wow_trends(merged)

    return merged


def load_phase12_forward_dataset(
    features_csv: str,
    snapshot_csv: str,
    horizon_weeks: int = 2,
    max_event_offset: int = 6,
) -> pd.DataFrame:
    """
    Build a forward-looking panel dataset with multiple observation events per rider.

    For each rider and each event time t, label y=1 if churn happens within (t, t+horizon_weeks].
    """
    features = pd.read_csv(features_csv)
    snapshot = pd.read_csv(snapshot_csv)

    features = _to_str_id(features)
    snapshot = _to_str_id(snapshot)

    if "anchor_week" not in features.columns:
        raise ValueError("Features CSV must include anchor_week for forward event construction")

    features["anchor_week"] = pd.to_datetime(features["anchor_week"], errors="coerce")
    if "week_of_churn" in features.columns:
        features["week_of_churn"] = pd.to_datetime(features["week_of_churn"], errors="coerce")
    else:
        features["week_of_churn"] = pd.NaT

    keep_snapshot_cols = [c for c in ["rider_id", "segment", "tenure_days"] if c in snapshot.columns]
    snapshot_meta = snapshot[keep_snapshot_cols].drop_duplicates(subset=["rider_id"])
    base = features.merge(snapshot_meta, on="rider_id", how="left", suffixes=("", "_snap"))

    weekly_cols = [c for c in base.columns if re.match(r"^(.*)_W([0-7])$", c)]
    prefixes = _weekly_prefixes(weekly_cols)

    global_anchor = pd.to_datetime(base["anchor_week"], errors="coerce").max()
    if pd.isna(global_anchor):
        raise ValueError("anchor_week contains only null values")

    panel_parts: list[pd.DataFrame] = []
    event_offsets = list(range(0, max(0, int(max_event_offset)) + 1))

    for offset in event_offsets:
        event = pd.DataFrame(index=base.index)
        event["rider_id"] = base["rider_id"]

        if "segment" in base.columns:
            event["segment"] = base["segment"]
        if "tenure_days" in base.columns:
            event["tenure_days"] = pd.to_numeric(base["tenure_days"], errors="coerce")

        event_week = base["anchor_week"] - pd.to_timedelta(offset * 7, unit="D")
        event["event_week"] = event_week

        if "week_of_churn" in base.columns:
            week_diff = ((base["week_of_churn"] - event_week).dt.days // 7)
            label = ((week_diff > 0) & (week_diff <= int(horizon_weeks))).astype(int)
            at_risk = base["week_of_churn"].isna() | (event_week < base["week_of_churn"])
        else:
            label = pd.Series(0, index=base.index, dtype=int)
            at_risk = pd.Series(True, index=base.index, dtype=bool)

        # Right-censoring guard: only keep events whose outcome window is fully observed.
        fully_observed = event_week <= (global_anchor - pd.to_timedelta(int(horizon_weeks) * 7, unit="D"))

        event["is_churned"] = label

        for prefix in prefixes:
            for lag in range(8):
                src_week = offset + lag
                src_col = f"{prefix}_W{src_week}"
                dst_col = f"{prefix}_W{lag}"
                if src_col in base.columns:
                    event[dst_col] = base[src_col]
                elif dst_col not in event.columns:
                    event[dst_col] = np.nan

        mask = at_risk & fully_observed & event_week.notna()
        panel_parts.append(event.loc[mask].copy())

    if not panel_parts:
        raise ValueError("No forward events were generated; check anchor_week/horizon settings")

    panel = pd.concat(panel_parts, ignore_index=True)
    panel = panel.drop_duplicates(subset=["rider_id", "event_week"])

    panel = add_normalized_features(panel)
    panel = add_wow_trends(panel)

    return panel


def create_time_aware_split(
    data: pd.DataFrame,
    date_col: str = "week_of_churn",
    test_size: float = 0.2,
    random_state: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """
    Phase 2 split: prefer time-aware split, fallback to stratified random split.
    """
    y = data["is_churned"].astype(int)
    X = data.drop(columns=["is_churned"])

    # Time-based split only if enough non-null anchors exist.
    if date_col in X.columns:
        dates = pd.to_datetime(X[date_col], errors="coerce")
        non_null_ratio = float(dates.notna().mean())

        if non_null_ratio >= 0.6:
            cutoff = dates.quantile(1 - test_size)
            train_mask = dates < cutoff
            test_mask = dates >= cutoff

            # Guardrails: non-empty split and both classes on each side.
            if train_mask.sum() > 0 and test_mask.sum() > 0:
                y_train = y.loc[train_mask]
                y_test = y.loc[test_mask]
                if y_train.nunique() >= 2 and y_test.nunique() >= 2:
                    logger.info(
                        "Using time-aware split on {} (cutoff={})".format(
                            date_col,
                            pd.Timestamp(cutoff).date(),
                        )
                    )
                    return X.loc[train_mask], X.loc[test_mask], y_train, y_test

    logger.warning("Falling back to stratified random split (insufficient temporal anchors)")
    return train_test_split(
        X,
        y,
        test_size=test_size,
        random_state=random_state,
        stratify=y if y.nunique() > 1 else None,
    )


def _build_preprocessor(X: pd.DataFrame) -> ColumnTransformer:
    numeric_cols = X.select_dtypes(include=["number", "bool"]).columns.tolist()
    categorical_cols = [c for c in X.columns if c not in numeric_cols]

    # Drop high-cardinality IDs/time anchors from model input (kept for split/metadata only)
    drop_cols = [c for c in ["rider_id", "week_of_churn", "anchor_week", "event_week"] if c in X.columns]
    numeric_cols = [c for c in numeric_cols if c not in drop_cols]
    categorical_cols = [c for c in categorical_cols if c not in drop_cols]

    numeric_pipe = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )
    categorical_pipe = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OneHotEncoder(handle_unknown="ignore")),
        ]
    )

    return ColumnTransformer(
        transformers=[
            ("num", numeric_pipe, numeric_cols),
            ("cat", categorical_pipe, categorical_cols),
        ],
        remainder="drop",
    )


def _candidate_models(random_state: int = 42) -> dict[str, Any]:
    return {
        "logistic_regression": LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            random_state=random_state,
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=400,
            max_depth=12,
            class_weight="balanced_subsample",
            random_state=random_state,
            n_jobs=-1,
        ),
    }


def train_models(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    random_state: int = 42,
) -> dict[str, dict[str, Any]]:
    """Train baseline models with normalized preprocessing."""
    if y_train.nunique() < 2:
        raise ValueError("Training split has a single class; cannot train a binary classifier")

    preprocessor = _build_preprocessor(X_train)
    models = _candidate_models(random_state=random_state)

    results: dict[str, dict[str, Any]] = {}
    for name, estimator in models.items():
        logger.info(f"Training {name}...")
        pipeline = Pipeline(steps=[("prep", preprocessor), ("model", estimator)])
        pipeline.fit(X_train, y_train)

        y_prob = pipeline.predict_proba(X_test)[:, 1]
        y_pred = (y_prob >= 0.5).astype(int)

        metrics = {
            "roc_auc": float(roc_auc_score(y_test, y_prob)) if y_test.nunique() > 1 else float("nan"),
            "avg_precision": float(average_precision_score(y_test, y_prob)),
            "positive_rate_test": float(np.mean(y_test)),
            "positive_rate_pred": float(np.mean(y_pred)),
        }

        logger.info(
            f"{name} -> ROC-AUC={metrics['roc_auc']:.4f}, PR-AUC={metrics['avg_precision']:.4f}"
        )

        results[name] = {
            "model": pipeline,
            "metrics": metrics,
            "y_prob": y_prob,
        }

    return results


def select_best_model(results: dict[str, dict[str, Any]], metric: str = "avg_precision") -> tuple[str, Any]:
    """Select champion model by metric (PR-AUC default)."""
    best_name = max(results, key=lambda k: results[k]["metrics"].get(metric, float("-inf")))
    logger.info(f"Selected best model: {best_name} ({metric}={results[best_name]['metrics'][metric]:.4f})")
    return best_name, results[best_name]["model"]


def save_model(model: Any, path: str = "models/churn_model.joblib") -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out)
    logger.info(f"Model saved to {out}")


def load_model(path: str = "models/churn_model.joblib") -> Any:
    return joblib.load(path)
