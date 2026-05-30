#!/usr/bin/env bash
# Removes the login service installed by setup-local.sh.
set -euo pipefail

PLIST_LABEL="com.gemini-dashboard.backend"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

if [ ! -f "$PLIST_PATH" ]; then
    echo "Service is not installed — nothing to do."
    exit 0
fi

launchctl unload "$PLIST_PATH" 2>/dev/null || true
rm -f "$PLIST_PATH"

echo "✓ Service uninstalled. The backend will no longer auto-start on login."
echo ""
echo "  Your .venv and .env are untouched."
echo "  To start the server manually: cd backend && ../.venv/bin/uvicorn main:app"
