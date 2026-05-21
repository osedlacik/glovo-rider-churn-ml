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
  - top-K policy (for example top 100, 250, 500, 1000)
- Important feature families:
  - earnings dynamics (earnings_per_hour, city-relative earnings gap)
  - engagement and recency (orders, slots, gap between worked slots)
  - support/compliance friction (contacts, violations)
  - seasonality/holiday context
- Action principles:
  - prefer low-cost, testable actions first
  - map actions to owner: City Ops, Planning, Rider Support, Compliance, Finance
  - avoid unsupported claims; use only provided rider metrics and domain rules
- Output must be concise and operational, with explicit next steps and expected impact.
""".strip()


def build_gemini_prompt(
    weekly_batch: list[dict[str, Any]],
    country_code: str,
    city_code: str | None = None,
    intervention_capacity: int = 500,
) -> str:
    """Create a single prompt for a weekly action planning run."""
    city_part = f" city={city_code}," if city_code else ""

    return f"""
You are a rider retention copilot for supply operations.

{churn_knowledge_base()}

Weekly run metadata:
- country={country_code},{city_part}
- intervention_capacity={intervention_capacity}
- records_in_batch={len(weekly_batch)}

Input rider batch (JSON):
{json.dumps(weekly_batch, ensure_ascii=True)}

Task:
1) For each rider, infer likely churn drivers from provided metrics.
2) Recommend up to 3 specific actions with owner and urgency.
3) Provide a short rationale and confidence.
4) Return valid JSON only (no markdown) using this schema:
{{
  "run_summary": {{
    "country": "...",
    "city": "...",
    "capacity": 500,
    "recommended_interventions": 500,
    "notes": "..."
  }},
  "riders": [
    {{
      "rider_id": "...",
      "risk": {{"probability": 0.0, "rank": 1}},
      "drivers": ["...", "...", "..."],
      "actions": [
        {{"owner": "City Ops", "action": "...", "urgency": "high|medium|low", "expected_effect": "..."}}
      ],
      "confidence": "high|medium|low"
    }}
  ]
}}
""".strip()


def call_gemini(prompt: str, model: str = "gemini-2.0-flash") -> dict[str, Any]:
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
