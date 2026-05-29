import asyncio
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import Optional, AsyncGenerator
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
from models import GlossaryTerm
from auth import resolve_user, get_request_token
import gemini_client
import bigquery_client
import json

# Hidden system entity mappings loaded once at import time
_ENTITY_GLOSSARY: list[dict] = gemini_client._load_entity_glossary()

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str   # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    text: str
    intent: str
    widget: dict | None = None
    suggested_questions: list[str] = []


def _normalize_error(msg: str) -> str:
    if "not initialised" in msg or "VERTEX_AI_PROJECT" in msg:
        return "Vertex AI is not configured. Set VERTEX_AI_PROJECT in .env and ensure credentials are available."
    if "PERMISSION_DENIED" in msg or "permission denied" in msg.lower():
        return "Vertex AI access denied. Ensure roles/aiplatform.user is granted."
    if any(k in msg for k in ("RESOURCE_EXHAUSTED", "429", "quota", "Quota exceeded", "rate limit")):
        return "Vertex AI quota exceeded. Please wait a few minutes and try again."
    return msg


def _fetch_widget_data(sql: str, token: str | None) -> list:
    """Return widget rows, reusing the agent's BQ cache when available.

    The agent already ran this SQL during its tool-call loop and stored the
    full result in _BQ_FULL_CACHE. Reusing it eliminates a redundant BQ
    round-trip on every response that produces a widget.
    """
    cached = gemini_client._BQ_FULL_CACHE.get(sql)
    if cached and time.monotonic() - cached[0] < gemini_client._BQ_RESULT_TTL:
        return cached[1]
    return bigquery_client.run_query(sql, token)


def _build_response(result: dict, token: str | None) -> ChatResponse:
    """Populate widget data and return a ChatResponse."""
    widget = result.get("widget")
    if widget and widget.get("sql"):
        try:
            widget["data"] = _fetch_widget_data(widget["sql"], token)
        except Exception as e:
            widget["data"] = []
            widget["error"] = str(e)
    return ChatResponse(
        text=result.get("text", ""),
        intent=result.get("intent", "explain"),
        widget=widget if widget and (widget.get("data") or widget.get("error")) else None,
        suggested_questions=result.get("suggested_questions", []),
    )


@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(resolve_user),
    token: Optional[str] = Depends(get_request_token),
):
    glossary = db.query(GlossaryTerm).filter(
        (GlossaryTerm.is_default == True) | (GlossaryTerm.user_id == user["id"])
    ).all()
    glossary_terms = [{"term": g.term, "definition": g.definition} for g in glossary] + _ENTITY_GLOSSARY
    history = [m.model_dump() for m in req.history]

    try:
        if gemini_client.is_analytical(req.message):
            result = gemini_client.agent_chat(
                message=req.message,
                history=history,
                glossary_terms=glossary_terms,
                token=token,
            )
        else:
            result = gemini_client.chat_turn(
                message=req.message,
                history=history,
                glossary_terms=glossary_terms,
            )
    except Exception as e:
        msg = _normalize_error(str(e))
        if "not configured" in msg or "not initialised" in str(e):
            raise HTTPException(status_code=503, detail=msg)
        if "access denied" in msg:
            raise HTTPException(status_code=403, detail=msg)
        if "quota exceeded" in msg:
            raise HTTPException(status_code=429, detail=msg)
        raise HTTPException(status_code=500, detail=f"AI error: {msg}")

    return _build_response(result, token)


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(resolve_user),
    token: Optional[str] = Depends(get_request_token),
):
    glossary = db.query(GlossaryTerm).filter(
        (GlossaryTerm.is_default == True) | (GlossaryTerm.user_id == user["id"])
    ).all()
    glossary_terms = [{"term": g.term, "definition": g.definition} for g in glossary] + _ENTITY_GLOSSARY
    history = [m.model_dump() for m in req.history]
    analytical = gemini_client.is_analytical(req.message)

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            if not analytical:
                # ── Fast path: single Gemini call, no tools, no BQ ─────────────
                yield f"data: {json.dumps({'type': 'status', 'message': 'Thinking…'})}\n\n"
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, gemini_client.chat_turn, req.message, history, glossary_terms
                )
                payload = _build_response(result, token)
                yield f"data: {json.dumps({'type': 'result', 'data': payload.model_dump()})}\n\n"
                return

            # ── Agent path: tool-calling loop with BQ ─────────────────────────
            result = None
            async for event in gemini_client.agent_chat_stream(
                message=req.message,
                history=history,
                glossary_terms=glossary_terms,
                token=token,
            ):
                if await request.is_disconnected():
                    return

                if event["type"] == "result":
                    result = event["data"]
                elif event["type"] == "error":
                    yield f"data: {json.dumps({'type': 'error', 'message': _normalize_error(event['message'])})}\n\n"
                    return
                else:
                    yield f"data: {json.dumps(event)}\n\n"

            if result:
                payload = _build_response(result, token)
                yield f"data: {json.dumps({'type': 'result', 'data': payload.model_dump()})}\n\n"

        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': _normalize_error(str(exc))})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
