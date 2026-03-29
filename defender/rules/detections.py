"""Detection engine -- matches event stream against Sigma-style rules."""
from __future__ import annotations

import json
from pathlib import Path

RULES_PATH = Path(__file__).parent / "sigma_rules.json"


def load_rules() -> list[dict]:
    return json.loads(RULES_PATH.read_text())


def evaluate(event: dict, rules: list[dict]) -> list[dict]:
    """Return list of detection alerts triggered by this event."""
    alerts = []
    event_type = event.get("type", "")
    event_data = event.get("data", {})

    for rule in rules:
        if event_type not in rule.get("match_event_types", []):
            continue

        field_match = True
        for field, expected in rule.get("match_fields", {}).items():
            if event_data.get(field) != expected:
                field_match = False
                break

        if field_match:
            alerts.append({
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                "description": rule["description"],
                "severity": rule["severity"],
                "mitre_technique": rule["mitre_technique"],
                "mitre_name": rule["mitre_name"],
                "matched_event": event_type,
                "matched_source": event.get("source", ""),
            })

    return alerts
