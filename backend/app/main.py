# =============================================================================
# main.py
# Purpose : Creates the FastAPI app and wires everything together.
# Logic   : - CORS so the browser frontend (a different origin) can call us.
#           - Includes the /analyze router.
#           - /health for a quick "is the server up?" check.
# Run     : uvicorn app.main:app --reload --port 8000
# =============================================================================
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routes import router

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tahlili")

app = FastAPI(title="Tahlili API", version="1.0.0")

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(router)

if settings.mock_llm:
    log.warning("MOCK_LLM is ON: returning demo data, the real model is NOT called.")


@app.get("/health")
def health() -> dict:
    """Quick status check (also shows if mock mode is on)."""
    return {"status": "ok", "mock": settings.mock_llm}
