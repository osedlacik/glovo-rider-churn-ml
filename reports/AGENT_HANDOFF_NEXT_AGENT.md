# Agent Handoff: Rider Churn ML + City Action Planning

Date: 2026-05-21
Owner handoff: new implementation includes weekly temporal validation, city-prioritized risk slicing, and Gemini/webhook integration with action-plan crosswalk.

## 1) Current Objective State

Implemented:
- Rolling-origin temporal backtest pipeline (train up to week t, test on t+1).
- Time-series stability/drift artifacts saved to reports.
- Gemini prompt and integration refined to city-level operational planning.
- Top-decile policy by country with top-3 impacted cities selection.
- Deterministic category-to-action matching (keyword mapping from model signals to action sheet rows).
- Newbie GAC exposure note support via env var.

## 2) Key Model Metrics (latest champion)

Source: models/phase12_metrics.json

Champion model:
- best_model: lightgbm
- selection_metric (PR-AUC): 0.1833891607332753
- ROC-AUC: 0.7932792129896247

Dataset stats:
- train_rows: 122863
- test_rows: 42038
- train_positive_rate: 0.25040085298259035
- test_positive_rate: 0.04536371854036824

Other candidate PR-AUCs:
- logistic_regression: 0.09706340951243417
- random_forest: 0.11268632598598018
- xgboost: 0.1385662716949699

## 3) Validation Outputs

Generated reports:
- reports/phase12_ranking_metrics.csv
- reports/phase12_threshold_policy.csv
- reports/phase12_weekly_backtest.csv
- reports/phase12_calibration_table.csv
- reports/phase12_rolling_origin_stability.csv
- reports/phase12_feature_drift_by_week.csv
- reports/phase12_label_rate_drift_by_week.csv

Rolling-origin run command:
- c:/Users/OndrejSedlacik/glovo-rider-churn-ml/.venv/Scripts/python.exe -m src.main backtest_phase12

## 4) Gemini + Webhook Pipeline

Core files:
- src/integrations/gem_client.py
- src/integrations/gem_webhook_dispatch.py
- scripts/example_weekly_gem_webhook.py

Pipeline behavior:
1. Load forward dataset and score current run week.
2. Rank riders by churn probability.
3. Keep top 10% highest risk riders inside country.
4. Pick top 3 cities with largest rider counts in that top-decile slice.
5. Compute category impact aggregates + top feature signals.
6. Deterministically match action-plan rows via keyword overlap (metrics + category + feature tokens), with low-cost preference.
7. Build Gemini prompt with context + action knowledge rows.
8. Post resulting payload to webhook.

## 5) Runtime Configuration

Required env vars for live run:
- GEMINI_API_KEY
- CHURN_ACTIONS_WEBHOOK_URL

Optional env vars:
- CHURN_ACTION_PLAN_CSV (default points to Downloads CSV path)
- COUNTRY_TOP_RISK_PCT (default 0.10)
- INTERVENTION_CAPACITY (default 500)
- NEWBIE_GAC_VALUE (default 0)

Dry run mode:
- If GEMINI_API_KEY is missing, script returns structured fallback output with prompt preview and does not call Gemini.
- If CHURN_ACTIONS_WEBHOOK_URL is missing, payload is printed locally.

## 6) Demo Runbook

From repo root:
1. Set project import path:
   - set PYTHONPATH=.
2. (Optional) dry demo without external calls:
   - set GEMINI_API_KEY=
   - set CHURN_ACTIONS_WEBHOOK_URL=
3. Run:
   - c:/Users/OndrejSedlacik/glovo-rider-churn-ml/.venv/Scripts/python.exe scripts/example_weekly_gem_webhook.py

Live demo:
1. set GEMINI_API_KEY=<your_key>
2. set CHURN_ACTIONS_WEBHOOK_URL=<https_endpoint>
3. optional: set NEWBIE_GAC_VALUE=<country_gac_value>
4. run the same command above
5. verify webhook response status code in terminal

## 7) Action Plan Forward

Near-term (next sprint):
- Replace heuristic contribution proxy with SHAP values for rider and city-level explainability.
- Add strict metric taxonomy mapping table (feature -> business metric) in config for less keyword dependence.
- Add city-level minimum sample guardrails (avoid unstable city recommendations on very low volume).
- Add payload snapshot persistence to reports/ for QA and auditing.
- Reduce load_phase12_forward_dataset fragmentation warnings (vectorized construction).

Mid-term:
- Multi-country rollout and segmentation templates.
- A/B test framework for recommended actions and measured retention uplift.
- Cost-aware optimization layer (action budget constraints per city).
