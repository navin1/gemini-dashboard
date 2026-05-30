import logging
import os
import json
import pathlib
import subprocess
import httpx
from dotenv import load_dotenv
from fastapi import Header, HTTPException
from typing import Optional

logger = logging.getLogger(__name__)

load_dotenv()

OAUTH_TOKEN_ENV = os.getenv("GOOGLE_OAUTH_TOKEN", "")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")

ANONYMOUS_USER_ID = "anonymous"


async def resolve_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """
    Extract user info from Bearer token in Authorization header.
    Falls back to env-level GOOGLE_OAUTH_TOKEN, then returns anonymous user.
    """
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
    elif OAUTH_TOKEN_ENV:
        token = OAUTH_TOKEN_ENV

    if token:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code == 200:
                    info = resp.json()
                    return {"id": info.get("id", info.get("sub", token[:32])), "email": info.get("email", "")}
        except Exception:
            pass

    return {"id": ANONYMOUS_USER_ID, "email": ""}


def get_request_token(authorization: Optional[str] = Header(default=None)) -> Optional[str]:
    """FastAPI dependency — extract Bearer token from Authorization header."""
    if authorization and authorization.startswith("Bearer "):
        return authorization.split(" ", 1)[1]
    return OAUTH_TOKEN_ENV or None


def _get_gcloud_login_credentials():
    """Load credentials from `gcloud auth login` for the currently active account.

    Reads ~/.config/gcloud/legacy_credentials/<account>/adc.json which holds
    a refresh token that auto-refreshes — no manual token rotation needed.
    Returns None if gcloud is not installed or the account file is missing.
    """
    try:
        result = subprocess.run(
            ["gcloud", "config", "get-value", "account"],
            capture_output=True, text=True, timeout=5,
        )
        account = result.stdout.strip()
        if not account:
            logger.debug("gcloud login creds: no active account configured")
            return None
    except Exception as e:
        logger.debug("gcloud login creds: could not run gcloud binary: %s", e)
        return None

    cred_file = (
        pathlib.Path.home()
        / ".config" / "gcloud" / "legacy_credentials" / account / "adc.json"
    )
    if not cred_file.exists():
        logger.debug("gcloud login creds: credential file not found at %s", cred_file)
        return None

    try:
        import google.auth
        creds, _ = google.auth.load_credentials_from_file(str(cred_file))
        logger.debug("gcloud login creds: loaded from %s", cred_file)
        return creds
    except Exception as e:
        logger.debug("gcloud login creds: failed to load file: %s", e)
        return None


def _find_gcloud_binary() -> str:
    """Return the path to the gcloud binary, checking common install locations."""
    # Try PATH first
    try:
        result = subprocess.run(["which", "gcloud"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass

    # Common install locations on macOS and Linux
    candidates = [
        "/usr/lib/google-cloud-sdk/bin/gcloud",
        "/usr/local/bin/gcloud",
        "/opt/homebrew/bin/gcloud",
        str(pathlib.Path.home() / "google-cloud-sdk" / "bin" / "gcloud"),
        "/snap/bin/gcloud",
        "/usr/bin/gcloud",
    ]
    for path in candidates:
        if pathlib.Path(path).exists():
            logger.debug("gcloud binary found at %s", path)
            return path

    return "gcloud"  # fall back to bare name and let subprocess raise FileNotFoundError


def _get_gcloud_print_token() -> str | None:
    """Get a short-lived access token via `gcloud auth print-access-token`.

    Works whenever `gcloud auth login` has been done, regardless of where
    the credential file lives on disk. Falls back gracefully if gcloud is
    not in PATH or no account is logged in.
    """
    gcloud = _find_gcloud_binary()
    try:
        result = subprocess.run(
            [gcloud, "auth", "print-access-token"],
            capture_output=True, text=True, timeout=10,
        )
        token = result.stdout.strip()
        if token and result.returncode == 0:
            logger.debug("gcloud print-access-token: obtained short-lived token (binary=%s)", gcloud)
            return token
        stderr = result.stderr.strip()
        logger.warning("gcloud print-access-token: returncode=%d stderr=%s (binary=%s)", result.returncode, stderr, gcloud)
        return None
    except FileNotFoundError:
        logger.warning("gcloud print-access-token: gcloud binary not found (tried: %s)", gcloud)
        return None
    except Exception as e:
        logger.warning("gcloud print-access-token: failed: %s", e)
        return None


def get_bq_credentials(token: Optional[str] = None):
    """Return BigQuery credentials.

    Priority:
      1. Per-request OAuth token (from UI Authorization header)
      2. GOOGLE_OAUTH_TOKEN env var
      3. gcloud auth login credentials via legacy credential file (auto-refreshing)
      4. gcloud auth print-access-token (short-lived; works when #3 file is missing)
      5. GOOGLE_APPLICATION_CREDENTIALS service-account / authorized-user file
      6. ADC (gcloud auth application-default login)
    """
    from google.oauth2 import credentials as oauth2_creds
    import google.auth

    # Quota project is needed for end-user credentials to avoid "quota exceeded" warnings
    quota_project = (
        os.getenv("BQ_JOB_PROJECT_ID")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCP_PROJECT_ID")
        or os.getenv("BIGQUERY_PROJECT_ID")
    )

    def _with_quota(creds):
        if quota_project and hasattr(creds, "with_quota_project"):
            try:
                return creds.with_quota_project(quota_project)
            except Exception:
                pass
        return creds

    effective_token = token or OAUTH_TOKEN_ENV
    if effective_token:
        logger.debug("get_bq_credentials: using OAuth token (UI / env)")
        return oauth2_creds.Credentials(token=effective_token)

    # gcloud auth login — uses stored refresh token, auto-refreshes
    gcloud_creds = _get_gcloud_login_credentials()
    if gcloud_creds is not None:
        logger.info("get_bq_credentials: using gcloud auth login credentials")
        return _with_quota(gcloud_creds)

    # gcloud auth print-access-token — short-lived but works on any machine
    # where `gcloud auth login` was done, even if the credential file is missing
    gcloud_token = _get_gcloud_print_token()
    if gcloud_token:
        logger.info("get_bq_credentials: using token from gcloud auth print-access-token")
        return oauth2_creds.Credentials(token=gcloud_token, quota_project_id=quota_project)

    # Explicit credential file (service account or authorized_user)
    if SERVICE_ACCOUNT_FILE and os.path.exists(SERVICE_ACCOUNT_FILE):
        logger.info("get_bq_credentials: using GOOGLE_APPLICATION_CREDENTIALS file")
        with open(SERVICE_ACCOUNT_FILE) as f:
            cred_type = json.load(f).get("type", "")
        if cred_type == "service_account":
            creds, _ = google.auth.load_credentials_from_file(
                SERVICE_ACCOUNT_FILE,
                scopes=["https://www.googleapis.com/auth/bigquery"],
            )
        else:
            creds, _ = google.auth.load_credentials_from_file(SERVICE_ACCOUNT_FILE)
        return _with_quota(creds)

    # Last resort: ADC (gcloud auth application-default login)
    try:
        creds, _ = google.auth.default()
        logger.info("get_bq_credentials: using Application Default Credentials")
        return _with_quota(creds)
    except Exception as e:
        logger.warning("get_bq_credentials: ADC failed: %s", e)

    msg = (
        "No valid Google credentials found. Tried (in order):\n"
        "  1. OAuth token from UI / GOOGLE_OAUTH_TOKEN env\n"
        "  2. gcloud auth login (legacy credential file)\n"
        "  3. gcloud auth print-access-token\n"
        "  4. GOOGLE_APPLICATION_CREDENTIALS file\n"
        "  5. Application Default Credentials\n"
        "Run 'gcloud auth login' and restart the server, "
        "or set GOOGLE_OAUTH_TOKEN / GOOGLE_APPLICATION_CREDENTIALS in .env"
    )
    logger.error("get_bq_credentials: all methods exhausted — %s", msg)
    raise ValueError(msg)
