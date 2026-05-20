"""
Slack integration for weekly churn alerts.

Sends per-country summary with top cities, at-risk rider counts,
and proposed action items.
"""

import json
from slack_sdk.webhook import WebhookClient
from loguru import logger
import yaml


def load_slack_config(config_path: str = "config/config.yaml") -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)["slack"]


def format_city_alert(city_summary: dict) -> dict:
    """
    Format a single city's churn summary into a Slack Block Kit message section.

    Args:
        city_summary: dict with city, total_couriers, high_risk_count, 
                     high_risk_pct, top_reasons, recommended_actions

    Returns:
        Slack Block Kit section block
    """
    # TODO: Build Slack block
    # Example output:
    # 🟡 Warsaw — 23 couriers at risk (6.8% of fleet)
    #   Top drivers: declining earnings (12), high wait times (8), no-shows increasing (3)
    #   Suggested: Review vendor wait times, open peak slots, re-engagement bonus

    block = {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                f"*{city_summary['city']}* — "
                f"{city_summary['high_risk_count']} couriers at risk "
                f"({city_summary['high_risk_pct']:.1f}% of fleet)\n"
                f"_Top drivers:_ {', '.join(city_summary.get('top_reasons', ['TBD']))}\n"
                f"_Suggested:_ {', '.join(city_summary.get('actions', ['TBD']))}"
            ),
        },
    }
    return block


def send_weekly_alert(
    country: str,
    city_summaries: list,
    webhook_url: str = None,
    config_path: str = "config/config.yaml",
) -> bool:
    """
    Send weekly Slack alert for a country with all city summaries.

    Message structure:
        📊 Weekly Churn Alert — {Country}
        {date range}

        🟡 City A — X couriers at risk (Y% of fleet)
          Top drivers: ...
          Suggested actions: ...

        🟢 City B — Low risk (Z% below threshold)

        📋 Full report: [link to dashboard]
    """
    if webhook_url is None:
        config = load_slack_config(config_path)
        webhook_url = config["webhook_url"]

    # Build message blocks
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📊 Weekly Churn Alert — {country}",
            },
        },
        {"type": "divider"},
    ]

    for city in city_summaries:
        blocks.append(format_city_alert(city))

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "📋 *<dashboard_url|View Full Dashboard>*",
        },
    })

    # Send via webhook
    try:
        webhook = WebhookClient(webhook_url)
        response = webhook.send(blocks=blocks)
        logger.info(f"Slack alert sent for {country}: {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Failed to send Slack alert for {country}: {e}")
        return False
