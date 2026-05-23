from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from sqlalchemy.orm import Session
from database import get_db
from models import Favorite
from schemas import FavoriteCreate, FavoriteOut
from auth import resolve_user, get_request_token
import bigquery_client

router = APIRouter(prefix="/api/favorites", tags=["favorites"])


@router.get("", response_model=list[FavoriteOut])
async def list_favorites(
    db: Session = Depends(get_db),
    user: dict = Depends(resolve_user),
):
    return db.query(Favorite).filter(
        (Favorite.is_default == True) | (Favorite.user_id == user["id"])
    ).order_by(Favorite.is_default.desc(), Favorite.created_at.desc()).all()


@router.post("", response_model=FavoriteOut)
async def create_favorite(
    fav: FavoriteCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(resolve_user),
):
    record = Favorite(**fav.model_dump(), is_default=False, user_id=user["id"])
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/{fav_id}")
async def delete_favorite(
    fav_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(resolve_user),
):
    fav = db.query(Favorite).filter(Favorite.id == fav_id).first()
    if not fav:
        raise HTTPException(status_code=404, detail="Favorite not found")
    if fav.is_default:
        raise HTTPException(status_code=403, detail="Cannot delete a default favorite")
    if fav.user_id != user["id"]:
        raise HTTPException(status_code=403, detail="Not your favorite")
    db.delete(fav)
    db.commit()
    return {"ok": True}


@router.post("/{fav_id}/run")
async def run_favorite(
    fav_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(resolve_user),
    token: Optional[str] = Depends(get_request_token),
):
    fav = db.query(Favorite).filter(Favorite.id == fav_id).first()
    if not fav:
        raise HTTPException(status_code=404, detail="Favorite not found")
    data = bigquery_client.run_query(fav.sql_query, token)
    return {
        "name": fav.name,
        "chart_type": fav.chart_type or "table",
        "sql": fav.sql_query,
        "data": data,
        "widget_config": fav.widget_config,
    }
