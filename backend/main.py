import os
import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from dotenv import load_dotenv

load_dotenv()

# Configure logging before any module that creates a logger is imported.
# Reads LOG_LEVEL, then UVICORN_LOG_LEVEL, then defaults to INFO.
_log_level = (os.getenv("LOG_LEVEL") or os.getenv("UVICORN_LOG_LEVEL") or "INFO").upper()
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,  # override any handlers uvicorn already attached
)

from database import engine, Base
import models  # noqa: F401 — registers SQLAlchemy models
from seed_data import seed
from routes import query, favorites, glossary, scorecard, pdf, chat

Base.metadata.create_all(bind=engine)
seed()

app = FastAPI(title="Gemini Workforce Dashboard", version="1.0.0")

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

_main_logger = logging.getLogger("main")

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    _main_logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": str(exc)})


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
