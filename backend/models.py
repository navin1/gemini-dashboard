from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, func
from database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)  # Google sub
    email = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())


class GlossaryTerm(Base):
    __tablename__ = "glossary"
    id = Column(Integer, primary_key=True, autoincrement=True)
    term = Column(String, nullable=False)
    definition = Column(Text, nullable=False)
    example = Column(Text, nullable=True)
    is_default = Column(Boolean, default=False)
    user_id = Column(String, nullable=True)  # NULL = shared default
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Favorite(Base):
    __tablename__ = "favorites"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    nl_query = Column(Text, nullable=True)
    sql_query = Column(Text, nullable=False)
    chart_type = Column(String, nullable=True)
    widget_config = Column(Text, nullable=True)  # JSON string
    is_default = Column(Boolean, default=False)
    user_id = Column(String, nullable=True)  # NULL = shared default
    created_at = Column(DateTime, default=func.now())


class DashboardLayout(Base):
    __tablename__ = "dashboard_layouts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False)
    tab_name = Column(String, nullable=False)
    layout_json = Column(Text, nullable=False)   # react-grid-layout positions
    widgets_json = Column(Text, nullable=False)  # widget configs + cached data
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
