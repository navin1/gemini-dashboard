from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import GlossaryTerm
from schemas import GlossaryTermCreate, GlossaryTermUpdate, GlossaryTermOut
from auth import resolve_user

router = APIRouter(prefix="/api/glossary", tags=["glossary"])


@router.get("", response_model=list[GlossaryTermOut])
async def list_terms(
    db: Session = Depends(get_db),
    user: dict = Depends(resolve_user),
):
    return db.query(GlossaryTerm).filter(
        (GlossaryTerm.is_default == True) | (GlossaryTerm.user_id == user["id"])
    ).order_by(GlossaryTerm.term).all()


@router.post("", response_model=GlossaryTermOut)
async def create_term(
    payload: GlossaryTermCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(resolve_user),
):
    term = GlossaryTerm(**payload.model_dump(), is_default=False, user_id=user["id"])
    db.add(term)
    db.commit()
    db.refresh(term)
    return term


@router.put("/{term_id}", response_model=GlossaryTermOut)
async def update_term(
    term_id: int,
    payload: GlossaryTermUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(resolve_user),
):
    term = db.query(GlossaryTerm).filter(GlossaryTerm.id == term_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")
    if term.is_default:
        raise HTTPException(status_code=403, detail="Cannot edit default terms — create a custom override instead")
    if term.user_id != user["id"]:
        raise HTTPException(status_code=403, detail="Not your term")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(term, field, value)
    db.commit()
    db.refresh(term)
    return term


@router.delete("/{term_id}")
async def delete_term(
    term_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(resolve_user),
):
    term = db.query(GlossaryTerm).filter(GlossaryTerm.id == term_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")
    if term.is_default:
        raise HTTPException(status_code=403, detail="Cannot delete default terms")
    if term.user_id != user["id"]:
        raise HTTPException(status_code=403, detail="Not your term")
    db.delete(term)
    db.commit()
    return {"ok": True}
