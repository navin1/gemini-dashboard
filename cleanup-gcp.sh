#!/usr/bin/env bash
# cleanup-gcp.sh — permanently delete ALL Google Cloud resources for this project
# This script only touches resources it created; it will NOT affect other services
# in your GCP project.
#
# Resources deleted:
#   • Cloud Run service
#   • Artifact Registry repository (and all container images inside it)
#   • Secret Manager secret  (gemini-api-key)
#   • IAM policy bindings    (for the dedicated service account)
#   • Dedicated service account
#
# Resources intentionally NOT deleted (project-wide, not app-specific):
#   • Enabled APIs  (harmless to leave; disabling could break other services)
#   • Cloud Build logs bucket  (gs://<project>_cloudbuild — shared by all builds)
#   • BigQuery datasets / tables (you own that data; we never created them)
#
# Usage: ./cleanup-gcp.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

# ── helpers ──────────────────────────────────────────────────────────────────

log()  { printf '\033[1;34m[cleanup]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[  ✓   ]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[  !   ]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[ err  ]\033[0m %s\n' "$*" >&2; exit 1; }
skip() { printf '\033[0;90m[ skip ]\033[0m %s\n' "$*"; }
step() { echo ""; printf '\033[1;37m━━ %s ━━\033[0m\n' "$*"; echo ""; }

env_get() {
  local key=$1
  grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"' || echo ""
}

env_remove() {
  local key=$1
  sed -i.bak "/^${key}=/d" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
}

# ── pre-flight ────────────────────────────────────────────────────────────────

command -v gcloud &>/dev/null || die "gcloud CLI not found."
[[ -f "$ENV_FILE" ]]          || die ".env not found — nothing to clean up."

gcloud auth print-access-token &>/dev/null || die "Not authenticated. Run: gcloud auth login"
ok "gcloud is authenticated"

# ── load config ───────────────────────────────────────────────────────────────

step "Load configuration"

GCP_PROJECT_ID=$(env_get "GCP_PROJECT_ID")
GCP_REGION=$(env_get "GCP_REGION")
GCP_SERVICE_NAME=$(env_get "GCP_SERVICE_NAME")
GCP_REPO_NAME=$(env_get "GCP_REPO_NAME")
GCP_SA_EMAIL=$(env_get "GCP_SA_EMAIL")
BIGQUERY_PROJECT_ID=$(env_get "BIGQUERY_PROJECT_ID")

[[ -n "$GCP_PROJECT_ID" ]]   || die "GCP_PROJECT_ID not set in .env — cannot determine what to delete."
[[ -n "$GCP_REGION" ]]       || die "GCP_REGION not set in .env."
[[ -n "$GCP_SERVICE_NAME" ]] || die "GCP_SERVICE_NAME not set in .env."

log "GCP project:      $GCP_PROJECT_ID"
log "Region:           $GCP_REGION"
log "Cloud Run:        $GCP_SERVICE_NAME"
log "Artifact Reg:     ${GCP_REPO_NAME:-<not set>}"
log "Secret:           gemini-api-key"
log "Service account:  ${GCP_SA_EMAIL:-<not set>}"

# ── confirmation ──────────────────────────────────────────────────────────────

step "Confirmation required"

echo ""
warn "This will PERMANENTLY DELETE the following resources in project '$GCP_PROJECT_ID':"
echo ""
echo "  • Cloud Run service       : $GCP_SERVICE_NAME  ($GCP_REGION)"
[[ -n "$GCP_REPO_NAME" ]] && \
echo "  • Artifact Registry repo  : $GCP_REPO_NAME  (all images inside)"
echo "  • Secret Manager secret   : gemini-api-key"
[[ -n "$GCP_SA_EMAIL" ]] && \
echo "  • Service account         : $GCP_SA_EMAIL"
echo "  • IAM bindings            : for the service account above"
echo ""
warn "This action is IRREVERSIBLE. Data deleted cannot be recovered."
echo ""
read -rp "  Type the GCP project ID to confirm: " confirm_project

if [[ "$confirm_project" != "$GCP_PROJECT_ID" ]]; then
  echo ""
  die "Input did not match '$GCP_PROJECT_ID'. Aborting — nothing was deleted."
fi

echo ""
ok "Confirmed. Starting cleanup..."

gcloud config set project "$GCP_PROJECT_ID" --quiet

# ── Cloud Run service ─────────────────────────────────────────────────────────

step "Delete Cloud Run service"

if gcloud run services describe "$GCP_SERVICE_NAME" \
     --region="$GCP_REGION" --project="$GCP_PROJECT_ID" &>/dev/null; then
  log "Deleting Cloud Run service '$GCP_SERVICE_NAME' ..."
  gcloud run services delete "$GCP_SERVICE_NAME" \
    --region="$GCP_REGION" \
    --project="$GCP_PROJECT_ID" \
    --quiet
  ok "Cloud Run service deleted"
else
  skip "Cloud Run service '$GCP_SERVICE_NAME' not found — skipping"
fi

# ── Artifact Registry repository ─────────────────────────────────────────────

step "Delete Artifact Registry repository"

if [[ -n "$GCP_REPO_NAME" ]]; then
  if gcloud artifacts repositories describe "$GCP_REPO_NAME" \
       --location="$GCP_REGION" --project="$GCP_PROJECT_ID" &>/dev/null; then
    log "Deleting repository '$GCP_REPO_NAME' and all images inside ..."
    gcloud artifacts repositories delete "$GCP_REPO_NAME" \
      --location="$GCP_REGION" \
      --project="$GCP_PROJECT_ID" \
      --quiet
    ok "Artifact Registry repository deleted"
  else
    skip "Repository '$GCP_REPO_NAME' not found — skipping"
  fi
else
  skip "GCP_REPO_NAME not set — skipping"
fi

# ── Secret Manager ────────────────────────────────────────────────────────────

step "Delete Secret Manager secret"

if gcloud secrets describe gemini-api-key \
     --project="$GCP_PROJECT_ID" &>/dev/null; then
  log "Deleting all versions of secret 'gemini-api-key' ..."
  gcloud secrets delete gemini-api-key \
    --project="$GCP_PROJECT_ID" \
    --quiet
  ok "Secret deleted"
else
  skip "Secret 'gemini-api-key' not found — skipping"
fi

# ── IAM bindings ──────────────────────────────────────────────────────────────

step "Remove IAM policy bindings"

if [[ -n "$GCP_SA_EMAIL" ]]; then
  MEMBER="serviceAccount:${GCP_SA_EMAIL}"

  for role in \
      "roles/secretmanager.secretAccessor" \
      "roles/bigquery.dataViewer" \
      "roles/bigquery.jobUser"; do

    log "Removing $role from $GCP_SA_EMAIL on project $GCP_PROJECT_ID ..."
    gcloud projects remove-iam-policy-binding "$GCP_PROJECT_ID" \
      --member="$MEMBER" \
      --role="$role" \
      --condition=None \
      --quiet 2>/dev/null \
    && ok "Removed $role" \
    || skip "$role binding not found — skipping"
  done

  # Also remove from BigQuery project if different
  if [[ -n "$BIGQUERY_PROJECT_ID" && "$BIGQUERY_PROJECT_ID" != "$GCP_PROJECT_ID" ]]; then
    log "Removing BigQuery bindings from project $BIGQUERY_PROJECT_ID ..."
    for role in "roles/bigquery.dataViewer" "roles/bigquery.jobUser"; do
      gcloud projects remove-iam-policy-binding "$BIGQUERY_PROJECT_ID" \
        --member="$MEMBER" \
        --role="$role" \
        --condition=None \
        --quiet 2>/dev/null \
      && ok "Removed $role from $BIGQUERY_PROJECT_ID" \
      || skip "$role on $BIGQUERY_PROJECT_ID not found — skipping"
    done
  fi
else
  skip "GCP_SA_EMAIL not set — skipping IAM cleanup"
fi

# ── Service account ───────────────────────────────────────────────────────────

step "Delete dedicated service account"

if [[ -n "$GCP_SA_EMAIL" ]]; then
  if gcloud iam service-accounts describe "$GCP_SA_EMAIL" \
       --project="$GCP_PROJECT_ID" &>/dev/null; then
    log "Deleting service account '$GCP_SA_EMAIL' ..."
    gcloud iam service-accounts delete "$GCP_SA_EMAIL" \
      --project="$GCP_PROJECT_ID" \
      --quiet
    ok "Service account deleted"
  else
    skip "Service account '$GCP_SA_EMAIL' not found — skipping"
  fi
else
  skip "GCP_SA_EMAIL not set — skipping"
fi

# ── Clean up .env ─────────────────────────────────────────────────────────────

step "Clean up .env"

for key in GCP_PROJECT_ID GCP_REGION GCP_SERVICE_NAME GCP_REPO_NAME GCP_SA_EMAIL CLOUD_RUN_URL; do
  if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
    env_remove "$key"
    log "Removed $key from .env"
  fi
done
ok ".env cleaned"

# ── done ──────────────────────────────────────────────────────────────────────

echo ""
ok "━━ Cleanup complete ━━"
echo ""
log "All app-specific GCP resources for '$GCP_SERVICE_NAME' have been deleted."
log "APIs remain enabled (they are project-wide and harmless to leave on)."
log "BigQuery dataset and tables were NOT touched."
echo ""
