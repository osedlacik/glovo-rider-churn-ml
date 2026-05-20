# Glovo Rider Churn Prediction

**Supply Operations Hackathon — May 2026**  
**Team 2** | Sponsored by Matías Salvati

## Problem

We cannot predict which couriers are about to leave until they already have. This model identifies early warning signals and gives ops teams actionable, ranked alerts before churn happens.

## Churn Definition

> A courier who delivered at least one order during the observation period but has **not booked any slots for 14 consecutive days** is classified as churned.  
> For newbies (< 30 days since hired): churn threshold is **7 days**.

## Courier Segments

| Segment | Definition |
|---------|-----------|
| Newbie | ≥1 order AND < 30 days since hired |
| Active | ≥ 30 days since hired, regular activity |
| Veteran | Long-tenured, stable patterns |

## Project Structure

```
├── config/             # Configuration files (BQ, model params, cities)
├── src/
│   ├── data/           # BigQuery extraction & data pipeline
│   ├── features/       # Feature engineering per category
│   ├── models/         # Training, prediction, evaluation
│   ├── actions/        # Churn action recommendations (AI-powered)
│   └── integrations/   # Slack alerts
├── dashboard/          # Streamlit frontend
├── notebooks/          # EDA and analysis
├── tests/              # Unit tests
└── data/               # Local data cache (gitignored)
```

## Outputs

1. **Weekly Slack alert** per country: top cities with riders at risk + proposed actions
2. **Dashboard** with detailed metrics, ranked rider list, churn probability, reasons
3. **Rider-level predictions**: ID, churn probability, top contributing signals, recommended intervention

## Quick Start

```bash
pip install -r requirements.txt
# Configure BigQuery credentials
cp config/config.example.yaml config/config.yaml
# Run pipeline
python -m src.main
```

## Team

| Role | Person |
|------|--------|
| Team Lead & Storyteller | TBD |
| Model Architect | TBD |
| Prototype Builder | TBD |
| Data Designer | TBD |
| Domain Validator | TBD |
| Impact Analyst | TBD |
