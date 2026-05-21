"""
Gemini integration skeleton for churn action recommendations.

This module prepares a grounded prompt from weekly model outputs and calls
Gemini via REST. Keep the API key in env var GEMINI_API_KEY.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib import request


GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"


def churn_knowledge_base() -> str:
    """Domain context injected into the model prompt."""
    return """
Churn program context:
- Objective: identify riders likely to churn in next 2 weeks and recommend concrete retention actions.
- Churn label: no slots booked for 14 days (newbies may have different sensitivity in ops logic).
- Segment definitions:
  - newbie: < 30 days since first order
  - active: >= 30 days since first order
- Core model outputs:
  - churn_probability (0-1)
  - risk_rank (lower is riskier)
  - top-decile policy inside country (top 10% highest-risk riders)
- Category framework for driver explanations:
  - Earnings Health
  - Workload and Slot Access
  - Reliability and Friction
  - Support and Experience
  - Momentum and Deterioration
  - Context and Seasonality
- Action principles:
  - prefer low-cost, testable actions first
  - map actions to owner: City Ops, Planning, Rider Support, Compliance, Finance
  - use the provided action-plan sheet rows as operational playbook options
  - avoid unsupported claims; use only provided rider metrics and domain rules
- Output must be concise and operational, with explicit next steps and expected impact.
""".strip()


def build_gem_prompt(
    country_context: dict[str, Any],
    action_plan_rows: list[dict[str, Any]],
    country_code: str,
    intervention_capacity: int = 500,
) -> str:
    """Create a single prompt for weekly city-level action planning run."""

    return f"""
You are a supply operations action planner for rider retention.

{churn_knowledge_base()}

Weekly run metadata:
- country={country_code}
- intervention_capacity={intervention_capacity}
- top_decile_city_count={len(country_context.get('top_3_cities', []))}

Country-level risk context (JSON):
{json.dumps(country_context, ensure_ascii=True)}

Action-plan knowledge base rows (JSON):
{json.dumps(action_plan_rows, ensure_ascii=True)}

Task:
1) Focus only on the top 3 impacted cities from the provided top-decile portfolio.
2) For each city, identify dominant churn categories and link them to explicit actions from the action-plan rows.
3) Prioritize low-cost, high-feasibility actions first, but include medium/high-cost actions when impact is materially higher.
4) For newbie riders, include a brief GAC-aware note (risk to payback if churn persists).
5) Return valid JSON only (no markdown) using this schema:
{{
  "run_summary": {{
    "country": "...",
    "run_week": "YYYY-MM-DD",
    "capacity": 500,
    "cities_analyzed": 3,
    "notes": "..."
  }},
  "top_cities": [
    {{
      "city": "...",
      "alert_level": "critical|high|medium",
      "impact_volume": 0,
      "share_of_country_top_decile": 0.0,
      "primary_fleet_drivers": ["...", "..."],
      "recommended_playbook": [
        {{
          "impact": "Earnings|Rider Experience|Rider engagement|Fraud",
          "metric": "...",
          "action": "...",
          "estimated_cost": "Low|Medium|High|Unknown",
          "owner": "City Ops|Planning|Support|Compliance|Finance",
          "urgency": "high|medium|low"
        }}
      ],
      "newbie_gac_note": "..."
    }}
  ],
  "execution_notes": ["...", "..."]
}}
""".strip()


def call_gem(prompt: str, model: str = "gemini-2.0-flash") -> dict[str, Any]:
    """Call Gemini REST API and return parsed JSON response.

    This is a skeleton: keep retries, validation, and guardrails in caller logic.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    url = GEMINI_ENDPOINT.format(model=model, api_key=api_key)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.9,
            "responseMimeType": "application/json",
        },
    }

    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    text = (
        body.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "{}")
    )
    return json.loads(text)
