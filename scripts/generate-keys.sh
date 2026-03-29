#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[*] Generating 4096-bit RSA keypair for demo..."
openssl genrsa -out "$SCRIPT_DIR/demo_private.pem" 4096 2>/dev/null
openssl rsa -in "$SCRIPT_DIR/demo_private.pem" -pubout -out "$SCRIPT_DIR/demo_public.pem" 2>/dev/null

echo "[+] Private key: $SCRIPT_DIR/demo_private.pem"
echo "[+] Public key:  $SCRIPT_DIR/demo_public.pem"
echo "[*] These are DEMO-ONLY keys. Do not use for anything real."
