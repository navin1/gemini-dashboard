import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

load_dotenv()

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
