from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.catalog import router as catalog_router
from app.api.errors import AppError, error_body
from app.api.jobs import router as jobs_router
from app.api.projects import router as projects_router
from app.config import get_settings
from app.db.session import create_engine, session_factory
from app.services.prompts import sync_prompts
from app.services.providers_seed import seed_providers


@asynccontextmanager
async def _lifespan(app: FastAPI):
    factory = getattr(app.state, "session_factory", None)
    if factory is not None:
        async with factory() as session:
            await sync_prompts(session)
            await seed_providers(session, get_settings())
            await session.commit()
    yield


def create_app(session_factory: async_sessionmaker | None = None) -> FastAPI:
    app = FastAPI(title="Stickman Content Factory", lifespan=_lifespan)
    if session_factory is not None:
        app.state.session_factory = session_factory

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.kind, exc.message, exc.detail),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, _exc: Exception):
        return JSONResponse(
            status_code=500,
            content=error_body(
                "InternalError", "Terjadi kesalahan tak terduga di server.", None
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=error_body(
                "ValidationError", "Input tidak valid.", jsonable_encoder(exc.errors())
            ),
        )

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    app.include_router(jobs_router)
    app.include_router(projects_router)
    app.include_router(catalog_router)
    return app


def serve() -> FastAPI:
    settings = get_settings()
    engine = create_engine(settings)
    return create_app(session_factory=session_factory(engine))
