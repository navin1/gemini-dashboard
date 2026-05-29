import os
import json
import pathlib
import subprocess
import httpx
from dotenv import load_dotenv
from fastapi import Header, HTTPException
from typing import Optional

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
            return None
    except Exception:
        return None

    cred_file = (
        pathlib.Path.home()
        / ".config" / "gcloud" / "legacy_credentials" / account / "adc.json"
    )
    if not cred_file.exists():
        return None

    try:
        data = json.loads(cred_file.read_text())
        from google.oauth2.credentials import Credentials
        return Credentials(
            token=None,
            refresh_token=data["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=data["client_id"],
            client_secret=data["client_secret"],
        )
    except Exception:
        return None


def get_bq_credentials(token: Optional[str] = None):
    """Return BigQuery credentials.

    Priority:
      1. Per-request OAuth token (from UI Authorization header)
      2. GOOGLE_OAUTH_TOKEN env var
      3. gcloud auth login credentials (auto-refreshing refresh token)
      4. GOOGLE_APPLICATION_CREDENTIALS service-account / authorized-user file
      5. ADC (gcloud auth application-default login)
    """
    from google.oauth2 import credentials as oauth2_creds
    import google.auth

    effective_token = token or OAUTH_TOKEN_ENV
    if effective_token:
        return oauth2_creds.Credentials(token=effective_token)

    # gcloud auth login — uses stored refresh token, auto-refreshes
    gcloud_creds = _get_gcloud_login_credentials()
    if gcloud_creds is not None:
        return gcloud_creds

    # Explicit credential file (service account or authorized_user)
    if SERVICE_ACCOUNT_FILE and os.path.exists(SERVICE_ACCOUNT_FILE):
        with open(SERVICE_ACCOUNT_FILE) as f:
            cred_type = json.load(f).get("type", "")
        if cred_type == "service_account":
            creds, _ = google.auth.load_credentials_from_file(
                SERVICE_ACCOUNT_FILE,
                scopes=["https://www.googleapis.com/auth/bigquery"],
            )
        else:
            creds, _ = google.auth.load_credentials_from_file(SERVICE_ACCOUNT_FILE)
        return creds

    # Last resort: ADC (gcloud auth application-default login)
    try:
        creds, _ = google.auth.default()
        return creds
    except Exception:
        pass

    raise ValueError(
        "No valid Google credentials found. "
        "Run: gcloud auth login  — or set GOOGLE_OAUTH_TOKEN / GOOGLE_APPLICATION_CREDENTIALS in .env"
    )
