from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def create_limiter() -> Limiter:
    return Limiter(
        key_func=get_remote_address,
        default_limits=["100/minute", "1000/hour"],
        storage_uri="memory://",
    )


def add_rate_limiting(app: FastAPI, limiter: Limiter):
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        # Skip rate limiting for health checks
        if request.url.path in ["/health", "/health/ready", "/docs", "/openapi.json", "/redoc"]:
            return await call_next(request)
        return await call_next(request)


def get_limiter(request: Request) -> Limiter:
    return request.app.state.limiter