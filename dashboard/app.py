"""Dashboard backend -- WebSocket hub, event ingest, service health proxy, replay."""
from __future__ import annotations

import asyncio
import json
import os
import time

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

CAPTURES_DIR = os.environ.get("CAPTURES_DIR", "/captures")

# --- WebSocket connection manager ---
connected: list[WebSocket] = []
event_log: list[dict] = []


async def broadcast(event: dict) -> None:
    event_log.append(event)
    dead = []
    payload = json.dumps(event)
    for ws in connected:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connected.remove(ws)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected.append(ws)
    # Send event history to newly connected client
    for evt in event_log:
        try:
            await ws.send_text(json.dumps(evt))
        except Exception:
            break
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in connected:
            connected.remove(ws)


# --- Event ingest (called by victim, c2, payload) ---
@app.post("/api/events")
async def ingest_event(request: Request):
    event = await request.json()
    if "timestamp" not in event:
        event["timestamp"] = time.time()
    await broadcast(event)
    return {"status": "ok"}


# --- Attack control proxy ---
@app.post("/api/attack/start")
async def start_attack():
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            resp = await client.post("http://victim:8000/attack/start")
            return resp.json()
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=502)


@app.post("/api/attack/reset")
async def reset_attack():
    event_log.clear()
    errors = []
    async with httpx.AsyncClient(timeout=5) as client:
        for url in ["http://victim:8000/attack/reset", "http://attacker-c2:9000/reset"]:
            try:
                await client.post(url)
            except Exception as e:
                errors.append(str(e))

    await broadcast({"type": "reset", "data": {}, "timestamp": time.time(), "source": "dashboard"})
    if errors:
        return JSONResponse({"status": "partial_reset", "errors": errors}, status_code=207)
    return {"status": "reset"}


# --- Service health ---
SERVICE_URLS = {
    "registry": "http://registry:8080/health/",
    "victim-1": "http://victim:8000/health",
    "victim-2": "http://victim-2:8001/health",
    "ci_runner": "http://ci-runner:8002/health",
    "attacker_c2": "http://attacker-c2:9000/health",
}


@app.get("/api/status")
async def service_status():
    results = {}
    async with httpx.AsyncClient(timeout=3, verify=False) as client:
        for name, url in SERVICE_URLS.items():
            try:
                resp = await client.get(url)
                results[name] = "ok" if resp.status_code < 500 else "error"
            except Exception:
                results[name] = "unreachable"
    results["dashboard"] = "ok"
    return results


@app.get("/api/events/history")
async def event_history():
    return {"events": event_log}


# --- Replay ---
_replay_task: asyncio.Task | None = None


async def _replay_worker(speed: float):
    if len(event_log) < 2:
        return
    events = list(event_log)
    # Clear UI state via reset, then replay
    await broadcast({"type": "reset", "data": {"replay": True}, "timestamp": time.time(), "source": "dashboard"})
    await asyncio.sleep(0.5)

    t0 = events[0].get("timestamp", 0)
    for evt in events:
        dt = (evt.get("timestamp", 0) - t0) / speed
        if dt > 0:
            await asyncio.sleep(dt)
        t0 = evt.get("timestamp", 0)
        replay_evt = {**evt, "_replay": True}
        payload = json.dumps(replay_evt)
        dead = []
        for ws in connected:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            connected.remove(ws)
    await broadcast({
        "type": "replay_complete",
        "data": {"events_replayed": len(events)},
        "timestamp": time.time(),
        "source": "dashboard",
    })


@app.post("/api/replay/start")
async def start_replay(request: Request):
    global _replay_task
    speed = float(request.query_params.get("speed", "2"))
    if speed < 0.1:
        speed = 0.1
    if speed > 50:
        speed = 50
    if _replay_task and not _replay_task.done():
        _replay_task.cancel()
    _replay_task = asyncio.create_task(_replay_worker(speed))
    return {"status": "replaying", "speed": speed, "events": len(event_log)}


@app.post("/api/replay/stop")
async def stop_replay():
    global _replay_task
    if _replay_task and not _replay_task.done():
        _replay_task.cancel()
        _replay_task = None
        return {"status": "stopped"}
    return {"status": "not_running"}


# --- PCAP download ---
@app.get("/api/pcap/download")
async def download_pcap():
    pcap_path = os.path.join(CAPTURES_DIR, "pathogen.pcap")
    if os.path.exists(pcap_path):
        return FileResponse(
            pcap_path,
            media_type="application/vnd.tcpdump.pcap",
            filename="pathogen.pcap",
        )
    return JSONResponse({"error": "No capture file available yet"}, status_code=404)


# --- Static files ---
@app.get("/")
async def index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
