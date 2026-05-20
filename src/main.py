"""
Main pipeline entrypoint.

Orchestrates: data extraction → feature engineering → prediction → output.
"""

from loguru import logger
import yaml

from src.data.bq_extract import build_dataset
from src.data.labeling import label_churn, create_train_test_split
from src.features.build_features import build_feature_matrix
from src.models.train import train_models, select_best_model, save_model
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


if __name__ == "__main__":
    config = load_config()

    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "train":
        run_training_pipeline(config)
    else:
        run_prediction_pipeline(config)
