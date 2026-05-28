import logging
import os
import time
import uuid
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

load_dotenv()

_log_level = os.getenv("UVICORN_LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s [%(levelname)-8s] %(name)-24s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Suppress noisy httpx/httpcore connection-pool chatter; keep warnings+
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

from database import engine, Base
import models  # noqa: F401 — registers SQLAlchemy models
from seed_data import seed
from routes import query, favorites, glossary, scorecard, pdf, chat, stream, airflow, schema_audit, excel_mapping

Base.metadata.create_all(bind=engine)
seed()

app = FastAPI(title="Gemini Workforce Dashboard", version="1.0.0")


@app.on_event("startup")
async def _pre_warm_schema():
    """Fetch BQ schema in the background so the first agent call has it cached."""
    import threading
    import gemini_client
    threading.Thread(target=gemini_client._get_schema, daemon=True, name="schema-prewarm").start()
    logger.info("Schema pre-warm thread started")


@app.middleware("http")
async def _request_logger(request: Request, call_next):
    req_id = uuid.uuid4().hex[:8]
    qs = f"?{request.url.query}" if request.url.query else ""
    logger.info(f"[{req_id}] → {request.method} {request.url.path}{qs}")
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
        ms = (time.perf_counter() - t0) * 1000
        log = logger.warning if response.status_code >= 400 else logger.info
        log(f"[{req_id}] ← {request.method} {request.url.path} {response.status_code} {ms:.0f}ms")
        return response
    except Exception:
        ms = (time.perf_counter() - t0) * 1000
        logger.exception(f"[{req_id}] ✗ {request.method} {request.url.path} UNHANDLED {ms:.0f}ms")
        raise


# CORS — allow local dev origins + any CLOUD_RUN_URL set at deploy time
_cors_origins = ["http://localhost:5173", "http://localhost:3000"]
if os.getenv("CLOUD_RUN_URL"):
    _cors_origins.append(os.getenv("CLOUD_RUN_URL"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(query.router)
app.include_router(favorites.router)
app.include_router(glossary.router)
app.include_router(scorecard.router)
app.include_router(pdf.router)
app.include_router(chat.router)
app.include_router(stream.router)
app.include_router(airflow.router)
app.include_router(schema_audit.router)
app.include_router(excel_mapping.router)


@app.get("/api/health")
async def health():
    import gemini_client
    return {
        "status": "ok",
        "ai_ready": gemini_client._model is not None,
        "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        "vertex_project": os.getenv("VERTEX_AI_PROJECT", ""),
        "vertex_location": os.getenv("VERTEX_AI_LOCATION", "us-central1"),
        "bigquery_project": os.getenv("BIGQUERY_PROJECT_ID", ""),
        "live_refresh_interval": stream.POLL_INTERVAL,
    }


# ── Serve built React SPA in production ──────────────────────────────────────
# In dev Vite runs separately; in production the Dockerfile copies dist → static/
_static = Path(__file__).parent / "static"
if _static.exists():
    _assets = _static / "assets"
    if _assets.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="static-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa(full_path: str):
        return FileResponse(str(_static / "index.html"))
