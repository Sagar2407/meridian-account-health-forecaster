"""The FastAPI application (plan section 19).

Routers are assembled here and nowhere else, so the served surface can be read
off one file and checked against section 19.1's table. Two things are deliberate:

* **Methods are enumerated, not opened.** CORS allows `GET` and `POST` because
  those are the two the contract uses; a wildcard would quietly admit `DELETE`
  the day someone adds one.
* **Errors have one shape.** `meridian.api.errors` renders every failure as a
  stable code and a plain message, and the unhandled-error handler logs the
  traceback rather than returning it (sections 19.3 and 24.3).
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from meridian.api.errors import ApiError, api_error_handler, unhandled_error_handler
from meridian.api.routes.accounts import router as accounts_router
from meridian.api.routes.assessments import router as assessments_router
from meridian.api.routes.evaluations import router as evaluations_router
from meridian.api.routes.health import router as health_router
from meridian.api.routes.review import router as review_router
from meridian.api.routes.scans import router as scans_router
from meridian.settings import get_settings


def create_app() -> FastAPI:
    """Build the API application from validated runtime settings."""

    settings = get_settings()
    logging.getLogger("meridian").setLevel(settings.log_level)
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Read-only decision support for the synthetic Meridian capstone dataset. "
            "Every result is advisory: the service assesses accounts and routes what it "
            "is unsure of to a person, and it takes no action on any customer."
        ),
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        # GET reads; POST starts a run, a scan, an evaluation, or records a
        # reviewer's decision. Nothing here deletes or replaces a resource.
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    application.add_exception_handler(ApiError, api_error_handler)
    application.add_exception_handler(Exception, unhandled_error_handler)

    for router in (
        health_router,
        accounts_router,
        assessments_router,
        scans_router,
        review_router,
        evaluations_router,
    ):
        application.include_router(router, prefix="/api")
    return application


app = create_app()
