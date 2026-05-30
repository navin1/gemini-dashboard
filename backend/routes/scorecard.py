import asyncio
import logging
from fastapi import APIRouter, Depends
from typing import Optional
from auth import get_request_token
import bigquery_client

router = APIRouter(prefix="/api/scorecard", tags=["scorecard"])
logger = logging.getLogger(__name__)


async def _run_safe(sql: str, token: Optional[str] = None) -> tuple[list[dict], str | None]:
    """Run a BQ query. Returns (rows, None) on success or ([], error_message) on failure."""
    loop = asyncio.get_running_loop()
    try:
        rows = await loop.run_in_executor(None, bigquery_client.run_query, sql, token)
        return rows, None
    except Exception as e:
        logger.exception("Scorecard query failed:\n%s", sql[:300])
        return [], str(e)


def _errors_map(**kwargs: str | None) -> dict[str, str]:
    return {k: v for k, v in kwargs.items() if v}


@router.get("/fte")
async def fte_scorecard(token: Optional[str] = Depends(get_request_token)):
    q = bigquery_client.FTE_SCORECARD_QUERIES
    (kpi, e_kpi), (cap_exp, e_cap_exp), (fte, e_fte), (hier, e_hier), (donut, e_donut), (cap_exp_ftp, e_cef) = \
        await asyncio.gather(
            _run_safe(q["kpi_ytd_spend"], token),
            _run_safe(q["monthly_capital_expense"], token),
            _run_safe(q["monthly_fte"], token),
            _run_safe(q["hierarchy_table"], token),
            _run_safe(q["capital_expense_donut"], token),
            _run_safe(q["monthly_cap_exp_ftp"], token),
        )
    return {
        "kpi": kpi,
        "monthly_capital_expense": cap_exp,
        "monthly_fte": fte,
        "hierarchy_table": hier,
        "capital_expense_donut": donut,
        "monthly_cap_exp_ftp": cap_exp_ftp,
        "_errors": _errors_map(
            kpi_ytd_spend=e_kpi,
            monthly_capital_expense=e_cap_exp,
            monthly_fte=e_fte,
            hierarchy_table=e_hier,
            capital_expense_donut=e_donut,
            monthly_cap_exp_ftp=e_cef,
        ),
        "_sql": {k: v.strip() for k, v in q.items()},
    }


@router.get("/vendor")
async def vendor_scorecard(token: Optional[str] = Depends(get_request_token)):
    q = bigquery_client.VENDOR_SCORECARD_QUERIES
    (vendor, e_v), (offshore, e_o), (billtype, e_b), (monthly, e_m), \
    (tier_monthly, e_tm), (cap_exp_ftp, e_cef), (tier, e_t), (vendor_rc, e_rc), (kpis, e_k) = \
        await asyncio.gather(
            _run_safe(q["vendor_table"], token),
            _run_safe(q["offshore_onshore_bar"], token),
            _run_safe(q["billtype_bar"], token),
            _run_safe(q["monthly_vendor_spend"], token),
            _run_safe(q["spend_by_tier_monthly"], token),
            _run_safe(q["monthly_cap_exp_ftp"], token),
            _run_safe(q["tier_breakdown"], token),
            _run_safe(q["vendor_resource_count"], token),
            _run_safe(q["vendor_kpis"], token),
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
        "_errors": _errors_map(
            vendor_table=e_v,
            offshore_onshore_bar=e_o,
            billtype_bar=e_b,
            monthly_vendor_spend=e_m,
            spend_by_tier_monthly=e_tm,
            monthly_cap_exp_ftp=e_cef,
            tier_breakdown=e_t,
            vendor_resource_count=e_rc,
            vendor_kpis=e_k,
        ),
        "_sql": {k: v.strip() for k, v in q.items()},
    }


@router.get("/hierarchy")
async def hierarchy_scorecard(token: Optional[str] = Depends(get_request_token)):
    q = bigquery_client.HIERARCHY_SCORECARD_QUERIES
    s = bigquery_client.SHARED_QUERIES
    (drill, e_d), (tier_monthly, e_tm), (billtype, e_b), (tier, e_t) = \
        await asyncio.gather(
            _run_safe(q["hierarchy_drill"], token),
            _run_safe(q["spend_by_tier_monthly"], token),
            _run_safe(s["monthly_vendor_spend"], token),
            _run_safe(s["tier_breakdown"], token),
        )
    return {
        "hierarchy_drill": drill,
        "spend_by_tier_monthly": tier_monthly,
        "billtype_monthly": billtype,
        "tier_breakdown": tier,
        "_errors": _errors_map(
            hierarchy_drill=e_d,
            spend_by_tier_monthly=e_tm,
            monthly_vendor_spend=e_b,
            tier_breakdown=e_t,
        ),
        "_sql": {
            **{k: v.strip() for k, v in q.items()},
            **{k: v.strip() for k, v in s.items()},
        },
    }


@router.get("/layout/{tab_name}")
async def get_layout(tab_name: str):
    """Return the saved widget layout for a dashboard layout persistence tab (dashboard layouts are stored client-side in localStorage per user)."""
    return {"tab_name": tab_name, "layout": None}
