from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
from models import GlossaryTerm
from auth import resolve_user, get_request_token
import gemini_client
import bigquery_client

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
    glossary_terms = [{"term": g.term, "definition": g.definition} for g in glossary]

    try:
        result = gemini_client.chat_turn(
            message=req.message,
            history=[m.model_dump() for m in req.history],
            glossary_terms=glossary_terms,
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
