"""Main FastAPI Application Entrypoint for Contract-Invoice AI Matching System."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .domain.database import SessionLocal, init_db
from .services.matching_service import MatchingService


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        MatchingService.ensure_default_agent(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Contract & Invoice AI Compliance Matching API",
    description=(
        "Standalone Clean Architecture AI Engine refactored from Odoo Enterprise 19 (et-addons/ai & ai_fields). "
        "Supports Contract (Source of Truth) RAG indexing, Invoice Excel-like Key-Value extraction, "
        "Human-in-the-loop editing, and AI Compliance Reconciliation."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root_health():
    return {
        "service": "Contract & Invoice AI Matching Backend",
        "architecture": "Clean Architecture (Core / Domain / Services / API) refactored from Odoo-ET 19",
        "docs": "/docs",
    }

