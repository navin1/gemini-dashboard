import logging
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import get_db
from models import GlossaryTerm
from schemas import QueryRequest, QueryResponse, RefineRequest
from auth import resolve_user, get_request_token
import gemini_client
import bigquery_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/query", tags=["query"])


class SqlRequest(BaseModel):
    sql: str


@router.post("/sql", response_model=QueryResponse)
async def run_sql_query(
    req: SqlRequest,
    token: Optional[str] = Depends(get_request_token),
):
    try:
        data = bigquery_client.run_query(req.sql.strip(), token)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"BigQuery error: {str(e)}")

    first = data[0] if data else {}
    num_keys = [k for k, v in first.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    str_keys = [k for k in first if k not in num_keys]
    x_axis = str_keys[0] if str_keys else (list(first.keys())[0] if first else None)
    y_axis = num_keys[:6]

    return QueryResponse(
        sql=req.sql.strip(),
        chart_type="table",
        title="SQL Result",
        x_axis=x_axis,
        y_axis=y_axis,
        color_field=None,
        stacked=False,
        dual_axis=False,
        secondary_y=None,
        ai_description="",
        data=data,
    )


@router.post("", response_model=QueryResponse)
async def run_nl_query(
    req: QueryRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(resolve_user),
    token: Optional[str] = Depends(get_request_token),
):
    # Fetch glossary for context
    glossary = db.query(GlossaryTerm).filter(
        (GlossaryTerm.is_default == True) | (GlossaryTerm.user_id == user["id"])
    ).all()
    glossary_terms = [{"term": g.term, "definition": g.definition} for g in glossary]

    logger.info(f"NL query: {req.nl_query!r}")
    try:
        widget_def = gemini_client.generate_widget(req.nl_query, glossary_terms)
        logger.info(f"Gemini generated chart_type={widget_def.get('chart_type')} title={widget_def.get('title')!r}")
    except Exception as e:
        logger.error(f"Gemini error for query {req.nl_query!r}: {e}")
        raise HTTPException(status_code=500, detail=f"Gemini error: {str(e)}")

    try:
        data = bigquery_client.run_query(widget_def["sql"], token)
    except Exception as e:
        logger.error(f"BQ error after Gemini query: {e}")
        raise HTTPException(status_code=500, detail=f"BigQuery error: {str(e)}")

    return QueryResponse(
        sql=widget_def.get("sql", ""),
        chart_type=widget_def.get("chart_type", "table"),
        title=widget_def.get("title", req.nl_query),
        x_axis=widget_def.get("x_axis"),
        y_axis=widget_def.get("y_axis", []),
        color_field=widget_def.get("color_field"),
        stacked=widget_def.get("stacked", False),
        dual_axis=widget_def.get("dual_axis", False),
        secondary_y=widget_def.get("secondary_y"),
        ai_description=widget_def.get("ai_description", ""),
        data=data,
    )


@router.post("/refine", response_model=QueryResponse)
async def refine_query(
    req: RefineRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(resolve_user),
    token: Optional[str] = Depends(get_request_token),
):
    glossary = db.query(GlossaryTerm).filter(
        (GlossaryTerm.is_default == True) | (GlossaryTerm.user_id == user["id"])
    ).all()
    glossary_terms = [{"term": g.term, "definition": g.definition} for g in glossary]

    try:
        widget_def = gemini_client.refine_widget(req.sql, req.nl_modification, glossary_terms)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini error: {str(e)}")

    try:
        data = bigquery_client.run_query(widget_def["sql"], token)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"BigQuery error: {str(e)}")

    return QueryResponse(
        sql=widget_def.get("sql", ""),
        chart_type=widget_def.get("chart_type", "table"),
        title=widget_def.get("title", ""),
        x_axis=widget_def.get("x_axis"),
        y_axis=widget_def.get("y_axis", []),
        color_field=widget_def.get("color_field"),
        stacked=widget_def.get("stacked", False),
        dual_axis=widget_def.get("dual_axis", False),
        secondary_y=widget_def.get("secondary_y"),
        ai_description=widget_def.get("ai_description", ""),
        data=data,
    )
