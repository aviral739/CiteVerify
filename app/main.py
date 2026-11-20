"""FastAPI application entrypoint for CiteVerify."""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.audit import router as audit_router
from app.api.documents import router as documents_router
from app.api.events import router as events_router
from app.api.export import router as export_router
from app.api.jobs import router as jobs_router
from app.api.reviews import router as reviews_router
from app.config import get_settings
from app.core.db import close_db, init_db
from app.core.exceptions import CiteVerifyException
from app.core.http import close_http_client
from app.models.schemas import HealthResponse

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events for startup and graceful shutdown."""
    # Ensure storage directories exist
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    settings.EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    settings.REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize SQLite database schema
    await init_db()

    yield

    # Clean up resources
    await close_http_client()
    await close_db()


app = FastAPI(
    title=settings.APP_NAME,
    description="Evidence-linked scientific claim verification engine.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS Configuration
origins = [str(o).strip().rstrip("/") for o in settings.CORS_ORIGINS] if isinstance(settings.CORS_ORIGINS, list) else [str(settings.CORS_ORIGINS).strip().rstrip("/")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
    expose_headers=["Content-Type", "Content-Disposition", "Content-Length", "X-Request-ID"],
    max_age=600,
)


# Global Exception Handling
@app.exception_handler(CiteVerifyException)
async def citeverify_exception_handler(request: Request, exc: CiteVerifyException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": True,
            "message": "An unexpected server error occurred.",
            "details": {"type": exc.__class__.__name__, "info": str(exc)},
        },
    )


# Health & Root Check
@app.get("/", tags=["system"])
async def root():
    """Root endpoint providing service status and links to documentation."""
    return {
        "service": settings.APP_NAME,
        "version": "0.1.0",
        "status": "ok",
        "documentation": "/docs",
        "health": "/health",
        "message": "CiteVerify Backend API is running. Visit /docs for the interactive API documentation.",
    }


@app.get("/health", response_model=HealthResponse, tags=["system"])
@app.get("/api/health", response_model=HealthResponse, tags=["system"])
async def health_check():
    """System health check endpoint."""
    return HealthResponse(
        status="ok",
        version="0.1.0",
        service=settings.APP_NAME,
        database_connected=True,
        llm_service_ready=True,
    )


# Register API Routers
app.include_router(documents_router)
app.include_router(jobs_router)
app.include_router(events_router)
app.include_router(reviews_router)
app.include_router(audit_router)
app.include_router(export_router)

