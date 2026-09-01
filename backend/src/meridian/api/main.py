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
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from meridian.api.errors import (
    ApiError,
    api_error_handler,
    http_error_handler,
    unhandled_error_handler,
)
from meridian.api.routes.accounts import router as accounts_router
from meridian.api.routes.assessments import router as assessments_router
from meridian.api.routes.demo import router as demo_router
from meridian.api.routes.evaluations import router as evaluations_router
from meridian.api.routes.health import router as health_router
from meridian.api.routes.review import router as review_router
from meridian.api.routes.scans import router as scans_router
from meridian.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API application from validated runtime settings.

    Args:
        settings: Overrides the process settings. Construction-time
            configuration -- the CORS allowlist and whether a browser bundle is
            mounted -- is read here and cannot be changed afterwards by a
            dependency override, so a test that needs different values has to
            supply them before the app is built.
    """

    settings = settings or get_settings()
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
    # FastAPI's own 404s and 405s otherwise come back as `{"detail": ...}`,
    # which is not the shape section 19.3 documents.
    application.add_exception_handler(StarletteHTTPException, http_error_handler)
    application.add_exception_handler(Exception, unhandled_error_handler)

    for router in (
        health_router,
        accounts_router,
        assessments_router,
        scans_router,
        review_router,
        evaluations_router,
        demo_router,
    ):
        application.include_router(router, prefix="/api")

    _mount_frontend(application, settings.static_root)
    return application


def _mount_frontend(application: FastAPI, root: Path | None) -> None:
    """Serve the compiled browser bundle, with an SPA fallback (section 24.2).

    Mounted last and only when a bundle exists. Last, because the mount claims
    every path and would otherwise shadow `/api`; only when it exists, because
    a development container has no bundle and must not answer `/` with a 404
    that reads like a broken deployment.

    The fallback is what makes client-side routing work: a browser asked to
    open `/review` directly requests that path from the server, which has no
    such file. It gets `index.html` and the router takes over. A request under
    `/api` that reached here is a genuine 404 and is answered as one, rather
    than being handed an HTML page that a fetch would fail to parse.
    """

    if root is None:
        return

    # Order matters. Starlette matches in registration order, so the hashed
    # asset mount has to be registered before the catch-all; after it, the
    # catch-all would claim every asset path and the mount would never run.
    assets = root / "assets"
    if assets.is_dir():
        application.mount("/assets", StaticFiles(directory=assets), name="assets")

    @application.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        """Return a built asset, or the shell for a client-side route."""

        if path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no such endpoint: /{path}")
        candidate = (root / path).resolve()
        # `resolve` plus this check refuses `../` traversal out of the bundle.
        if root.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(root / "index.html")


app = create_app()
