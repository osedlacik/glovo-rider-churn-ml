"""
Webhook payload skeleton for Gemini churn recommendations.
"""

from __future__ import annotations

import json
from datetime import datetime, UTC
from typing import Any
from urllib import request


def build_webhook_payload(
    country_code: str,
    run_week: str,
    model_name: str,
    model_metrics: dict[str, Any],
    ranking_snapshot: dict[str, Any],
    gemini_output: dict[str, Any],
) -> dict[str, Any]:
    """Compose the JSON payload sent to downstream ops webhook."""
    return {
        "event_type": "weekly_rider_churn_actions",
        "sent_at_utc": datetime.now(UTC).isoformat(),
        "country_code": country_code,
        "run_week": run_week,
        "model": {
            "name": model_name,
            "metrics": model_metrics,
            "ranking_snapshot": ranking_snapshot,
        },
        "gemini": gemini_output,
    }


def post_webhook(webhook_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Send payload as JSON to a webhook endpoint and return response metadata."""
    req = request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with request.urlopen(req, timeout=30) as resp:
        response_body = resp.read().decode("utf-8")
        return {
            "status_code": resp.status,
            "response_body": response_body,
        }
