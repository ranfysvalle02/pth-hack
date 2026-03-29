"""Defender -- blue team detection engine.

Subscribes to the dashboard WebSocket, evaluates incoming events against
Sigma-style rules, and fires detection_alert events back to the dashboard
with a small delay simulating realistic detection latency.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(__file__))
from rules.detections import load_rules, evaluate

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://dashboard:8000")
DASHBOARD_WS = os.environ.get("DASHBOARD_WS", "ws://dashboard:8000/ws")
DETECTION_DELAY = float(os.environ.get("DETECTION_DELAY", "0.8"))

rules = load_rules()


def _report(event_type: str, data: dict) -> None:
    payload = json.dumps({
        "type": event_type,
        "data": data,
        "timestamp": time.time(),
        "source": "defender",
    }).encode()
    req = Request(
        f"{DASHBOARD_URL}/api/events",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urlopen(req, timeout=3)
    except Exception:
        pass


async def _connect_and_watch():
    """Connect to dashboard WebSocket and evaluate events in real time."""
    import websockets

    while True:
        try:
            async with websockets.connect(DASHBOARD_WS) as ws:
                print("[defender] connected to dashboard WebSocket", flush=True)
                _report("defender_online", {"rules_loaded": len(rules)})

                async for message in ws:
                    try:
                        event = json.loads(message)
                    except json.JSONDecodeError:
                        continue

                    if event.get("type", "").startswith("detection_"):
                        continue
                    if event.get("source") == "defender":
                        continue
                    if event.get("_replay"):
                        continue

                    alerts = evaluate(event, rules)
                    for alert in alerts:
                        await asyncio.sleep(DETECTION_DELAY)
                        _report("detection_alert", alert)

        except Exception as e:
            print(f"[defender] connection error: {e}, reconnecting...", flush=True)
            await asyncio.sleep(2)


def main():
    print("[defender] starting detection engine", flush=True)
    asyncio.run(_connect_and_watch())


if __name__ == "__main__":
    main()
