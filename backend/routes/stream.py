import asyncio
import json
import os
import time
import uuid
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth import get_request_token
import bigquery_client

router = APIRouter(prefix="/api/stream", tags=["stream"])

# Poll interval: how often BigQuery is re-queried and data pushed to clients.
# Configurable via LIVE_REFRESH_INTERVAL in .env (seconds, default 60).
# Minimum enforced at 10s to avoid hammering BigQuery.
_RAW = int(os.getenv("LIVE_REFRESH_INTERVAL", "60"))
POLL_INTERVAL = max(10, _RAW)

# Heartbeat keeps the connection alive through proxies/load-balancers
# that close idle SSE streams (Cloud Run times out at 60s by default).
HEARTBEAT_INTERVAL = 15  # seconds


async def _sse_stream(
    request: Request,
    fetch_fn,           # async callable → dict payload
    token: Optional[str],
) -> AsyncGenerator[str, None]:
    """
    Generic SSE generator:
      1. Sends current data immediately on connect.
      2. Re-queries BigQuery every POLL_INTERVAL seconds.
      3. Sends a heartbeat comment every HEARTBEAT_INTERVAL seconds so
         the connection isn't dropped by proxies before the next poll.
    """
    loop = asyncio.get_running_loop()
    elapsed = 0

    while not await request.is_disconnected():
        if elapsed == 0 or elapsed >= POLL_INTERVAL:
            try:
                data = await fetch_fn(token)
                yield f"data: {json.dumps(data)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            elapsed = 0

        await asyncio.sleep(HEARTBEAT_INTERVAL)
        elapsed += HEARTBEAT_INTERVAL

        # SSE comment — invisible to the client but keeps TCP alive
        yield ": heartbeat\n\n"


# ── per-scorecard fetch helpers ───────────────────────────────────────────────

async def _fetch_fte(token):
    loop = asyncio.get_running_loop()
    q = bigquery_client.FTE_SCORECARD_QUERIES
    kpi, cap_exp, fte, hier, donut, cap_exp_ftp = await asyncio.gather(
        loop.run_in_executor(None, bigquery_client.run_query, q["kpi_ytd_spend"], token),
        loop.run_in_executor(None, bigquery_client.run_query, q["monthly_capital_expense"], token),
        loop.run_in_executor(None, bigquery_client.run_query, q["monthly_fte"], token),
        loop.run_in_executor(None, bigquery_client.run_query, q["hierarchy_table"], token),
        loop.run_in_executor(None, bigquery_client.run_query, q["capital_expense_donut"], token),
        loop.run_in_executor(None, bigquery_client.run_query, q["monthly_cap_exp_ftp"], token),
    )
    return {
        "kpi": kpi,
        "monthly_capital_expense": cap_exp,
        "monthly_fte": fte,
        "hierarchy_table": hier,
        "capital_expense_donut": donut,
        "monthly_cap_exp_ftp": cap_exp_ftp,
    }


async def _fetch_vendor(token):
    loop = asyncio.get_running_loop()
    q = bigquery_client.VENDOR_SCORECARD_QUERIES
    vendor, offshore, billtype, monthly, tier_monthly, cap_exp_ftp, tier, vendor_rc, kpis = await asyncio.gather(
        loop.run_in_executor(None, bigquery_client.run_query, q["vendor_table"], token),
        loop.run_in_executor(None, bigquery_client.run_query, q["offshore_onshore_bar"], token),
        loop.run_in_executor(None, bigquery_client.run_query, q["billtype_bar"], token),
        loop.run_in_executor(None, bigquery_client.run_query, q["monthly_vendor_spend"], token),
        loop.run_in_executor(None, bigquery_client.run_query, q["spend_by_tier_monthly"], token),
        loop.run_in_executor(None, bigquery_client.run_query, q["monthly_cap_exp_ftp"], token),
        loop.run_in_executor(None, bigquery_client.run_query, q["tier_breakdown"], token),
        loop.run_in_executor(None, bigquery_client.run_query, q["vendor_resource_count"], token),
        loop.run_in_executor(None, bigquery_client.run_query, q["vendor_kpis"], token),
    )
    return {
        "vendor_table": vendor,
        "offshore_onshore_bar": offshore,
        "billtype_bar": billtype,
        "monthly_vendor_spend": monthly,
        "spend_by_tier_monthly": tier_monthly,
        "monthly_cap_exp_ftp": cap_exp_ftp,
        "tier_breakdown": tier,
        "vendor_resource_count": vendor_rc,
        "vendor_kpis": kpis,
    }


async def _fetch_hierarchy(token):
    loop = asyncio.get_running_loop()
    q = bigquery_client.HIERARCHY_SCORECARD_QUERIES
    s = bigquery_client.SHARED_QUERIES
    drill, tier_monthly, billtype, tier = await asyncio.gather(
        loop.run_in_executor(None, bigquery_client.run_query, q["hierarchy_drill"], token),
        loop.run_in_executor(None, bigquery_client.run_query, q["spend_by_tier_monthly"], token),
        loop.run_in_executor(None, bigquery_client.run_query, s["monthly_vendor_spend"], token),
        loop.run_in_executor(None, bigquery_client.run_query, s["tier_breakdown"], token),
    )
    return {
        "hierarchy_drill": drill,
        "spend_by_tier_monthly": tier_monthly,
        "billtype_monthly": billtype,
        "tier_breakdown": tier,
    }


# ── SSE endpoints ─────────────────────────────────────────────────────────────

@router.get("/fte")
async def stream_fte(
    request: Request,
    token: Optional[str] = Depends(get_request_token),
):
    return StreamingResponse(
        _sse_stream(request, _fetch_fte, token),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/vendor")
async def stream_vendor(
    request: Request,
    token: Optional[str] = Depends(get_request_token),
):
    return StreamingResponse(
        _sse_stream(request, _fetch_vendor, token),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/hierarchy")
async def stream_hierarchy(
    request: Request,
    token: Optional[str] = Depends(get_request_token),
):
    return StreamingResponse(
        _sse_stream(request, _fetch_hierarchy, token),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/config")
async def stream_config():
    """Expose the active poll interval so the frontend can show it."""
    return {"poll_interval_seconds": POLL_INTERVAL}


# ── Custom widget streaming ───────────────────────────────────────────────────
# SSE is GET-only, so SQL can't be sent in the request body.
# Solution: two-step session pattern.
#   1. POST /api/stream/session  → register widget SQLs, get session_id
#   2. GET  /api/stream/custom/{session_id} → SSE stream for those widgets
#
# Sessions are in-memory (ephemeral per backend instance) and expire after
# SESSION_TTL seconds of inactivity to prevent memory leaks.

SESSION_TTL = 600  # seconds — session expires if no SSE connection opens

_sessions: dict[str, dict] = {}  # session_id → {widgets, token, last_used}


class WidgetEntry(BaseModel):
    id: str
    sql: str


class SessionRequest(BaseModel):
    widgets: list[WidgetEntry]


@router.post("/session")
async def create_session(
    body: SessionRequest,
    token: Optional[str] = Depends(get_request_token),
):
    """
    Register a list of {id, sql} widget definitions.
    Returns a session_id to pass to GET /api/stream/custom/{session_id}.
    Call again whenever widgets change (old session will expire on its own).
    """
    if not body.widgets:
        raise HTTPException(status_code=400, detail="widgets list must not be empty")

    session_id = str(uuid.uuid4())
    _sessions[session_id] = {
        "widgets": [w.model_dump() for w in body.widgets],
        "token": token,
        "last_used": time.time(),
    }
    # Evict sessions older than SESSION_TTL
    now = time.time()
    stale = [k for k, v in _sessions.items() if now - v["last_used"] > SESSION_TTL]
    for k in stale:
        del _sessions[k]

    return {"session_id": session_id, "widget_count": len(body.widgets)}


async def _fetch_custom(widgets: list[dict], token: Optional[str]) -> dict:
    """Re-run every widget's SQL in parallel and return {id → data} mapping."""
    loop = asyncio.get_running_loop()

    async def run_one(w: dict):
        try:
            data = await loop.run_in_executor(
                None, bigquery_client.run_query, w["sql"], token
            )
            return {"id": w["id"], "data": data, "error": None}
        except Exception as e:
            return {"id": w["id"], "data": [], "error": str(e)}

    results = await asyncio.gather(*[run_one(w) for w in widgets])
    return {"updates": results}


@router.get("/custom/{session_id}")
async def stream_custom(
    session_id: str,
    request: Request,
    token: Optional[str] = Depends(get_request_token),
):
    """
    SSE stream that re-runs the SQL for each widget registered in the session
    every POLL_INTERVAL seconds and pushes the refreshed data.

    Each event: data: {"updates": [{"id": "...", "data": [...], "error": null}, ...]}
    """
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found or expired. Call POST /api/stream/session again.")

    session = _sessions[session_id]
    session["last_used"] = time.time()
    widgets = session["widgets"]
    # Prefer the token from the session (set at session creation time)
    effective_token = session.get("token") or token

    async def generate() -> AsyncGenerator[str, None]:
        elapsed = 0
        while not await request.is_disconnected():
            if elapsed == 0 or elapsed >= POLL_INTERVAL:
                payload = await _fetch_custom(widgets, effective_token)
                yield f"data: {json.dumps(payload)}\n\n"
                elapsed = 0
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            elapsed += HEARTBEAT_INTERVAL
            yield ": heartbeat\n\n"

        # Clean up session when client disconnects
        _sessions.pop(session_id, None)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
