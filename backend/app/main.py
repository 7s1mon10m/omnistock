"""FastAPI application factory for OmniStock."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import setup_logging
from app.middlewares import RequestContextMiddleware

logger = logging.getLogger("app.startup")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """Seed roles and the bootstrap administrator on first start."""
    setup_logging()
    logger.info("OmniStock 启动 env=%s version=%s", settings.APP_ENV, settings.APP_VERSION)

    if settings.APP_ENV not in ("test", "testing"):
        from app.db import SessionLocal
        from app.services import auth_service, permission_service

        session = SessionLocal()
        try:
            permission_service.ensure_default_roles(session)
            auth_service.bootstrap_admin(session)
        except Exception as exc:  # pragma: no cover - schema may not exist yet
            session.rollback()
            logger.warning("初始化数据失败（可能尚未执行迁移）：%s", exc)
        finally:
            session.close()
    yield
    logger.info("OmniStock 停止")


def create_app() -> FastAPI:
    setup_logging()

    docs_enabled = settings.EXPOSE_DOCS and settings.APP_ENV != "production"
    app = FastAPI(
        title=settings.APP_NAME,
        description="多渠道电商库存与采购协同平台",
        version=settings.APP_VERSION,
        debug=settings.DEBUG,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )

    # Starlette inserts each new middleware at the front, so the middleware
    # added last ends up outermost. Desired order, outermost first:
    #   RequestContext -> CORS -> routes
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Content-Disposition"],
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/healthz", summary="存活探针", tags=["meta"])
    def healthz() -> dict:
        return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}

    @app.get("/", summary="服务信息", tags=["meta"])
    def root() -> dict:
        return {
            "name": settings.APP_NAME,
            "env": settings.APP_ENV,
            "version": settings.APP_VERSION,
            "api_prefix": settings.API_V1_PREFIX,
            "docs": "/docs" if docs_enabled else None,
            "health": "/healthz",
        }

    return app


app = create_app()
