import asyncio
import json
import os
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

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
