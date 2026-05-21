"""
Example: build weekly top-risk payload, call Gemini, post to webhook.

Usage:
  set GEMINI_API_KEY=...
  set CHURN_ACTIONS_WEBHOOK_URL=https://your.webhook/endpoint
  c:/Users/OndrejSedlacik/glovo-rider-churn-ml/.venv/Scripts/python.exe scripts/example_weekly_gemini_webhook.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from src.integrations.gemini_client import build_gemini_prompt, call_gemini
from src.integrations.webhook_dispatch import build_webhook_payload, post_webhook
from src.models.train import load_model, load_phase12_forward_dataset


def main() -> None:
    cfg = yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))
    pconf = cfg["phase12"]

    df = load_phase12_forward_dataset(
        pconf["features_csv"],
        pconf["snapshot_csv"],
        horizon_weeks=int(pconf.get("horizon_weeks", 2)),
        max_event_offset=int(pconf.get("max_event_offset", 6)),
    )
    df["event_week"] = df["event_week"].astype("datetime64[ns]")

    run_week = str(df["event_week"].max().date())
    weekly = df[df["event_week"] == df["event_week"].max()].copy()

    model = load_model(pconf.get("model_output_path", "models/phase12_churn_model.joblib"))
    probs = model.predict_proba(weekly.drop(columns=["is_churned"]))[:, 1]
    weekly["churn_probability"] = probs
    weekly = weekly.sort_values("churn_probability", ascending=False).reset_index(drop=True)
    weekly["risk_rank"] = weekly.index + 1

    fields = [
        "rider_id",
        "segment",
        "tenure_days",
        "churn_probability",
        "risk_rank",
        "total_orders_cpo_W0",
        "total_earnings_W0",
        "hours_worked_W0",
        "earnings_per_hour_W0",
        "slot_gap_mean_days_W0",
        "compliance_total_violations_W0",
        "contacts_total_tickets_W0",
    ]
    top_batch = weekly[fields].head(20).to_dict(orient="records")

    prompt = build_gemini_prompt(
        weekly_batch=top_batch,
        country_code="PL",
        city_code=None,
        intervention_capacity=500,
    )
    gemini_output = call_gemini(prompt)

    metrics = json.loads(Path("models/phase12_metrics.json").read_text(encoding="utf-8"))
    payload = build_webhook_payload(
        country_code="PL",
        run_week=run_week,
        model_name=metrics["best_model"],
        model_metrics=metrics["metrics"][metrics["best_model"]],
        ranking_snapshot={"k_values": metrics.get("ranking_k_values", [100, 250, 500, 1000])},
        gemini_output=gemini_output,
    )

    webhook = os.getenv("CHURN_ACTIONS_WEBHOOK_URL")
    if not webhook:
        print(json.dumps(payload, indent=2))
        print("CHURN_ACTIONS_WEBHOOK_URL not set; printed payload locally.")
        return

    result = post_webhook(webhook, payload)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
