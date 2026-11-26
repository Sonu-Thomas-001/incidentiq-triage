import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError

from app.api.v1 import auth, incidents, servicenow, workflow
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, request_id_var

logger = logging.getLogger("app")


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id_var.get(),
        }
    }
    return JSONResponse(status_code=status, content=body)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.resolved_secret_key()  # fail fast outside development

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        logger.info("starting %s env=%s", settings.app_name, settings.app_env)
        task = None
        if settings.autopilot_enabled and settings.servicenow_enabled:
            from app.services import autopilot

            logger.info(
                "autopilot on: every %ss, auto_assign=%s",
                settings.autopilot_interval_seconds,
                settings.autopilot_auto_assign,
            )
            task = asyncio.create_task(autopilot.poll_forever(settings.autopilot_interval_seconds))
        yield
        if task is not None:
            task.cancel()

    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        description=(
            "Phase 1 backend. Triage returns NOT_READY until a trained model exists. "
            "Seed data is synthetic. Canonical paths: /api/v1/...; /api/... is an alias."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            elapsed = (time.perf_counter() - start) * 1000
            logger.info("%s %s %.1fms", request.method, request.url.path, elapsed)
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        resp = _error(exc.status_code, exc.code, exc.message, exc.details)
        retry_after = getattr(exc, "retry_after", None)
        if retry_after is not None:
            resp.headers["Retry-After"] = str(int(retry_after))
        if headers:
            resp.headers.update(headers)
        return resp

    @app.exception_handler(HTTPException)
    async def http_error_handler(_: Request, exc: HTTPException):
        return _error(exc.status_code, f"HTTP_{exc.status_code}", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        return _error(422, "VALIDATION_ERROR", "Request validation failed", details)

    @app.exception_handler(StaleDataError)
    async def stale_handler(_: Request, exc: StaleDataError):
        return _error(409, "STALE_VERSION", "Incident was modified concurrently; reload and retry")

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception):
        logger.exception("unhandled error")
        return _error(500, "INTERNAL_ERROR", "Internal server error")

    @app.get("/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok", "service": settings.app_name, "version": app.version}

    api = APIRouter()
    api.include_router(auth.router)
    api.include_router(incidents.router)
    api.include_router(workflow.router)
    api.include_router(servicenow.router)
    app.include_router(api, prefix="/api/v1")
    app.include_router(api, prefix="/api", include_in_schema=False)
    return app


app = create_app()
