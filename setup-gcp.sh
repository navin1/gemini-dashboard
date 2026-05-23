#!/usr/bin/env bash
# setup-gcp.sh — one-time Google Cloud setup for the Workforce Dashboard
# Run this once before your first deployment.
# Usage: ./setup-gcp.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

# ── helpers ──────────────────────────────────────────────────────────────────

log()  { printf '\033[1;34m[gcp-setup]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[    ✓    ]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[  warn   ]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[  error  ]\033[0m %s\n' "$*" >&2; exit 1; }
step() { echo ""; printf '\033[1;37m━━ %s ━━\033[0m\n' "$*"; echo ""; }

# Read a value from .env file
env_get() {
  local key=$1
  grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"' || echo ""
}

# Set or update a value in .env file
env_set() {
  local key=$1 val=$2
  if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
    sed -i.bak "s|^${key}=.*|${key}=${val}|" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
}

# Prompt for a value; use default if provided and user presses Enter
prompt() {
  local label=$1 default=${2:-} result
  if [[ -n "$default" ]]; then
    read -rp "  $label [$default]: " result
    echo "${result:-$default}"
  else
    read -rp "  $label: " result
    echo "$result"
  fi
}

# ── pre-flight ────────────────────────────────────────────────────────────────

command -v gcloud &>/dev/null || die "gcloud CLI not found. Install it from https://cloud.google.com/sdk/docs/install"
[[ -f "$ENV_FILE" ]] || die ".env not found in project root. Run './dev.sh setup' first."

gcloud auth print-access-token &>/dev/null || die "Not authenticated. Run: gcloud auth login"
ok "gcloud is authenticated"

# ── read / prompt for config ──────────────────────────────────────────────────

step "Configuration"

GCP_PROJECT_ID=$(env_get "GCP_PROJECT_ID")
GCP_REGION=$(env_get "GCP_REGION")
GCP_SERVICE_NAME=$(env_get "GCP_SERVICE_NAME")
GCP_REPO_NAME=$(env_get "GCP_REPO_NAME")
VITE_GOOGLE_CLIENT_ID=$(env_get "VITE_GOOGLE_CLIENT_ID")
GEMINI_API_KEY=$(env_get "GEMINI_API_KEY")
BIGQUERY_PROJECT_ID=$(env_get "BIGQUERY_PROJECT_ID")
GCP_SA_EMAIL=$(env_get "GCP_SA_EMAIL")

GCP_PROJECT_ID=$(prompt "GCP Project ID" "$GCP_PROJECT_ID")
GCP_REGION=$(prompt "Region" "${GCP_REGION:-us-central1}")
GCP_SERVICE_NAME=$(prompt "Cloud Run service name" "${GCP_SERVICE_NAME:-workforce-dashboard}")
GCP_REPO_NAME=$(prompt "Artifact Registry repo name" "${GCP_REPO_NAME:-workforce-dashboard}")
VITE_GOOGLE_CLIENT_ID=$(prompt "Google OAuth Client ID (VITE_GOOGLE_CLIENT_ID, leave blank to skip)" "$VITE_GOOGLE_CLIENT_ID")

[[ -n "$GCP_PROJECT_ID" ]] || die "GCP_PROJECT_ID is required."

# Persist to .env
env_set "GCP_PROJECT_ID"       "$GCP_PROJECT_ID"
env_set "GCP_REGION"           "$GCP_REGION"
env_set "GCP_SERVICE_NAME"     "$GCP_SERVICE_NAME"
env_set "GCP_REPO_NAME"        "$GCP_REPO_NAME"
[[ -n "$VITE_GOOGLE_CLIENT_ID" ]] && env_set "VITE_GOOGLE_CLIENT_ID" "$VITE_GOOGLE_CLIENT_ID"

ok "Config saved to .env"

# ── set project ───────────────────────────────────────────────────────────────

step "Set active project"
gcloud config set project "$GCP_PROJECT_ID"
ok "Active project: $GCP_PROJECT_ID"

# ── enable APIs ───────────────────────────────────────────────────────────────

step "Enable required APIs"
log "Enabling APIs (this may take a minute)..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  bigquery.googleapis.com \
  --project="$GCP_PROJECT_ID"
ok "All APIs enabled"

# ── Artifact Registry ─────────────────────────────────────────────────────────

step "Artifact Registry repository"
if gcloud artifacts repositories describe "$GCP_REPO_NAME" \
     --location="$GCP_REGION" --project="$GCP_PROJECT_ID" &>/dev/null; then
  ok "Repository '$GCP_REPO_NAME' already exists — skipping"
else
  log "Creating repository '$GCP_REPO_NAME' in $GCP_REGION ..."
  gcloud artifacts repositories create "$GCP_REPO_NAME" \
    --repository-format=docker \
    --location="$GCP_REGION" \
    --project="$GCP_PROJECT_ID"
  ok "Repository created"
fi

# ── Secret Manager — GEMINI_API_KEY ───────────────────────────────────────────

step "Secret Manager — GEMINI_API_KEY"
if [[ -z "$GEMINI_API_KEY" ]]; then
  GEMINI_API_KEY=$(prompt "GEMINI_API_KEY (paste your Gemini API key)")
  [[ -n "$GEMINI_API_KEY" ]] || die "GEMINI_API_KEY is required."
  env_set "GEMINI_API_KEY" "$GEMINI_API_KEY"
fi

if gcloud secrets describe gemini-api-key --project="$GCP_PROJECT_ID" &>/dev/null; then
  warn "Secret 'gemini-api-key' already exists."
  read -rp "  Update it with the current GEMINI_API_KEY from .env? [y/N]: " update_secret
  if [[ "${update_secret,,}" == "y" ]]; then
    echo -n "$GEMINI_API_KEY" | gcloud secrets versions add gemini-api-key \
      --data-file=- --project="$GCP_PROJECT_ID"
    ok "Secret updated"
  else
    ok "Secret left unchanged"
  fi
else
  log "Creating secret 'gemini-api-key' ..."
  echo -n "$GEMINI_API_KEY" | gcloud secrets create gemini-api-key \
    --data-file=- --project="$GCP_PROJECT_ID"
  ok "Secret created"
fi

# ── Dedicated Service Account ─────────────────────────────────────────────────

step "Dedicated service account"

# SA IDs must be 6–30 chars; derive from service name and truncate if needed
SA_ID="${GCP_SERVICE_NAME}-sa"
SA_ID="${SA_ID:0:30}"
GCP_SA_EMAIL="${SA_ID}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

if gcloud iam service-accounts describe "$GCP_SA_EMAIL" \
     --project="$GCP_PROJECT_ID" &>/dev/null; then
  ok "Service account '${SA_ID}' already exists — skipping"
else
  log "Creating service account '${SA_ID}' ..."
  gcloud iam service-accounts create "$SA_ID" \
    --display-name="Workforce Dashboard — Cloud Run SA" \
    --project="$GCP_PROJECT_ID"
  ok "Service account created: $GCP_SA_EMAIL"
fi

env_set "GCP_SA_EMAIL" "$GCP_SA_EMAIL"
log "GCP_SA_EMAIL saved to .env"

# ── IAM — grant dedicated SA the required permissions ────────────────────────

step "IAM permissions"
log "Service account: $GCP_SA_EMAIL"

log "Granting Secret Manager accessor..."
gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member="serviceAccount:${GCP_SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" \
  --condition=None \
  --quiet
ok "secretmanager.secretAccessor granted"

log "Granting BigQuery Data Viewer..."
gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member="serviceAccount:${GCP_SA_EMAIL}" \
  --role="roles/bigquery.dataViewer" \
  --condition=None \
  --quiet
ok "bigquery.dataViewer granted"

log "Granting BigQuery Job User..."
gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member="serviceAccount:${GCP_SA_EMAIL}" \
  --role="roles/bigquery.jobUser" \
  --condition=None \
  --quiet
ok "bigquery.jobUser granted"

# If BigQuery is in a different project, grant roles there too
if [[ -n "$BIGQUERY_PROJECT_ID" && "$BIGQUERY_PROJECT_ID" != "$GCP_PROJECT_ID" ]]; then
  warn "BigQuery project ($BIGQUERY_PROJECT_ID) differs from GCP project ($GCP_PROJECT_ID)."
  warn "Granting BigQuery roles on project $BIGQUERY_PROJECT_ID ..."
  gcloud projects add-iam-policy-binding "$BIGQUERY_PROJECT_ID" \
    --member="serviceAccount:${GCP_SA_EMAIL}" \
    --role="roles/bigquery.dataViewer" \
    --condition=None \
    --quiet
  gcloud projects add-iam-policy-binding "$BIGQUERY_PROJECT_ID" \
    --member="serviceAccount:${GCP_SA_EMAIL}" \
    --role="roles/bigquery.jobUser" \
    --condition=None \
    --quiet
  ok "BigQuery roles granted on $BIGQUERY_PROJECT_ID"
fi

# ── done ──────────────────────────────────────────────────────────────────────

echo ""
ok "━━ GCP setup complete ━━"
echo ""
log "Service account: $GCP_SA_EMAIL"
log "Next step → run:  ./deploy.sh"
echo ""
