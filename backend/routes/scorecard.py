import asyncio
import logging
import time
from fastapi import APIRouter, Depends
from typing import Optional
from auth import get_request_token
import bigquery_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scorecard", tags=["scorecard"])

_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 300  # 5 minutes

async def _cached(key: str, factory) -> dict:
    """Return cached scorecard result, or run factory() and cache it."""
    entry = _CACHE.get(key)
    if entry and time.time() - entry[0] < _TTL:
        logger.info(f"{key} scorecard: cache hit")
        return entry[1]
    result = await factory()
    _CACHE[key] = (time.time(), result)
    return result


async def _run(sql: str, label: str = "", token: Optional[str] = None) -> list[dict]:
    """Run a BQ query; return [] on failure so one bad query never kills the whole response."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, bigquery_client.run_query, sql, token)
    except Exception as e:
        logger.error(f"Scorecard query failed [{label}]: {e}")
        return []


@router.get("/uat")
async def uat_scorecard(token: Optional[str] = Depends(get_request_token)):
    async def _fetch():
        logger.info("UAT scorecard: starting 6 BQ queries")
        q = bigquery_client.FTE_SCORECARD_QUERIES
        kpi, cap_exp, fte, hier, donut, cap_exp_ftp = await asyncio.gather(
            _run(q["kpi_ytd_spend"],          "uat/kpi_ytd_spend",          token),
            _run(q["monthly_capital_expense"], "uat/monthly_capital_expense", token),
            _run(q["monthly_fte"],             "uat/monthly_fte",             token),
            _run(q["hierarchy_table"],         "uat/hierarchy_table",         token),
            _run(q["capital_expense_donut"],   "uat/capital_expense_donut",   token),
            _run(q["monthly_cap_exp_ftp"],     "uat/monthly_cap_exp_ftp",     token),
        )
        return {
            "kpi": kpi,
            "monthly_capital_expense": cap_exp,
            "monthly_fte": fte,
            "hierarchy_table": hier,
            "capital_expense_donut": donut,
            "monthly_cap_exp_ftp": cap_exp_ftp,
            "_sql": {k: v.strip() for k, v in q.items()},
        }
    return await _cached("uat", _fetch)


@router.get("/prd")
async def prd_scorecard(token: Optional[str] = Depends(get_request_token)):
    async def _fetch():
        logger.info("PRD scorecard: starting 9 BQ queries")
        q = bigquery_client.VENDOR_SCORECARD_QUERIES
        vendor, offshore, billtype, monthly, tier_monthly, cap_exp_ftp, tier, vendor_rc, kpis = await asyncio.gather(
            _run(q["vendor_table"],          "prd/vendor_table",          token),
            _run(q["offshore_onshore_bar"],  "prd/offshore_onshore_bar",  token),
            _run(q["billtype_bar"],          "prd/billtype_bar",          token),
            _run(q["monthly_vendor_spend"],  "prd/monthly_vendor_spend",  token),
            _run(q["spend_by_tier_monthly"], "prd/spend_by_tier_monthly", token),
            _run(q["monthly_cap_exp_ftp"],   "prd/monthly_cap_exp_ftp",   token),
            _run(q["tier_breakdown"],        "prd/tier_breakdown",        token),
            _run(q["vendor_resource_count"], "prd/vendor_resource_count", token),
            _run(q["vendor_kpis"],           "prd/vendor_kpis",           token),
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
            "_sql": {k: v.strip() for k, v in q.items()},
        }
    return await _cached("prd", _fetch)


@router.get("/dev")
async def dev_scorecard(token: Optional[str] = Depends(get_request_token)):
    async def _fetch():
        logger.info("DEV scorecard: starting 4 BQ queries")
        q = bigquery_client.HIERARCHY_SCORECARD_QUERIES
        s = bigquery_client.SHARED_QUERIES
        drill, tier_monthly, billtype, tier = await asyncio.gather(
            _run(q["hierarchy_drill"],       "dev/hierarchy_drill",       token),
            _run(q["spend_by_tier_monthly"], "dev/spend_by_tier_monthly", token),
            _run(s["monthly_vendor_spend"],  "dev/monthly_vendor_spend",  token),
            _run(s["tier_breakdown"],        "dev/tier_breakdown",        token),
        )
        return {
            "hierarchy_drill": drill,
            "spend_by_tier_monthly": tier_monthly,
            "billtype_monthly": billtype,
            "tier_breakdown": tier,
            "_sql": {
                **{k: v.strip() for k, v in q.items()},
                **{k: v.strip() for k, v in s.items()},
            },
        }
    return await _cached("dev", _fetch)


@router.get("/layout/{tab_name}")
async def get_layout(tab_name: str):
    """Return the saved widget layout for a dashboard layout persistence tab (dashboard layouts are stored client-side in localStorage per user)."""
    return {"tab_name": tab_name, "layout": None}
