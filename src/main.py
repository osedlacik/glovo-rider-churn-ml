"""
Main pipeline entrypoint.

Orchestrates: data extraction → feature engineering → prediction → output.
"""

from loguru import logger
import yaml
import json
from pathlib import Path

from src.data.bq_extract import build_dataset
from src.data.labeling import label_churn, create_train_test_split
from src.features.build_features import build_feature_matrix
from src.models.train import train_models, select_best_model, save_model
from src.models.train import load_phase12_dataset, load_phase12_forward_dataset, create_time_aware_split
from src.models.backtest import run_rolling_origin_backtest, save_backtest_artifacts
from src.models.evaluate import (
    ranking_metrics_at_k,
    threshold_capacity_table,
    weekly_backtest_table,
    calibration_table,
)
from src.models.predict import predict_churn, explain_predictions, get_city_summary
from src.actions.recommendations import recommend_actions
from src.integrations.slack import send_weekly_alert


def load_config(path: str = "config/config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def run_training_pipeline(config: dict):
    """Full training pipeline: extract → features → train → evaluate → save."""
    logger.info("=== TRAINING PIPELINE ===")

    for city in config["cities"]:
        logger.info(f"Processing {city}...")

        # 1. Extract data from BigQuery
        raw_data = build_dataset(city, config)

        # 2. Label churn
        labeled = label_churn(
            raw_data["slots"],
            raw_data["courier_base"],
            threshold_active_days=config["churn"]["threshold_active_days"],
            threshold_newbie_days=config["churn"]["threshold_newbie_days"],
        )

        # 3. Build features
        features = build_feature_matrix(raw_data)

        # 4. Train/test split
        X_train, X_test, y_train, y_test = create_train_test_split(
            features.merge(labeled[["courier_id", "is_churned"]], on="courier_id"),
            test_size=config["model"]["test_size"],
        )

        # 5. Train models
        results = train_models(X_train, y_train, X_test, y_test)

        # 6. Select best and save
        best_name, best_model = select_best_model(results)
        save_model(best_model, f"models/{city}_churn_model.joblib")

    logger.info("=== TRAINING COMPLETE ===")


def run_prediction_pipeline(config: dict):
    """Score current fleet and generate alerts."""
    logger.info("=== PREDICTION PIPELINE ===")

    all_city_summaries = {}

    for city in config["cities"]:
        logger.info(f"Scoring {city}...")

        # 1. Extract current data
        raw_data = build_dataset(city, config)

        # 2. Build features
        features = build_feature_matrix(raw_data)

        # 3. Predict
        predictions = predict_churn(
            features,
            model_path=f"models/{city}_churn_model.joblib",
        )

        # 4. Explain top risks
        explanations = explain_predictions(
            features,
            model_path=f"models/{city}_churn_model.joblib",
        )

        # 5. Recommend actions
        actions = recommend_actions(predictions, explanations)

        # 6. City summary
        summary = get_city_summary(predictions)
        all_city_summaries[city] = summary

    # 7. Send Slack alerts (grouped by country)
    # TODO: Group cities by country and send one alert per country
    # send_weekly_alert(country, city_summaries)

    logger.info("=== PREDICTION COMPLETE ===")
    return all_city_summaries


def run_phase12_training(config: dict) -> None:
    """Phase 1/2 training from exported CSVs with time-aware validation."""
    logger.info("=== PHASE 1/2 TRAINING ===")
    pconf = config.get("phase12", {})

    features_csv = pconf.get("features_csv", "data/exports/churn_riders_features_8w_poland_2026_to_today.csv")
    snapshot_csv = pconf.get("snapshot_csv", "data/exports/churn_riders_snapshot_poland_2026_to_today.csv")
    model_out = pconf.get("model_output_path", "models/phase12_churn_model.joblib")
    metrics_out = pconf.get("metrics_output_path", "models/phase12_metrics.json")
    ranking_out = pconf.get("ranking_metrics_output_path", "reports/phase12_ranking_metrics.csv")
    threshold_out = pconf.get("threshold_policy_output_path", "reports/phase12_threshold_policy.csv")
    weekly_backtest_out = pconf.get("weekly_backtest_output_path", "reports/phase12_weekly_backtest.csv")
    calibration_out = pconf.get("calibration_output_path", "reports/phase12_calibration_table.csv")
    k_values = [int(k) for k in pconf.get("ranking_k_values", [100, 250, 500, 1000])]

    use_forward_events = bool(pconf.get("use_forward_events", True))
    if use_forward_events:
        dataset = load_phase12_forward_dataset(
            features_csv=features_csv,
            snapshot_csv=snapshot_csv,
            horizon_weeks=int(pconf.get("horizon_weeks", 2)),
            max_event_offset=int(pconf.get("max_event_offset", 6)),
        )
    else:
        dataset = load_phase12_dataset(features_csv=features_csv, snapshot_csv=snapshot_csv)
    logger.info(f"Loaded merged dataset with {len(dataset):,} rows and {len(dataset.columns):,} columns")

    X_train, X_test, y_train, y_test = create_time_aware_split(
        dataset,
        date_col=pconf.get("date_col", "event_week" if use_forward_events else "anchor_week"),
        test_size=float(pconf.get("test_size", 0.2)),
        random_state=int(pconf.get("random_state", 42)),
    )

    results = train_models(
        X_train,
        y_train,
        X_test,
        y_test,
        random_state=int(pconf.get("random_state", 42)),
    )

    best_name, best_model = select_best_model(results, metric=pconf.get("selection_metric", "avg_precision"))
    save_model(best_model, model_out)

    best_probs = results[best_name]["y_prob"]

    ranking_df = ranking_metrics_at_k(y_test, best_probs, k_values=k_values)
    threshold_df = threshold_capacity_table(y_test, best_probs)
    calibration_df = calibration_table(y_test, best_probs, bins=int(pconf.get("calibration_bins", 10)))

    ranking_path = Path(ranking_out)
    ranking_path.parent.mkdir(parents=True, exist_ok=True)
    ranking_df.to_csv(ranking_path, index=False)

    threshold_path = Path(threshold_out)
    threshold_path.parent.mkdir(parents=True, exist_ok=True)
    threshold_df.to_csv(threshold_path, index=False)

    calibration_path = Path(calibration_out)
    calibration_path.parent.mkdir(parents=True, exist_ok=True)
    calibration_df.to_csv(calibration_path, index=False)

    if "event_week" in X_test.columns:
        weekly_backtest_df = weekly_backtest_table(y_test, best_probs, X_test["event_week"])
        weekly_path = Path(weekly_backtest_out)
        weekly_path.parent.mkdir(parents=True, exist_ok=True)
        weekly_backtest_df.to_csv(weekly_path, index=False)
    else:
        weekly_backtest_df = None

    summary = {
        "best_model": best_name,
        "selection_metric": pconf.get("selection_metric", "avg_precision"),
        "metrics": {k: v["metrics"] for k, v in results.items()},
        "train_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "train_positive_rate": float(y_train.mean()),
        "test_positive_rate": float(y_test.mean()),
        "ranking_k_values": k_values,
        "ranking_metrics_output_path": str(ranking_path),
        "threshold_policy_output_path": str(threshold_path),
        "weekly_backtest_output_path": str(weekly_backtest_out) if weekly_backtest_df is not None else None,
        "calibration_output_path": str(calibration_path),
    }

    out = Path(metrics_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info(f"Metrics saved to {metrics_out}")
    logger.info("=== PHASE 1/2 TRAINING COMPLETE ===")


def run_phase12_backtest(config: dict) -> None:
    """Rolling-origin temporal validation + drift diagnostics."""
    logger.info("=== PHASE 1/2 ROLLING BACKTEST ===")
    pconf = config.get("phase12", {})

    dataset = load_phase12_forward_dataset(
        features_csv=pconf.get("features_csv", "data/exports/churn_riders_features_8w_poland_2026_to_today.csv"),
        snapshot_csv=pconf.get("snapshot_csv", "data/exports/churn_riders_snapshot_poland_2026_to_today.csv"),
        horizon_weeks=int(pconf.get("horizon_weeks", 2)),
        max_event_offset=int(pconf.get("max_event_offset", 6)),
    )

    stability_df, drift_df, label_rate_df = run_rolling_origin_backtest(
        dataset=dataset,
        date_col=pconf.get("date_col", "event_week"),
        selection_metric=pconf.get("selection_metric", "avg_precision"),
        random_state=int(pconf.get("random_state", 42)),
        model_name=pconf.get("backtest_model_name", "lightgbm"),
        time_series_only=bool(pconf.get("backtest_time_series_only", True)),
    )

    save_backtest_artifacts(
        stability_df=stability_df,
        drift_df=drift_df,
        label_rate_df=label_rate_df,
        out_dir=pconf.get("backtest_output_dir", "reports"),
        prefix=pconf.get("backtest_output_prefix", "phase12"),
    )
    logger.info("=== PHASE 1/2 ROLLING BACKTEST COMPLETE ===")


if __name__ == "__main__":
    config = load_config()

    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "train":
        run_training_pipeline(config)
    elif len(sys.argv) > 1 and sys.argv[1] == "train_phase12":
        run_phase12_training(config)
    elif len(sys.argv) > 1 and sys.argv[1] == "backtest_phase12":
        run_phase12_backtest(config)
    else:
        run_prediction_pipeline(config)
