from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from meridian.api.routes.health import router as health_router
from meridian.api.routes.review import router as review_router
from meridian.settings import get_settings


def create_app() -> FastAPI:
    """Build the API application from validated runtime settings."""

    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Read-only decision support for the synthetic Meridian capstone dataset. "
            "Phase 7 exposes health checks and the human-review queue; the assessment "
            "routes arrive in Phase 8."
        ),
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        # The review queue accepts a reviewer's decision, which is the one
        # write this API has. Everything else stays read-only.
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    application.include_router(health_router, prefix="/api")
    application.include_router(review_router, prefix="/api")
    return application


app = create_app()
