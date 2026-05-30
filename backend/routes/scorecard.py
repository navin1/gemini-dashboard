import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from auth import get_request_token
import bigquery_client

router = APIRouter(prefix="/api/scorecard", tags=["scorecard"])
logger = logging.getLogger(__name__)


async def _run(sql: str, token: Optional[str] = None) -> list[dict]:
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, bigquery_client.run_query, sql, token)
    except Exception as e:
        logger.exception("Scorecard query failed:\n%s", sql[:200])
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fte")
async def fte_scorecard(token: Optional[str] = Depends(get_request_token)):
    q = bigquery_client.FTE_SCORECARD_QUERIES
    kpi, cap_exp, fte, hier, donut, cap_exp_ftp = await asyncio.gather(
        _run(q["kpi_ytd_spend"], token),
        _run(q["monthly_capital_expense"], token),
        _run(q["monthly_fte"], token),
        _run(q["hierarchy_table"], token),
        _run(q["capital_expense_donut"], token),
        _run(q["monthly_cap_exp_ftp"], token),
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


@router.get("/vendor")
async def vendor_scorecard(token: Optional[str] = Depends(get_request_token)):
    q = bigquery_client.VENDOR_SCORECARD_QUERIES
    vendor, offshore, billtype, monthly, tier_monthly, cap_exp_ftp, tier, vendor_rc, kpis = await asyncio.gather(
        _run(q["vendor_table"], token),
        _run(q["offshore_onshore_bar"], token),
        _run(q["billtype_bar"], token),
        _run(q["monthly_vendor_spend"], token),
        _run(q["spend_by_tier_monthly"], token),
        _run(q["monthly_cap_exp_ftp"], token),
        _run(q["tier_breakdown"], token),
        _run(q["vendor_resource_count"], token),
        _run(q["vendor_kpis"], token),
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


@router.get("/hierarchy")
async def hierarchy_scorecard(token: Optional[str] = Depends(get_request_token)):
    q = bigquery_client.HIERARCHY_SCORECARD_QUERIES
    s = bigquery_client.SHARED_QUERIES
    drill, tier_monthly, billtype, tier = await asyncio.gather(
        _run(q["hierarchy_drill"], token),
        _run(q["spend_by_tier_monthly"], token),
        _run(s["monthly_vendor_spend"], token),
        _run(s["tier_breakdown"], token),
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


@router.get("/layout/{tab_name}")
async def get_layout(tab_name: str):
    """Return the saved widget layout for a dashboard layout persistence tab (dashboard layouts are stored client-side in localStorage per user)."""
    return {"tab_name": tab_name, "layout": None}
