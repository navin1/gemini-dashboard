import os
import httpx
from dotenv import load_dotenv
from fastapi import Header, HTTPException, Query
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


def get_request_token(
    authorization: Optional[str] = Header(default=None),
    token: Optional[str] = Query(default=None),
) -> Optional[str]:
    """FastAPI dependency — extract Bearer token from Authorization header or
    ?token= query param (used by EventSource, which cannot send custom headers)."""
    if authorization and authorization.startswith("Bearer "):
        return authorization.split(" ", 1)[1]
    if token:
        return token
    return OAUTH_TOKEN_ENV or None


def get_bq_credentials(token: Optional[str] = None):
    """Return BigQuery credentials. Priority: per-request token > env token > service account > ADC."""
    from google.oauth2 import credentials as oauth2_creds
    import google.auth

    effective_token = token or OAUTH_TOKEN_ENV
    if effective_token:
        return oauth2_creds.Credentials(token=effective_token)

    # Handles both service_account and authorized_user (ADC) credential file formats.
    # authorized_user credentials have scopes baked in; passing scopes= causes an error.
    if SERVICE_ACCOUNT_FILE and os.path.exists(SERVICE_ACCOUNT_FILE):
        import json
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

    # Last resort: pick up whatever ADC the environment provides
    try:
        creds, _ = google.auth.default()
        return creds
    except Exception:
        pass

    raise ValueError(
        "No valid Google credentials found. "
        "Set GOOGLE_OAUTH_TOKEN or GOOGLE_APPLICATION_CREDENTIALS in .env"
    )
