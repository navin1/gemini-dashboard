# Gemini Workforce Dashboard

A full-stack analytics dashboard powered by **Gemini 2.5 Flash** that connects to a BigQuery workforce/spend table and lets you explore data through natural language, drag-and-drop charts, multi-turn AI chat, and PDF reports. Deployable to Google Cloud Run in minutes.

---

## Features

- **3 Pre-built Scorecards** — FTE Hierarchy, Vendor Summary, Hierarchy Summary (auto-loaded from BigQuery)
- **AI Dashboard** — type a question in plain English; Gemini generates SQL, picks the best chart type, and explains the results
- **Dynamic Tabs** — add unlimited custom dashboard tabs, rename them (double-click), close them; state persists across sessions
- **Floating AI Chat** — conversational multi-turn agent accessible from any tab; inline chart previews with "Add to tab" button
- **7 Chart Types** — bar, stacked bar, line, combo (bar + line), donut, pie, horizontal bar, and data table
- **Drag & Drop Grid** — resize and rearrange every widget freely
- **Favorites** — 6 pre-seeded default queries + save your own; tied to your Google identity
- **Glossary** — 25 pre-seeded domain terms (FTP, FTE, TM, Capital, etc.); add/edit your own; Gemini uses them as context
- **PDF Export** — letter-size PDF with cover page, AI-written widget descriptions, red accent theme; filename follows tab name
- **Graceful degradation** — if Gemini API key is missing or invalid, all scorecards and BigQuery features continue to work; only AI features are disabled with a clear in-app banner
- **Auth** — Google OAuth token (primary) → service account JSON (fallback)

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | For local development |
| Node.js 18+ | For local development |
| npm 9+ | For local development |
| Google Cloud project | With BigQuery access |
| Gemini API key | From [Google AI Studio](https://aistudio.google.com/app/apikey) — optional; app works without it |
| gcloud CLI | Required for cloud deployment only |
| Docker | Required for cloud deployment only (used by Cloud Build) |

---

## Project Structure

```
gemini-dashboard/
├── .env                        # Your credentials (never committed)
├── Dockerfile                  # Multi-stage build: Node → Python + Playwright
├── .dockerignore
├── cloudbuild.yaml             # Cloud Build pipeline: build → push → deploy
├── dev.sh                      # Local dev: setup / start / stop / restart / status
├── setup-gcp.sh                # One-time GCP setup (run before first deploy)
├── deploy.sh                   # Build and deploy to Cloud Run
├── cleanup-gcp.sh              # Permanently delete all GCP resources for this app
├── backend/
│   ├── main.py                 # FastAPI app — serves API + React SPA in production
│   ├── auth.py                 # OAuth token / service account auth
│   ├── gemini_client.py        # Gemini 2.5 Flash — widget + chat generation
│   ├── bigquery_client.py      # BigQuery query execution + scorecard SQL
│   ├── database.py             # SQLite setup (SQLAlchemy)
│   ├── models.py               # DB models: User, GlossaryTerm, Favorite, DashboardLayout
│   ├── schemas.py              # Pydantic request/response schemas
│   ├── seed_data.py            # Default glossary terms + favorite queries
│   ├── assets/
│   │   └── logo.png            # App logo (shown in browser header and PDF)
│   ├── requirements.txt
│   └── routes/
│       ├── query.py            # POST /api/query      — NL → SQL → widget
│       ├── chat.py             # POST /api/chat       — multi-turn conversation
│       ├── scorecard.py        # GET  /api/scorecard/ — pre-built scorecard data
│       ├── favorites.py        # CRUD /api/favorites
│       ├── glossary.py         # CRUD /api/glossary
│       └── pdf.py              # POST /api/pdf/export — Playwright PDF generation
├── frontend/
│   ├── public/
│   │   └── logo.png            # Served at /logo.png by Vite / FastAPI static
│   └── src/
│       ├── App.tsx             # Root: dynamic tab bar + chat panel
│       ├── tabs/               # FTEHierarchyTab, VendorSummaryTab, HierarchySummaryTab, AIDashboardTab, FavoritesTab, GlossaryTab
│       ├── components/
│       │   ├── Charts/         # ChartRenderer (all 7 chart types via Recharts)
│       │   ├── Chat/           # ChatPanel with voice input + suggested questions
│       │   ├── Dashboard/      # DashboardGrid (react-grid-layout) + Widget shell
│       │   ├── DataTable/      # Sortable, paginated table with numeric right-alignment
│       │   ├── Header/         # App header with logo + KPI cards + token input
│       │   └── QueryBar/       # NL query input with suggestions
│       ├── api/                # Typed Axios clients for each backend route
│       ├── context/            # AuthContext (OAuth token management)
│       └── types/              # Shared TypeScript types
└── data/
    └── app.db                  # SQLite database (auto-created on first run)
```

---

## Local Development

### 1. Configure environment variables

Create your `.env` file in the project root:

```env
# ── Gemini ──────────────────────────────────────────────────────────────────
# Get from https://aistudio.google.com/app/apikey
# Optional — app works without it (AI features will be disabled)
GEMINI_API_KEY=your_gemini_api_key_here

# ── Google Authentication (at least one required) ────────────────────────────
# PRIMARY: Short-lived Google OAuth2 token
# Run: gcloud auth print-access-token
GOOGLE_OAUTH_TOKEN=

# FALLBACK: Path to a Google service account JSON key file
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# ── BigQuery ──────────────────────────────────────────────────────────────────
BIGQUERY_PROJECT_ID=your_project_id
BIGQUERY_DATASET=your_dataset
BIGQUERY_TABLE=your_table
```

> **Auth priority:** `GOOGLE_OAUTH_TOKEN` is used first. If blank, the backend falls back to `GOOGLE_APPLICATION_CREDENTIALS`. At least one must be set for BigQuery access.

### 2. Install dependencies

```bash
./dev.sh setup
```

This creates a Python virtual environment, installs all Python and Node dependencies, and installs Playwright's Chromium for PDF export. Run once.

### 3. Start the app

```bash
./dev.sh start
```

Starts the FastAPI backend on **port 8000** and the Vite frontend on **port 5173**. The Vite dev server proxies all `/api/*` requests to the backend — no CORS configuration needed.

| URL | Description |
|---|---|
| http://localhost:5173 | Dashboard |
| http://localhost:8000/docs | FastAPI interactive docs |
| http://localhost:8000/api/health | Health check |

### Other dev commands

```bash
./dev.sh stop      # stop both servers
./dev.sh restart   # stop then start
./dev.sh status    # check if servers are running
```

---

## Setting Your OAuth Token in the UI

1. Run `gcloud auth print-access-token` in your terminal
2. Click the **login icon** in the top-right corner of the dashboard
3. Paste the token — it is stored in your browser's `localStorage`
4. The header will show **● Authenticated** when the token is active

> Tokens expire after ~1 hour. Re-run `gcloud auth print-access-token` and re-paste when needed.

---

## Google Cloud Deployment

The app deploys as a single Cloud Run service: FastAPI serves the API and the pre-built React SPA from the same container. `GEMINI_API_KEY` is stored in Secret Manager and injected at runtime.

### Architecture

```
Cloud Build
  └── builds Docker image (Node build → Python runtime + Playwright)
  └── pushes to Artifact Registry
  └── deploys to Cloud Run
         ├── FastAPI (port 8080)
         │   ├── /api/*         — backend routes
         │   └── /*             — React SPA (static files)
         └── Secrets: GEMINI_API_KEY (from Secret Manager)
```

### Step 1 — One-time GCP setup

```bash
./setup-gcp.sh
```

Run this once per GCP project. It will:
- Prompt for your GCP project ID, region, service name, OAuth Client ID, and Gemini API key
- Enable required APIs (Cloud Run, Cloud Build, Artifact Registry, Secret Manager, BigQuery)
- Create an Artifact Registry Docker repository
- Store `GEMINI_API_KEY` in Secret Manager
- Create a **dedicated service account** (`<service-name>-sa`) with only the roles it needs:
  - `roles/secretmanager.secretAccessor`
  - `roles/bigquery.dataViewer`
  - `roles/bigquery.jobUser`
- Save all config to `.env`

### Step 2 — Deploy (and redeploy)

```bash
./deploy.sh
```

Submits the build to Cloud Build, waits for completion, then saves the live Cloud Run URL to `.env`.

> First build takes **~5–8 minutes** (Playwright's Chromium layer is large). Subsequent deploys are faster due to layer caching.

### Step 3 — Google OAuth (if using Google Sign-In)

After the first deploy, add your Cloud Run URL to the OAuth Client's **Authorized JavaScript origins**:

1. Go to [Google Cloud Console](https://console.cloud.google.com) → **APIs & Services → Credentials**
2. Open your OAuth 2.0 Client ID
3. Under **Authorized JavaScript origins**, add your Cloud Run URL (printed at the end of `./deploy.sh`)
4. Save

### Teardown

```bash
./cleanup-gcp.sh
```

Permanently deletes all GCP resources created for this app:
- Cloud Run service
- Artifact Registry repository (all container images)
- Secret Manager secret
- IAM policy bindings
- Dedicated service account

> You must type the GCP project ID to confirm. APIs are intentionally left enabled (project-wide; harmless). BigQuery datasets and tables are never touched.

---

## Using the Dashboard

### Pre-built Scorecards
The three scorecard tabs (FTE Hierarchy, Vendor Summary, Hierarchy Summary) load automatically from BigQuery. Click **Refresh** to re-query. Click **Export PDF** to download a formatted letter-size report — the filename follows the tab name.

### AI Dashboard (Query Bar)
Type any question in plain English:
- *"Show top 10 vendors by YTD spend"*
- *"Compare capital vs expense monthly trend"*
- *"Which resource managers have the most offshore resources?"*

Gemini generates the SQL, picks the best chart type, runs the query, and adds a widget to the drag-and-drop grid. Each widget shows an AI-written insight.

### AI Chat (Floating Panel)
Click the **AI Analyst** bar at the bottom. You can:
- Ask follow-up questions in context — *"Now show only Capital spend"*
- Request explanations — *"What does FTP mean?"*
- Ask for charts — *"Create a donut chart of bill type split"*
- Use **voice input** (microphone button) on supported browsers
- Click **Add to tab** on any inline chart to move it to your current tab
- Click suggested follow-up questions for quick exploration

### Dynamic Tabs
- Click **+ New Tab** to create a new AI workspace
- **Double-click** a custom tab name to rename it — the PDF filename will match
- **Hover** a custom tab and click **×** to close it
- Custom tabs persist across browser sessions

### Favorites
- Click the **★** icon on any widget to save the query
- Open the **Favorites** tab to re-run saved queries or browse the 6 default queries

### Glossary
- Open the **Glossary** tab to browse 25 pre-seeded domain terms
- Click **Add Term** to create your own terms
- Gemini uses the glossary as context when generating SQL and explanations

---

## Tech Stack

| Layer | Technology |
|---|---|
| AI Model | Gemini 2.5 Flash (`google-generativeai`) |
| Backend | FastAPI + Uvicorn |
| Database | SQLite via SQLAlchemy |
| BigQuery | `google-cloud-bigquery` |
| PDF | Playwright (headless Chromium) + pypdf (page merging) |
| Frontend | React 18 + TypeScript + Vite |
| Styling | Tailwind CSS |
| Charts | Recharts |
| Dashboard grid | react-grid-layout |
| HTTP client | Axios |
| Container | Docker (multi-stage: Node 20 Alpine → Python 3.12 slim) |
| CI/CD | Google Cloud Build |
| Hosting | Google Cloud Run |
| Image registry | Google Artifact Registry |
| Secrets | Google Secret Manager |

---

## Troubleshooting

**AI Analyst unavailable banner appears**
The app detected that `GEMINI_API_KEY` is missing, invalid, or quota-exceeded. BigQuery scorecards still work normally. Set a valid key in `.env` (local) or update the Secret Manager secret and redeploy (cloud).

**BigQuery permission error**
Ensure your OAuth token or service account has `BigQuery Data Viewer` and `BigQuery Job User` roles on the BigQuery project.

**PDF export fails locally**
Playwright's Chromium must be installed: run `./dev.sh setup` (it installs Chromium automatically). If you installed manually, run `playwright install chromium` inside the virtual environment.

**PDF export fails on Cloud Run**
The Dockerfile includes all Chromium system dependencies and runs `playwright install chromium` at build time. If it still fails, check Cloud Run logs for missing shared libraries.

**OAuth token expired**
Tokens expire after ~1 hour. Re-run `gcloud auth print-access-token` and update the token in the dashboard header.

**Custom tabs lost after refresh**
Custom tab configuration is stored in `localStorage`. Clearing browser data will reset them. Widget data is in-memory only — re-run queries after a page refresh.

**Cloud Build fails on first run**
Ensure `./setup-gcp.sh` was run first (enables required APIs, creates the Artifact Registry repo, and stores the secret). Check that the Cloud Build service account (`<project-number>@cloudbuild.gserviceaccount.com`) has the `Cloud Run Admin` and `Service Account User` roles if not already granted.
