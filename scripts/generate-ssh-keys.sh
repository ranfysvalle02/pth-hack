#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[*] Generating ED25519 SSH keypairs for demo..."
ssh-keygen -t ed25519 -f "$SCRIPT_DIR/demo_ssh_victim1" -N "" -C "victim1@demo" 2>/dev/null
ssh-keygen -t ed25519 -f "$SCRIPT_DIR/demo_ssh_victim2" -N "" -C "victim2@demo" 2>/dev/null

echo "[+] victim-1 key: $SCRIPT_DIR/demo_ssh_victim1"
echo "[+] victim-2 key: $SCRIPT_DIR/demo_ssh_victim2"
echo "[*] These are DEMO-ONLY keys. Do not use for anything real."
