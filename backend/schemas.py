from pydantic import BaseModel
from typing import Optional, Any
import datetime


class GlossaryTermBase(BaseModel):
    term: str
    definition: str
    example: Optional[str] = None


class GlossaryTermCreate(GlossaryTermBase):
    pass


class GlossaryTermUpdate(BaseModel):
    term: Optional[str] = None
    definition: Optional[str] = None
    example: Optional[str] = None


class GlossaryTermOut(GlossaryTermBase):
    id: int
    is_default: bool
    user_id: Optional[str] = None
    created_at: Optional[datetime.datetime] = None

    class Config:
        from_attributes = True


class FavoriteBase(BaseModel):
    name: str
    nl_query: Optional[str] = None
    sql_query: str
    chart_type: Optional[str] = None
    widget_config: Optional[str] = None


class FavoriteCreate(FavoriteBase):
    pass


class FavoriteOut(FavoriteBase):
    id: int
    is_default: bool
    user_id: Optional[str] = None
    created_at: Optional[datetime.datetime] = None

    class Config:
        from_attributes = True


class QueryRequest(BaseModel):
    nl_query: str


class RefineRequest(BaseModel):
    sql: str
    nl_modification: str


class QueryResponse(BaseModel):
    sql: str
    chart_type: str
    title: str
    x_axis: Optional[str] = None
    y_axis: list[str] = []
    color_field: Optional[str] = None
    stacked: bool = False
    dual_axis: bool = False
    secondary_y: Optional[str] = None
    ai_description: str
    data: list[dict[str, Any]] = []
    error: Optional[str] = None


class DashboardLayoutSave(BaseModel):
    tab_name: str
    layout_json: str
    widgets_json: str


class PDFRequest(BaseModel):
    tab_name: str
    title: str
    widgets: list[dict[str, Any]]
