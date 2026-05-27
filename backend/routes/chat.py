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

    try:
        result = gemini_client.agent_chat(
            message=req.message,
            history=[m.model_dump() for m in req.history],
            glossary_terms=glossary_terms,
            token=token,
        )
    except Exception as e:
        msg = str(e)
        if "not initialised" in msg or "VERTEX_AI_PROJECT" in msg:
            raise HTTPException(status_code=503, detail="Vertex AI is not configured. Set VERTEX_AI_PROJECT in .env and ensure credentials are available.")
        if "PERMISSION_DENIED" in msg or "permission denied" in msg.lower():
            raise HTTPException(status_code=403, detail="Vertex AI access denied. Ensure your account or service account has roles/aiplatform.user.")
        if any(k in msg for k in ("RESOURCE_EXHAUSTED", "429", "quota", "Quota exceeded", "rate limit")):
            raise HTTPException(status_code=429, detail="Vertex AI quota exceeded. Please wait a few minutes and try again.")
        raise HTTPException(status_code=500, detail=f"AI error: {msg}")

    widget = result.get("widget")

    # If a widget was requested, run its SQL now
    if widget and widget.get("sql"):
        try:
            data = bigquery_client.run_query(widget["sql"], token)
            widget["data"] = data
        except Exception as e:
            widget["data"] = []
            widget["error"] = str(e)

    return ChatResponse(
        text=result.get("text", ""),
        intent=result.get("intent", "explain"),
        widget=widget if widget and (widget.get("data") or widget.get("error")) else None,
        suggested_questions=result.get("suggested_questions", []),
    )


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

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            async for event in gemini_client.agent_chat_stream(
                message=req.message,
                history=[m.model_dump() for m in req.history],
                glossary_terms=glossary_terms,
                token=token,
            ):
                if await request.is_disconnected():
                    break

                if event["type"] == "result":
                    # Run the widget SQL to populate data before sending final result
                    result = event["data"]
                    widget = result.get("widget")
                    if widget and widget.get("sql"):
                        try:
                            data = bigquery_client.run_query(widget["sql"], token)
                            widget["data"] = data
                        except Exception as e:
                            widget["data"] = []
                            widget["error"] = str(e)

                    payload = ChatResponse(
                        text=result.get("text", ""),
                        intent=result.get("intent", "explain"),
                        widget=widget if widget and (widget.get("data") or widget.get("error")) else None,
                        suggested_questions=result.get("suggested_questions", []),
                    )
                    yield f"data: {json.dumps({'type': 'result', 'data': payload.model_dump()})}\n\n"

                elif event["type"] == "error":
                    msg = event["message"]
                    if "not initialised" in msg or "VERTEX_AI_PROJECT" in msg:
                        msg = "Vertex AI is not configured. Set VERTEX_AI_PROJECT in .env."
                    elif "PERMISSION_DENIED" in msg or "permission denied" in msg.lower():
                        msg = "Vertex AI access denied. Ensure roles/aiplatform.user is granted."
                    elif any(k in msg for k in ("RESOURCE_EXHAUSTED", "429", "quota", "Quota exceeded")):
                        msg = "Vertex AI quota exceeded. Please wait a few minutes and try again."
                    yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"

                else:
                    yield f"data: {json.dumps(event)}\n\n"

        except Exception as exc:
            msg = str(exc)
            if "not initialised" in msg or "VERTEX_AI_PROJECT" in msg:
                msg = "Vertex AI is not configured. Set VERTEX_AI_PROJECT in .env."
            elif "PERMISSION_DENIED" in msg or "permission denied" in msg.lower():
                msg = "Vertex AI access denied. Ensure roles/aiplatform.user is granted."
            elif any(k in msg for k in ("RESOURCE_EXHAUSTED", "429", "quota", "Quota exceeded")):
                msg = "Vertex AI quota exceeded. Please wait a few minutes and try again."
            yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
