# Agent Handoff: Forward Churn Modeling (Poland)

## Scope Completed
- Converted churn modeling from a leakage-prone cross-sectional setup to a forward-looking event-panel setup.
- Switched from one row per rider to multiple observation events per rider (`t`, `t-1w`, ..., `t-6w`).
- Implemented forward labels: `is_churned = 1` if churn occurs within `(t, t+h]` where `h = horizon_weeks`.
- Enforced time-aware split by `event_week`.

## Why This Was Needed
- Prior setup produced unrealistically high metrics due to leakage-like predictors:
  - `days_since_last_slot`
  - churn date features (`week_of_churn`, `week_of_churn_feat`)
  - date-cardinality artifacts (`anchor_week` categories)
- The new setup aligns with production intent: predict future churn risk from past behavior.

## Key File Changes
- `src/models/train.py`
  - Added `load_phase12_forward_dataset(...)`.
  - Creates panel rows across multiple event offsets.
  - Applies right-censoring guard so label windows are fully observed.
  - Keeps `event_week` for splitting.
  - Drops leakage columns from model inputs.
  - Preprocessor now excludes `event_week` (and other ID/time anchors) from training features.
- `src/main.py`
  - `run_phase12_training` now supports `use_forward_events` mode (default used in config).
  - Uses `event_week` for split when in forward mode.
- `config/config.yaml`
  - `phase12.use_forward_events: true`
  - `phase12.horizon_weeks: 2`
  - `phase12.max_event_offset: 6`
  - `phase12.date_col: event_week`
- `config/config.example.yaml`
  - Updated to match forward-event defaults.

## Data/Label Setup in Current Run
- Features file: `data/exports/churn_riders_features_8w_poland_2026_to_today.csv`
- Snapshot labels file: `data/exports/churn_riders_snapshot_poland_2026_to_today.csv`
- Event panel stats:
  - Rows: `164,901`
  - Columns: `597`
  - Event range: `2025-11-17` to `2026-05-04`
  - Mean events per rider: `5.55`
  - 90th percentile events per rider: `6`
  - Positive label rate (panel): `0.1981`

## Last Validation Results
Saved in `models/phase12_metrics.json`.
- Best model: `random_forest`
- Logistic Regression:
  - ROC-AUC: `0.7094`
  - PR-AUC: `0.1027`
- Random Forest:
  - ROC-AUC: `0.7732`
  - PR-AUC: `0.1227`
- Split behavior:
  - Time-aware split applied on `event_week`.
  - Logged cutoff around `2026-04-20`.

## Known Caveats
- Performance warnings in pandas due to many iterative column inserts during WoW/trend feature generation (non-fatal, optimization opportunity).
- `utm_source` sparsity can trigger sklearn imputer warning.
- Class balance differs by time split; monitor calibration and thresholding by week.

## Recommended Next Steps
1. Add ranking metrics for operations:
   - Precision@K, Recall@K, Lift@K.
2. Add weekly backtest table:
   - metrics per `event_week` cohort for drift/stability tracking.
3. Improve feature construction performance:
   - replace repeated column inserts with batched `pd.concat`.
4. Add threshold policy artifact:
   - map score thresholds to intervention capacity (for example top 500 riders/week).
5. Optionally try gradient boosting baseline (XGBoost/LightGBM) after confirming no leakage regressions.

## How To Re-Run
- Train:
  - `python -m src.main train_phase12`
- Recompute metrics and model artifact:
  - outputs to `models/phase12_metrics.json` and `models/phase12_churn_model.joblib`

## Commit Context
- Main implementation commit introduced forward-event framing and leakage-safe training behavior.
- This handoff document is intended for continuity by the next agent without requiring full chat history.
