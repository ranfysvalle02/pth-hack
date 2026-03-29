"""CI Runner -- simulated build agent that auto-installs from requirements.txt.

Polls the internal git repo for changes. When requirements.txt is modified,
runs a simulated CI pipeline: pip install in a fresh venv, which triggers the
.pth payload. Demonstrates how automated infrastructure gets compromised.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from urllib.request import Request, urlopen

from fastapi import FastAPI

app = FastAPI()

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://dashboard:8000")
GIT_SERVER = os.environ.get("GIT_SERVER", "git-server")
GIT_REPO_PATH = os.environ.get("GIT_REPO_PATH", "/repos/internal-app.git")
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://registry:8080/simple/")
POLL_INTERVAL = int(os.environ.get("GIT_POLL_INTERVAL", "5"))
SOURCE = "ci-runner"

CLONE_DIR = "/tmp/ci-workspace"
RUNNER_STATE = {"status": "waiting", "last_commit": None, "infected": False}

SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
GIT_SSH_CMD = f"ssh -i {SSH_KEY} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

SITE_PKG = None


def _get_site_packages():
    global SITE_PKG
    if SITE_PKG is None:
        SITE_PKG = subprocess.run(
            [sys.executable, "-c", "import site; print(site.getsitepackages()[0])"],
            capture_output=True, text=True,
            env={**os.environ, "_PTH_GUARD": "1"},
        ).stdout.strip()
    return SITE_PKG


def _report(event_type, data=None):
    payload = json.dumps({
        "type": event_type,
        "data": data or {},
        "timestamp": time.time(),
        "source": SOURCE,
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


def _git_env():
    return {**os.environ, "GIT_SSH_COMMAND": GIT_SSH_CMD}


def _clone_repo():
    clone_url = f"git@{GIT_SERVER}:{GIT_REPO_PATH}"
    for attempt in range(120):
        if os.path.exists(CLONE_DIR):
            shutil.rmtree(CLONE_DIR)
        result = subprocess.run(
            ["git", "clone", clone_url, CLONE_DIR],
            capture_output=True, text=True, env=_git_env(), timeout=15,
        )
        if result.returncode == 0:
            _report("ci_repo_cloned", {"repo": clone_url})
            head = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=CLONE_DIR, capture_output=True, text=True, env=_git_env(),
            ).stdout.strip()
            RUNNER_STATE["last_commit"] = head
            RUNNER_STATE["status"] = "watching"
            return True
        time.sleep(2)
    _report("ci_clone_failed", {"error": "Exhausted retries"})
    return False


def _check_for_updates():
    env = _git_env()
    subprocess.run(["git", "fetch", "origin"], cwd=CLONE_DIR,
                   capture_output=True, env=env, timeout=15)
    head_local = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=CLONE_DIR,
        capture_output=True, text=True, env=env,
    ).stdout.strip()
    head_remote = subprocess.run(
        ["git", "rev-parse", "origin/main"], cwd=CLONE_DIR,
        capture_output=True, text=True, env=env,
    ).stdout.strip()

    if head_local == head_remote:
        return False

    _report("ci_new_commits", {"local": head_local[:7], "remote": head_remote[:7]})
    subprocess.run(["git", "pull", "origin", "main"], cwd=CLONE_DIR,
                   capture_output=True, env=env, timeout=15)
    RUNNER_STATE["last_commit"] = head_remote[:7]

    req_file = os.path.join(CLONE_DIR, "requirements.txt")
    if os.path.exists(req_file):
        with open(req_file) as f:
            contents = f.read()
        if "pyautoconf" in contents:
            _report("ci_poisoned_requirements", {"contents": contents})
            return True
    return False


def _run_pipeline():
    """Simulate a CI build pipeline -- install deps, run tests, trigger .pth."""
    _report("ci_pipeline_triggered", {"message": "CI pipeline started: install + test"})

    _report("ci_build_start", {"message": "pip install -r requirements.txt from internal registry"})
    guarded_env = {**os.environ, "_PTH_GUARD": "1"}
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install",
         "--index-url", REGISTRY_URL,
         "--trusted-host", "registry",
         "--no-deps",
         "pyautoconf"],
        capture_output=True, text=True, timeout=120, env=guarded_env,
    )
    _report("ci_pip_complete", {"stdout": result.stdout[:500], "returncode": result.returncode})

    if result.returncode != 0:
        _report("ci_pip_error", {"stderr": result.stderr[:500]})
        return

    import glob as _glob
    site_pkg = _get_site_packages()
    for pth in _glob.glob(os.path.join(sys.prefix, "pathogen_hook.pth")):
        dest = os.path.join(site_pkg, os.path.basename(pth))
        shutil.move(pth, dest)
        _report("ci_pth_moved", {"from": pth, "to": dest})

    _report("ci_triggering", {"message": "Running test suite (triggers .pth in CI context)"})

    clean_env = {k: v for k, v in os.environ.items() if k != "_PTH_GUARD"}
    clean_env["PAYLOAD_SOURCE"] = SOURCE

    proc = subprocess.Popen(
        [sys.executable, "-c", "print('CI test run: all tests passed')"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=clean_env,
    )

    time.sleep(1)
    pth_path = os.path.join(site_pkg, "pathogen_hook.pth")
    if os.path.exists(pth_path):
        os.remove(pth_path)

    proc.communicate(timeout=120)

    RUNNER_STATE["infected"] = True
    RUNNER_STATE["status"] = "infected"
    _report("ci_build_infected", {
        "message": "CI runner compromised -- build agent credentials stolen",
    })


def _watcher_loop():
    _report("ci_watcher_started", {"message": "CI runner polling for repo changes"})

    if not _clone_repo():
        RUNNER_STATE["status"] = "error"
        return

    while not RUNNER_STATE["infected"]:
        time.sleep(POLL_INTERVAL)
        try:
            if _check_for_updates():
                _run_pipeline()
                break
        except Exception as e:
            _report("ci_watcher_error", {"error": str(e)})


_watcher_thread = None


@app.on_event("startup")
async def startup():
    global _watcher_thread
    _watcher_thread = threading.Thread(target=_watcher_loop, daemon=True)
    _watcher_thread.start()


@app.get("/health")
async def health():
    return {"status": "ok", "runner": RUNNER_STATE}


@app.get("/status")
async def status():
    return RUNNER_STATE
