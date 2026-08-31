from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from meridian.api.routes.health import router as health_router
from meridian.settings import get_settings


def create_app() -> FastAPI:
    """Build the API application from validated runtime settings."""

    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Read-only decision support for the synthetic Meridian capstone dataset. "
            "Phase 0 exposes health checks only."
        ),
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    application.include_router(health_router, prefix="/api")
    return application


app = create_app()
