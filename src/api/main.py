"""PharmaInsight Data Platform - FastAPI Entrypoint.

Provides Data-as-a-Service access to Bronze, Silver, and Gold Parquet layers,
Data Quality Gate reporting, and Analytical Marts.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from src.api.routers import analytics, system, trials
from src.utils.config import settings
from src.utils.logger import setup_logger

logger = setup_logger("pharma_api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle handler."""
    logger.info("Initializing PharmaInsight API...")
    settings.ensure_directories()
    logger.info("Storage directories verified: Bronze, Silver, Gold.")
    yield
    logger.info("Shutting down PharmaInsight API.")


app = FastAPI(
    title="PharmaInsight Clinical Trials Data Platform API",
    description="""
## PharmaInsight: Clinical Trials ELT & Analytics Data-as-a-Service

This REST API serves high-performance analytical data marts and cleansed clinical trials
derived from **ClinicalTrials.gov API v2** via DuckDB and Parquet.

### Key Capabilities:
* **Analytical Marts (Gold)**: Sponsor benchmarking, drug intervention adoption, and duration timeline trends.
* **Study Exploration (Silver)**: Search, filter, and inspect normalized clinical trials and protocols.
* **Data Quality Gates**: Live audit reports verifying Primary Key uniqueness, referential integrity, and value bounds.
* **Swagger Interactive Docs**: Test all endpoints directly via the `/docs` UI.
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable permissive CORS for local development and dashboard integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register sub-routers
app.include_router(system.router)
app.include_router(analytics.router)
app.include_router(trials.router)


@app.get("/", include_in_schema=False)
def root_redirect() -> RedirectResponse:
    """Redirect root path directly to interactive Swagger docs."""
    return RedirectResponse(url="/docs")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)
