#!/usr/bin/env bash
# deploy.sh — build and deploy the Workforce Dashboard to Google Cloud Run
# Usage: ./deploy.sh
# Pre-requisite: run ./setup-gcp.sh once before the first deploy.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
CLOUDBUILD_CONFIG="$PROJECT_ROOT/cloudbuild.yaml"

# ── helpers ──────────────────────────────────────────────────────────────────

log()  { printf '\033[1;34m[deploy]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[  ✓  ]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[ warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[ err ]\033[0m %s\n' "$*" >&2; exit 1; }
step() { echo ""; printf '\033[1;37m━━ %s ━━\033[0m\n' "$*"; echo ""; }

env_get() {
  local key=$1
  grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"' || echo ""
}

env_set() {
  local key=$1 val=$2
  if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
    sed -i.bak "s|^${key}=.*|${key}=${val}|" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
}

# ── pre-flight ────────────────────────────────────────────────────────────────

step "Pre-flight checks"

command -v gcloud &>/dev/null || die "gcloud CLI not found. Install from https://cloud.google.com/sdk/docs/install"
[[ -f "$ENV_FILE" ]]          || die ".env not found. Run './dev.sh setup' then './setup-gcp.sh' first."
[[ -f "$CLOUDBUILD_CONFIG" ]] || die "cloudbuild.yaml not found in project root."

gcloud auth print-access-token &>/dev/null || die "Not authenticated. Run: gcloud auth login"
ok "gcloud is authenticated"

# ── load config from .env ────────────────────────────────────────────────────

step "Load configuration"

GCP_PROJECT_ID=$(env_get "GCP_PROJECT_ID")
GCP_REGION=$(env_get "GCP_REGION")
GCP_SERVICE_NAME=$(env_get "GCP_SERVICE_NAME")
GCP_REPO_NAME=$(env_get "GCP_REPO_NAME")
GCP_SA_EMAIL=$(env_get "GCP_SA_EMAIL")
VITE_GOOGLE_CLIENT_ID=$(env_get "VITE_GOOGLE_CLIENT_ID")
BIGQUERY_PROJECT_ID=$(env_get "BIGQUERY_PROJECT_ID")
BIGQUERY_DATASET=$(env_get "BIGQUERY_DATASET")
BIGQUERY_TABLE=$(env_get "BIGQUERY_TABLE")

[[ -n "$GCP_PROJECT_ID" ]]   || die "GCP_PROJECT_ID is not set in .env. Run ./setup-gcp.sh first."
[[ -n "$GCP_REGION" ]]       || die "GCP_REGION is not set in .env. Run ./setup-gcp.sh first."
[[ -n "$GCP_SERVICE_NAME" ]] || die "GCP_SERVICE_NAME is not set in .env. Run ./setup-gcp.sh first."
[[ -n "$GCP_REPO_NAME" ]]    || die "GCP_REPO_NAME is not set in .env. Run ./setup-gcp.sh first."
[[ -n "$GCP_SA_EMAIL" ]]     || die "GCP_SA_EMAIL is not set in .env. Run ./setup-gcp.sh first."

log "Project:  $GCP_PROJECT_ID"
log "Region:   $GCP_REGION"
log "Service:  $GCP_SERVICE_NAME"
log "SA:       $GCP_SA_EMAIL"
[[ -n "$BIGQUERY_PROJECT_ID" ]] && log "BQ project: $BIGQUERY_PROJECT_ID / $BIGQUERY_DATASET.$BIGQUERY_TABLE"
ok "Config loaded"

# ── set active project ───────────────────────────────────────────────────────

gcloud config set project "$GCP_PROJECT_ID" --quiet

# ── build & deploy via Cloud Build ──────────────────────────────────────────

step "Build and deploy (Cloud Build)"

SUBS="_REGION=${GCP_REGION}"
SUBS+=",_SERVICE=${GCP_SERVICE_NAME}"
SUBS+=",_REPO=${GCP_REPO_NAME}"
SUBS+=",_SA_EMAIL=${GCP_SA_EMAIL}"
SUBS+=",_VITE_GOOGLE_CLIENT_ID=${VITE_GOOGLE_CLIENT_ID}"
SUBS+=",_BIGQUERY_PROJECT_ID=${BIGQUERY_PROJECT_ID:-}"
SUBS+=",_BIGQUERY_DATASET=${BIGQUERY_DATASET:-}"
SUBS+=",_BIGQUERY_TABLE=${BIGQUERY_TABLE:-}"

log "Submitting build to Cloud Build..."
log "This typically takes 3-7 minutes on first run (Playwright layer is large)."
echo ""

gcloud builds submit \
  --config="$CLOUDBUILD_CONFIG" \
  --substitutions="$SUBS" \
  --project="$GCP_PROJECT_ID" \
  "$PROJECT_ROOT"

ok "Build and deploy complete"

# ── retrieve Cloud Run URL ───────────────────────────────────────────────────

step "Retrieve service URL"

CLOUD_RUN_URL=$(gcloud run services describe "$GCP_SERVICE_NAME" \
  --region="$GCP_REGION" \
  --project="$GCP_PROJECT_ID" \
  --format="value(status.url)" 2>/dev/null || echo "")

if [[ -n "$CLOUD_RUN_URL" ]]; then
  env_set "CLOUD_RUN_URL" "$CLOUD_RUN_URL"
  ok "Service URL: $CLOUD_RUN_URL"
  ok "CLOUD_RUN_URL saved to .env"
else
  warn "Could not retrieve service URL — check the Cloud Run console."
fi

# ── post-deploy reminders ────────────────────────────────────────────────────

echo ""
ok "━━ Deployment complete ━━"
echo ""

if [[ -n "$CLOUD_RUN_URL" ]]; then
  log "Your app is live at: $CLOUD_RUN_URL"
  echo ""
fi

if [[ -n "$VITE_GOOGLE_CLIENT_ID" ]]; then
  log "Google OAuth reminder:"
  log "  Add the following URL to your OAuth Client's 'Authorized JavaScript origins':"
  [[ -n "$CLOUD_RUN_URL" ]] && log "    $CLOUD_RUN_URL"
  log "  Google Cloud Console → APIs & Services → Credentials → your OAuth Client ID"
  echo ""
fi

log "To redeploy after changes, simply run:  ./deploy.sh"
echo ""
