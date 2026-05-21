"""
Example: build weekly top-risk payload, call GEM, post to webhook.

Usage:
  set GEMINI_API_KEY=...
  set CHURN_ACTIONS_WEBHOOK_URL=https://your.webhook/endpoint
    c:/Users/OndrejSedlacik/glovo-rider-churn-ml/.venv/Scripts/python.exe scripts/example_weekly_gem_webhook.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.integrations.gem_client import build_gem_prompt, call_gem
from src.integrations.gem_webhook_dispatch import build_webhook_payload, post_webhook
from src.models.train import load_model, load_phase12_forward_dataset


CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Earnings Health": (
        "earnings",
        "cpo",
        "eph",
        "city_median_earnings",
    ),
    "Workload and Slot Access": (
        "hours_worked",
        "all_shifts",
        "shifts_done",
        "slot_gap",
        "total_orders_cpo",
    ),
    "Reliability and Friction": (
        "no_shows",
        "perc_reas",
        "at_customer_time",
        "at_vendor_time",
        "cdt",
        "distance",
    ),
    "Support and Experience": (
        "contacts",
        "compliance",
        "avg_sat_score",
        "batch",
        "stacking",
        "bw_orders",
    ),
    "Momentum and Deterioration": (
        "wow_delta",
        "wow_pct_change",
        "trend_slope_8w",
    ),
    "Context and Seasonality": (
        "holiday",
        "season",
        "city_median",
    ),
}


PROTECTIVE_HIGH_KEYWORDS = (
    "earnings",
    "total_orders",
    "hours_worked",
    "all_shifts",
    "shifts_done",
    "avg_sat_score",
)


OWNER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Planning": ("slot", "forecast", "capacity", "peak"),
    "Compliance": ("compliance", "violation", "fraud", "fail rate", "appeal"),
    "Rider Support": ("contact", "liveops", "support", "rsat", "retrain"),
    "Finance": ("bonus", "earnings", "payment", "quest", "loyalty"),
    "City Ops": ("distribution", "vendor", "assignment", "distance", "waiting"),
}


METRIC_MATCH_KEYWORDS: dict[str, tuple[str, ...]] = {
    "orders": ("orders", "total_orders_cpo", "bw_orders"),
    "earnings": ("earnings", "cpo", "eph", "epd", "epw"),
    "hours": ("hours_worked", "hours"),
    "slot": ("slot", "all_shifts", "shifts_done", "slot_gap"),
    "stack": ("stacking", "batch"),
    "contact": ("contacts", "support", "rsat", "cr"),
    "compliance": ("compliance", "violation", "no_shows", "perc_reas", "fail_rate", "fraud"),
    "distance": ("distance", "sp_distance", "pd_distance", "at_vendor_time", "at_customer_time", "cdt"),
    "weather": ("bw_orders", "bad weather", "rain"),
}


def _find_col(df: pd.DataFrame, candidates: list[str], fallback: str) -> str:
    for c in candidates:
        if c in df.columns:
            return c
    return fallback


def _load_action_plan_rows() -> list[dict[str, Any]]:
    path = os.getenv(
        "CHURN_ACTION_PLAN_CSV",
        "c:/Users/OndrejSedlacik/Downloads/Rider Churn reasons and action plan - Sheet1.csv",
    )
    p = Path(path)
    if not p.exists():
        return []

    actions = pd.read_csv(p)
    actions.columns = [str(c).strip() for c in actions.columns]

    out: list[dict[str, Any]] = []
    for _, row in actions.iterrows():
        action_txt = str(row.get("Action plan", "")).strip()
        if not action_txt:
            continue
        out.append(
            {
                "impact": str(row.get("Impact", "Unknown")).strip() or "Unknown",
                "metric": str(row.get("Metrics", "Unknown")).strip() or "Unknown",
                "reason": str(row.get("Reasons to churn", "")).strip(),
                "action": action_txt,
                "estimated_cost": str(row.get("Estimated cost of action plan", "Unknown")).strip() or "Unknown",
                "owner": "City Ops",
            }
        )

    for entry in out:
        action_text = f"{entry.get('metric', '')} {entry.get('action', '')}".lower()
        for owner, keys in OWNER_KEYWORDS.items():
            if any(k in action_text for k in keys):
                entry["owner"] = owner
                break

    return out


def _build_feature_contributions(weekly: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    numeric = weekly.select_dtypes(include=["number", "bool"]).copy()
    drop_cols = [
        c
        for c in [
            "is_churned",
            "churn_probability",
            "risk_rank",
            "tenure_days",
        ]
        if c in numeric.columns
    ]
    numeric = numeric.drop(columns=drop_cols, errors="ignore")

    z = (numeric - numeric.mean()) / (numeric.std(ddof=0).replace(0, np.nan))
    z = z.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    direction = pd.Series(1.0, index=z.columns)
    for col in z.columns:
        if any(k in col.lower() for k in PROTECTIVE_HIGH_KEYWORDS):
            direction[col] = -1.0

    contrib = z.mul(direction, axis=1)
    return contrib, list(contrib.columns)


def _category_scores(row: pd.Series, feature_cols: list[str]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        cols = [c for c in feature_cols if any(k in c.lower() for k in keywords)]
        if not cols:
            scores[cat] = 0.0
            continue
        vals = row[cols].clip(lower=0)
        scores[cat] = float(vals.mean())
    return scores


def _top_features(row: pd.Series, top_n: int = 5) -> list[dict[str, Any]]:
    ordered = row.sort_values(ascending=False).head(top_n)
    return [
        {"feature": str(idx), "impact_score": float(val)}
        for idx, val in ordered.items()
        if float(val) > 0
    ]


def _metric_token_matches(text: str) -> set[str]:
    t = text.lower()
    matched: set[str] = set()
    for token, keys in METRIC_MATCH_KEYWORDS.items():
        if any(k in t for k in keys):
            matched.add(token)
    return matched


def _select_playbook_candidates(
    action_plan_rows: list[dict[str, Any]],
    dominant_categories: list[dict[str, Any]],
    top_feature_rows: list[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    category_tokens = _metric_token_matches(" ".join([c.get("category", "") for c in dominant_categories]))
    feature_tokens = _metric_token_matches(" ".join([f.get("feature", "") for f in top_feature_rows]))

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in action_plan_rows:
        impact = str(row.get("impact", ""))
        metric = str(row.get("metric", ""))
        action_text = str(row.get("action", ""))

        row_tokens = _metric_token_matches(f"{impact} {metric} {action_text}")
        token_overlap = len((category_tokens | feature_tokens) & row_tokens)

        cost = str(row.get("estimated_cost", "Unknown")).strip().lower()
        cost_bonus = 0.5 if cost == "low" else (0.2 if cost == "medium" else 0.0)
        score = float(token_overlap) + cost_bonus
        scored.append((score, row))

    scored.sort(key=lambda x: x[0], reverse=True)

    chosen: list[dict[str, Any]] = []
    seen_actions: set[str] = set()
    for score, row in scored:
        action = str(row.get("action", "")).strip()
        if not action or action in seen_actions:
            continue
        enriched = dict(row)
        enriched["match_score"] = float(score)
        chosen.append(enriched)
        seen_actions.add(action)
        if len(chosen) >= limit:
            break
    return chosen


def _aggregate_city_feature_signals(city_df: pd.DataFrame, top_n: int = 5) -> list[dict[str, Any]]:
    scores: dict[str, float] = {}
    if "top_feature_contributions" not in city_df.columns:
        return []

    for raw in city_df["top_feature_contributions"].dropna().astype(str):
        try:
            arr = json.loads(raw)
        except Exception:
            continue
        if not isinstance(arr, list):
            continue
        for item in arr:
            if not isinstance(item, dict):
                continue
            feat = str(item.get("feature", "")).strip()
            val = float(item.get("impact_score", 0.0) or 0.0)
            if not feat or val <= 0:
                continue
            scores[feat] = scores.get(feat, 0.0) + val

    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return [{"feature": k, "impact_score": float(v)} for k, v in ordered]


def _build_country_context(
    weekly: pd.DataFrame,
    country_col: str,
    city_col: str,
    action_plan_rows: list[dict[str, Any]],
    top_pct: float = 0.10,
) -> dict[str, Any]:
    parts: list[dict[str, Any]] = []

    for country, part in weekly.groupby(country_col):
        part = part.sort_values("churn_probability", ascending=False).reset_index(drop=True)
        n_top = max(1, int(np.ceil(len(part) * top_pct)))
        top_decile = part.head(n_top).copy()

        city_counts = (
            top_decile.groupby(city_col, as_index=False)
            .agg(riders_in_top_decile=("rider_id", "size"))
            .sort_values("riders_in_top_decile", ascending=False)
            .head(3)
        )

        top_decile_city_set = set(city_counts[city_col].astype(str).tolist())
        city_slice = top_decile[top_decile[city_col].astype(str).isin(top_decile_city_set)].copy()

        by_city: list[dict[str, Any]] = []
        for _, crow in city_counts.iterrows():
            city = str(crow[city_col])
            city_df = city_slice[city_slice[city_col].astype(str) == city].copy()
            if city_df.empty:
                continue

            cat_agg = {}
            for cat in CATEGORY_KEYWORDS.keys():
                if f"cat__{cat}" in city_df.columns:
                    cat_agg[cat] = float(city_df[f"cat__{cat}"].mean())
                else:
                    cat_agg[cat] = 0.0
            top_categories = sorted(cat_agg.items(), key=lambda x: x[1], reverse=True)[:3]

            city_top_features = _aggregate_city_feature_signals(city_df, top_n=5)

            dominant_categories_payload = [
                {"category": cat, "impact_score": float(score)} for cat, score in top_categories
            ]
            action_matches = _select_playbook_candidates(
                action_plan_rows=action_plan_rows,
                dominant_categories=dominant_categories_payload,
                top_feature_rows=city_top_features,
                limit=5,
            )

            newbie_count = int((city_df.get("segment", pd.Series([], dtype=object)).astype(str).str.lower() == "newbie").sum())
            gac_per_newbie = float(os.getenv("NEWBIE_GAC_VALUE", "0") or 0)
            gac_exposure = float(newbie_count) * gac_per_newbie

            by_city.append(
                {
                    "city": city,
                    "riders_in_top_decile": int(crow["riders_in_top_decile"]),
                    "share_of_country_top_decile": float(crow["riders_in_top_decile"] / max(1, n_top)),
                    "avg_churn_probability": float(city_df["churn_probability"].mean()),
                    "dominant_categories": [
                        {"category": cat, "impact_score": float(score)} for cat, score in top_categories
                    ],
                    "city_top_feature_signals": city_top_features,
                    "playbook_candidates": action_matches[:5],
                    "newbie_high_risk_count": newbie_count,
                    "newbie_gac_exposure": gac_exposure,
                    "sample_riders": city_df[
                        [
                            c
                            for c in [
                                "rider_id",
                                "segment",
                                "tenure_days",
                                "churn_probability",
                                "risk_rank",
                                "top_feature_contributions",
                            ]
                            if c in city_df.columns
                        ]
                    ]
                    .head(25)
                    .to_dict(orient="records"),
                }
            )

        parts.append(
            {
                "country": str(country),
                "top_decile_pct": top_pct,
                "total_riders_week": int(len(part)),
                "top_decile_riders": int(n_top),
                "top_3_cities": by_city,
            }
        )

    if not parts:
        return {}
    return parts[0]


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

    country_col = _find_col(weekly, ["glovo_country_code", "country", "country_code"], "glovo_country_code")
    city_col = _find_col(weekly, ["city_code", "city", "city_name"], "city_code")
    if country_col not in weekly.columns:
        weekly[country_col] = "PL"
    if city_col not in weekly.columns:
        weekly[city_col] = "UNKNOWN_CITY"

    model = load_model(pconf.get("model_output_path", "models/phase12_churn_model.joblib"))
    probs = model.predict_proba(weekly.drop(columns=["is_churned"]))[:, 1]
    weekly["churn_probability"] = probs
    weekly = weekly.sort_values("churn_probability", ascending=False).reset_index(drop=True)
    weekly["risk_rank"] = weekly.index + 1

    contrib, feature_cols = _build_feature_contributions(weekly)
    weekly["top_feature_contributions"] = [json.dumps(_top_features(contrib.iloc[i]), ensure_ascii=True) for i in range(len(contrib))]
    for cat in CATEGORY_KEYWORDS.keys():
        weekly[f"cat__{cat}"] = [
            _category_scores(contrib.iloc[i], feature_cols).get(cat, 0.0)
            for i in range(len(contrib))
        ]

    action_plan_rows = _load_action_plan_rows()
    country_context = _build_country_context(
        weekly=weekly,
        country_col=country_col,
        city_col=city_col,
        action_plan_rows=action_plan_rows,
        top_pct=float(os.getenv("COUNTRY_TOP_RISK_PCT", "0.10")),
    )

    country_context["run_week"] = run_week
    country_context["category_framework"] = list(CATEGORY_KEYWORDS.keys())

    prompt = build_gem_prompt(
        country_context=country_context,
        action_plan_rows=action_plan_rows,
        country_code=str(country_context.get("country", "PL")),
        intervention_capacity=int(os.getenv("INTERVENTION_CAPACITY", "500")),
    )
    if os.getenv("GEMINI_API_KEY"):
        gem_output = call_gem(prompt)
    else:
        gem_output = {
            "run_summary": {
                "country": str(country_context.get("country", "PL")),
                "run_week": run_week,
                "capacity": int(os.getenv("INTERVENTION_CAPACITY", "500")),
                "cities_analyzed": len(country_context.get("top_3_cities", [])),
                "notes": "Dry run: GEMINI_API_KEY not set, no model response generated.",
            },
            "top_cities": country_context.get("top_3_cities", []),
            "execution_notes": [
                "Set GEMINI_API_KEY to enable generated narratives and recommended playbook output.",
            ],
            "debug_prompt_preview": prompt[:2000],
        }

    metrics = json.loads(Path("models/phase12_metrics.json").read_text(encoding="utf-8"))
    payload = build_webhook_payload(
        country_code=str(country_context.get("country", "PL")),
        run_week=run_week,
        model_name=metrics["best_model"],
        model_metrics=metrics["metrics"][metrics["best_model"]],
        ranking_snapshot={
            "k_values": metrics.get("ranking_k_values", [100, 250, 500, 1000]),
            "top_decile_pct": float(os.getenv("COUNTRY_TOP_RISK_PCT", "0.10")),
            "top_3_cities": country_context.get("top_3_cities", []),
        },
        gem_output=gem_output,
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
