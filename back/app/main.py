from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import connect_to_mongo, close_mongo_connection
from app.api import admin, datasets, analytics, health, export, auth, reports, organizations, notifications
from app.core.logging import setup_logging, RequestLoggingMiddleware
from app.core.rate_limit import create_limiter, add_rate_limiting
from app.services.auth import AuthFailure


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    yield
    await close_mongo_connection()


settings = get_settings()

# Setup structured logging
setup_logging(settings.ENVIRONMENT.upper() == "DEVELOPMENT" and "DEBUG" or "INFO")

app = FastAPI(
    title="AQI Environmental Analytics API",
    description="API for environmental data upload, processing, and analytics",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(AuthFailure)
async def auth_failure_handler(request: Request, exc: AuthFailure):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

# Add middlewares (order matters - CORS first, then rate limiting, then logging)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.FRONTEND_ORIGINS.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# Rate limiting
limiter = create_limiter()
add_rate_limiting(app, limiter)

app.add_middleware(RequestLoggingMiddleware)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(organizations.router)
app.include_router(datasets.router)
app.include_router(analytics.router)
app.include_router(export.router)
app.include_router(reports.router)
app.include_router(admin.router)
app.include_router(notifications.router)


@app.get("/")
async def root():
    return {
        "message": "AQI Environmental Analytics API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }