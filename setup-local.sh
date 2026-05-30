#!/usr/bin/env bash
# One-time setup: installs the backend as a macOS login service.
# Works on any Mac regardless of Python version or username.
set -euo pipefail

# ── Paths (all derived from script location — no hardcoded usernames) ─────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
VENV_DIR="$BACKEND_DIR/.venv"
PLIST_LABEL="com.gemini-dashboard.backend"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
LOG_PATH="$HOME/Library/Logs/gemini-dashboard.log"
ADC_PATH="$HOME/.config/gcloud/application_default_credentials.json"

echo "================================================"
echo "  Workforce IQ Dashboard — Local Setup"
echo "================================================"
echo ""

# ── 1. Check .env exists ──────────────────────────────────────────────────────
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "✗ No .env file found at: $SCRIPT_DIR/.env"
    echo ""
    echo "  Copy the example and fill in your BigQuery details:"
    echo "    cp $SCRIPT_DIR/.env.example $SCRIPT_DIR/.env"
    echo "    # then edit .env: set BIGQUERY_PROJECT_ID, BIGQUERY_DATASET, BIGQUERY_TABLE"
    echo ""
    exit 1
fi
echo "✓ .env found"

# ── 2. Find Python 3.9+ ───────────────────────────────────────────────────────
echo "→ Looking for Python 3.9+..."

PYTHON=""
CANDIDATES=(
    "python3"
    "/opt/homebrew/bin/python3"                   # Homebrew — Apple Silicon
    "/usr/local/bin/python3"                       # Homebrew — Intel
    "/usr/bin/python3"                             # macOS system (Xcode CLT)
    "$HOME/.pyenv/shims/python3"                   # pyenv
    "/opt/homebrew/opt/python@3.12/bin/python3"
    "/opt/homebrew/opt/python@3.11/bin/python3"
    "/opt/homebrew/opt/python@3.10/bin/python3"
    "/opt/homebrew/opt/python@3.9/bin/python3"
    "/usr/local/opt/python@3.12/bin/python3"
    "/usr/local/opt/python@3.11/bin/python3"
    "/usr/local/opt/python@3.10/bin/python3"
    "/usr/local/opt/python@3.9/bin/python3"
)

for candidate in "${CANDIDATES[@]}"; do
    if command -v "$candidate" &>/dev/null 2>&1 || [ -x "$candidate" ]; then
        VERSION=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        MAJOR=$(echo "$VERSION" | cut -d. -f1)
        MINOR=$(echo "$VERSION" | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 9 ]; then
            PYTHON=$(command -v "$candidate" 2>/dev/null || echo "$candidate")
            echo "  Found: $PYTHON (Python $VERSION)"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo ""
    echo "✗ Python 3.9 or higher not found on this machine."
    echo ""
    echo "  Install options:"
    echo "    Homebrew:  brew install python3"
    echo "    Direct:    https://www.python.org/downloads/"
    echo ""
    echo "  After installing, re-run this script."
    exit 1
fi

# ── 3. Create virtual environment ─────────────────────────────────────────────
echo "→ Creating virtual environment..."
if [ -d "$VENV_DIR" ]; then
    echo "  Already exists — recreating to match this Python..."
    rm -rf "$VENV_DIR"
fi
"$PYTHON" -m venv "$VENV_DIR"
echo "  Created at: $VENV_DIR"

# ── 4. Install Python dependencies ────────────────────────────────────────────
echo "→ Installing dependencies (this may take a minute)..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements.txt"
echo "✓ Dependencies installed"

# ── 5. Install Playwright browser (needed for PDF export) ─────────────────────
echo "→ Installing Playwright browser..."
"$VENV_DIR/bin/playwright" install chromium
echo "✓ Playwright ready"

# ── 6. Google authentication (ADC) ────────────────────────────────────────────
echo ""
echo "→ Checking Google credentials..."

if [ -f "$ADC_PATH" ]; then
    echo "✓ Application Default Credentials already configured — skipping."
else
    if command -v gcloud &>/dev/null 2>&1; then
        echo "  Running: gcloud auth application-default login"
        echo "  (A browser window will open — sign in with your Google account)"
        echo ""
        gcloud auth application-default login
        echo ""
        echo "✓ Google credentials configured"
    else
        echo ""
        echo "  ⚠ gcloud CLI not found — BigQuery auth not configured yet."
        echo ""
        echo "  Install gcloud: https://cloud.google.com/sdk/docs/install"
        echo "  Then run once:  gcloud auth application-default login"
        echo ""
    fi
fi

# ── 7. Write launchd plist ────────────────────────────────────────────────────
echo "→ Registering login service..."

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$HOME/Library/Logs"

cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${VENV_DIR}/bin/uvicorn</string>
        <string>main:app</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>8000</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${BACKEND_DIR}</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>${LOG_PATH}</string>

    <key>StandardErrorPath</key>
    <string>${LOG_PATH}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>${HOME}</string>
        <key>PATH</key>
        <string>${VENV_DIR}/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
PLIST

# ── 8. Load the service ───────────────────────────────────────────────────────
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"
echo "✓ Login service registered and started"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "================================================"
echo "  ✓ Setup complete!"
echo "================================================"
echo ""
echo "  The backend is running and will auto-start on every login."
echo ""
echo "  Logs:     tail -f $LOG_PATH"
echo "  Stop:     launchctl unload $PLIST_PATH"
echo "  Start:    launchctl load $PLIST_PATH"
echo "  Remove:   ./uninstall-local.sh"
echo ""
