#!/usr/bin/env bash
set -euo pipefail

REPO=/repos/internal-app.git
TMP=/tmp/init-repo

git config --global --add safe.directory "$REPO"
git config --global init.defaultBranch main

git init --bare "$REPO"
chown -R git:git "$REPO"

git clone "$REPO" "$TMP"
cd "$TMP"

git config user.email "admin@internal.dev"
git config user.name "Admin"

cat > requirements.txt <<'EOF'
flask>=3.0
requests>=2.31
gunicorn>=21.2
EOF

cat > README.md <<'EOF'
# internal-app

Internal application service. Do not share externally.
EOF

cat > package.json <<'EOF'
{
  "name": "internal-app",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "start": "node app.js"
  }
}
EOF

cat > app.js <<'EOF'
console.log("internal-app booted");
EOF

git add -A
git commit -m "initial commit"
git branch -M main
git push origin main

rm -rf "$TMP"
chown -R git:git "$REPO"
