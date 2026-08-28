import logging
import json
import sys
from datetime import datetime
from typing import Any, Dict
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        if hasattr(record, "request_id"):
            log_obj["request_id"] = record.request_id
        if hasattr(record, "method"):
            log_obj["method"] = record.method
        if hasattr(record, "path"):
            log_obj["path"] = record.path
        if hasattr(record, "status_code"):
            log_obj["status_code"] = record.status_code
        if hasattr(record, "duration_ms"):
            log_obj["duration_ms"] = record.duration_ms
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_obj)


def setup_logging(level: str = "INFO"):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = [handler]
    
    # Reduce noise from libraries
    logging.getLogger("uvicorn.access").handlers = [handler]
    logging.getLogger("uvicorn.error").handlers = [handler]
    logging.getLogger("motor").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        import time
        import uuid
        
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        
        # Add request_id to request state for access in endpoints
        request.state.request_id = request_id
        
        logger = logging.getLogger("request")
        logger.info(
            "Request started",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
            }
        )
        
        try:
            response = await call_next(request)
            duration_ms = round((time.time() - start_time) * 1000, 2)
            
            logger.info(
                "Request completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                }
            )
            
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as e:
            duration_ms = round((time.time() - start_time) * 1000, 2)
            logger.error(
                "Request failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                },
                exc_info=True
            )
            raise