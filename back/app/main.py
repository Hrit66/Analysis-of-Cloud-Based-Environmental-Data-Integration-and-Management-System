from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import connect_to_mongo, close_mongo_connection
from app.api import datasets, analytics, health


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    yield
    await close_mongo_connection()


settings = get_settings()

app = FastAPI(
    title="AQI Environmental Analytics API",
    description="API for environmental data upload, processing, and analytics",
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

app.include_router(health.router)
app.include_router(datasets.router)
app.include_router(analytics.router)


@app.get("/")
async def root():
    return {
        "message": "AQI Environmental Analytics API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }