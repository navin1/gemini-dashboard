# Workforce IQ Dashboard

A Chrome extension that connects to a local FastAPI backend to provide an interactive workforce and spend management dashboard powered by BigQuery and Gemini AI.

---

## What's Inside

```
gemini-dashboard/
├── backend/            FastAPI server — BigQuery queries, Gemini AI, PDF export
├── extension/          Built Chrome extension (load this folder in Chrome)
├── setup-local.sh      One-time setup script (run this first)
├── uninstall-local.sh  Removes the login service
├── .env.example        Configuration template
└── README.md
```

---

## Requirements

| Requirement | Notes |
|---|---|
| macOS | Setup script uses macOS launchd |
| Python 3.9+ | Any version — script auto-detects |
| Google Chrome | Any recent version |
| GCP account | Needs BigQuery access on your project |
| gcloud CLI | For authentication — [install here](https://cloud.google.com/sdk/docs/install) |

---

## First-Time Setup

### Step 1 — Configure your environment

```bash
cp .env.example .env
```

Open `.env` and fill in your BigQuery details at minimum:

```env
BIGQUERY_TABLES=your-project.your-dataset.your-table
BQ_JOB_PROJECT_ID=your-gcp-project-id
VERTEX_AI_PROJECT=your-gcp-project-id
```

See `.env.example` for all available options with descriptions.

### Step 2 — Run the setup script

```bash
./setup-local.sh
```

This single script handles everything automatically:
- Finds Python 3.9+ on your machine (checks all common install locations)
- Creates an isolated virtual environment in `backend/.venv`
- Installs all Python dependencies
- Installs Playwright browser (used for PDF export)
- Runs `gcloud auth application-default login` (opens a browser — sign in once)
- Registers the backend as a **macOS login service** that auto-starts on every login

> The backend starts immediately after setup and auto-starts on every login.
> No terminal window needs to stay open.

### Step 3 — Load the Chrome extension

1. Open Chrome → go to `chrome://extensions`
2. Enable **Developer mode** (toggle, top-right corner)
3. Click **Load unpacked**
4. Select the `extension/` folder inside this project

The Workforce IQ icon appears in your Chrome toolbar. Click it to open the dashboard.

### Step 4 — Authenticate in the extension

Click the gear icon (⚙) in the dashboard header to open Settings.

**Recommended — Application Default Credentials**
If `setup-local.sh` completed successfully, ADC is already configured. Leave all token fields empty — the backend uses your gcloud credentials automatically. No further action needed.

**Alternative — Manual token**
Paste a short-lived token from:
```bash
gcloud auth print-access-token
```
Tokens expire after ~1 hour. ADC is strongly preferred for daily use.

---

## GCP Permissions Required

Your Google account needs these IAM roles on your GCP project:

| Role | Purpose |
|---|---|
| `roles/bigquery.dataViewer` | Read BigQuery tables |
| `roles/bigquery.jobUser` | Run BigQuery queries |
| `roles/aiplatform.user` | Use Vertex AI / Gemini AI chat |

---

## Managing the Backend Service

The backend runs silently as a macOS login service. Useful commands:

```bash
# Check if the server is running
curl http://localhost:8000/api/health

# View live logs
tail -f ~/Library/Logs/gemini-dashboard.log

# Stop the server
launchctl unload ~/Library/LaunchAgents/com.gemini-dashboard.backend.plist

# Start the server
launchctl load ~/Library/LaunchAgents/com.gemini-dashboard.backend.plist

# Remove the login service entirely
./uninstall-local.sh
```

---

## Receiving an Update

When you receive a new zip from the developer:

1. Unzip and replace the project folder (your `.env` file is excluded from the zip — it is safe)
2. Reload the extension in Chrome:
   - `chrome://extensions` → find Workforce IQ → click the **refresh icon**
3. If the update notes mention "backend dependencies changed", re-run:
   ```bash
   ./setup-local.sh
   ```
   Otherwise no further steps are needed — the service picks up backend changes on its next restart.

---

## Developer Guide

### Making changes

**Frontend / extension changes:**
```bash
# Run from gemini-dashboard-extension/
npm run build
```
Then reload the extension in Chrome (`chrome://extensions` → refresh icon).

**Backend changes (API, queries, AI logic):**
```bash
# Restart the service to pick up changes
launchctl unload ~/Library/LaunchAgents/com.gemini-dashboard.backend.plist
launchctl load  ~/Library/LaunchAgents/com.gemini-dashboard.backend.plist
```

**New Python dependency added to requirements.txt:**
```bash
./setup-local.sh   # rebuilds the venv from scratch
```

### Building and sharing a new distribution

```bash
# 1. Rebuild the extension
cd /path/to/gemini-dashboard-extension
npm run build          # outputs to ../gemini-dashboard/extension/

# 2. Create the zip (run from the parent of gemini-dashboard/)
cd ..
zip -r workforce-iq.zip gemini-dashboard/ \
  --exclude "*/backend/.venv/*" \
  --exclude "*/.venv/*" \
  --exclude "*/frontend/*" \
  --exclude "*/__pycache__/*" \
  --exclude "*/.git/*" \
  --exclude "*/.DS_Store" \
  --exclude "*/*.pyc" \
  --exclude "*/.env" \
  --exclude "*/data/*" \
  --exclude "*/Dockerfile" \
  --exclude "*/cloudbuild.yaml" \
  --exclude "*/deploy.sh" \
  --exclude "*/setup-gcp.sh" \
  --exclude "*/cleanup-gcp.sh" \
  --exclude "*/dev.sh" \
  --exclude "*/.dockerignore" \
  --exclude "*/package-lock.json" \
  --exclude "*/.logs/*"
```

Share `workforce-iq.zip`. Recipients follow **First-Time Setup** above.

---

## Troubleshooting

**Dashboard shows "Could not refresh data"**
- Verify the backend is running: `curl http://localhost:8000/api/health`
- If not running: `launchctl load ~/Library/LaunchAgents/com.gemini-dashboard.backend.plist`
- Check logs: `tail -f ~/Library/Logs/gemini-dashboard.log`

**403 Access Denied from BigQuery**
- Your account is missing the required IAM roles — see [GCP Permissions](#gcp-permissions-required)
- Re-run authentication: `gcloud auth application-default login`

**Token expired (manual token mode)**
- Paste a fresh token in Settings → Manual Token: `gcloud auth print-access-token`
- Switch to ADC (recommended) to avoid this entirely

**PDF export fails**
- Playwright browser may not be installed — re-run `./setup-local.sh`

**AI chat returns an error**
- Verify `VERTEX_AI_PROJECT` in `.env` is a valid GCP project ID
- Ensure `roles/aiplatform.user` is granted on that project
- Check logs: `tail -f ~/Library/Logs/gemini-dashboard.log`

**Extension not loading in Chrome**
- Make sure you selected the `extension/` folder, not the project root
- Developer mode must be enabled in `chrome://extensions`

**setup-local.sh: Python not found**
- Install Python 3.9+: `brew install python3` or from [python.org](https://www.python.org/downloads/)
- Re-run `./setup-local.sh`
