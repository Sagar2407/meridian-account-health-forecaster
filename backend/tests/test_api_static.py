"""Serving the browser bundle from the API (plan section 24.2).

The production image puts the compiled frontend inside the container and serves
both from one process. Three things have to hold, and each has a way of being
quietly wrong:

* A client-side route like `/review` must return the shell, not a 404. The
  browser asks the *server* for that path on a hard refresh.
* A request under `/api` that matched nothing must still be a JSON 404. The
  catch-all claims every path, so without an explicit check a mistyped endpoint
  would hand a `fetch` an HTML page to parse.
* `../` must not escape the bundle.

The whole mount is conditional, so a development container with no bundle is
also tested: it must keep answering the API and must not invent a shell.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meridian.api.main import create_app
from meridian.settings import Settings, get_settings


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    """Return a directory shaped like a Vite build."""

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>shell</title>", encoding="utf-8")
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return tmp_path


def _client(static_directory: str) -> TestClient:
    """Return a client whose app serves from `static_directory`.

    The settings are passed to `create_app` rather than overridden afterwards:
    whether a bundle is mounted is decided while the app is being built, so a
    `dependency_overrides` entry installed later arrives too late to matter.
    """

    settings = Settings(_env_file=None, static_directory=static_directory)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


@pytest.fixture(autouse=True)
def _restore_settings_cache() -> Iterator[None]:
    """Keep one test's settings from leaking into the next."""

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestWithABundle:
    def test_the_root_serves_the_shell(self, bundle: Path) -> None:
        """The landing page is the compiled application, not an API response."""

        response = _client(str(bundle)).get("/")

        assert response.status_code == 200
        assert "shell" in response.text

    def test_a_client_side_route_serves_the_shell(self, bundle: Path) -> None:
        """A hard refresh on /review asks the server for a file that does not exist."""

        for path in ("/review", "/evaluation", "/accounts/ACC-1042", "/runs/RUN-1"):
            response = _client(str(bundle)).get(path)
            assert response.status_code == 200, path
            assert "shell" in response.text, path

    def test_a_built_asset_is_served_as_itself(self, bundle: Path) -> None:
        """Handing the shell back for a script tag would break the page silently."""

        response = _client(str(bundle)).get("/assets/index-abc123.js")

        assert response.status_code == 200
        assert "console.log" in response.text

    def test_a_root_level_file_is_served_as_itself(self, bundle: Path) -> None:
        """Not everything lives under /assets: the favicon sits at the root."""

        response = _client(str(bundle)).get("/favicon.svg")

        assert response.status_code == 200
        assert "svg" in response.text

    def test_the_api_still_answers(self, bundle: Path) -> None:
        """The catch-all claims every path; it must not shadow the API."""

        response = _client(str(bundle)).get("/api/health")

        assert response.status_code == 200
        assert response.json()["service"] == "meridian-api"

    def test_an_unknown_api_path_is_a_json_404_not_the_shell(self, bundle: Path) -> None:
        """A `fetch` handed an HTML page fails to parse and reports nothing useful."""

        response = _client(str(bundle)).get("/api/nope")

        assert response.status_code == 404
        assert "shell" not in response.text
        # Section 19.3's shape, not FastAPI's `{"detail": ...}`.
        assert response.json()["code"] == "ACCOUNT_NOT_FOUND"
        assert "no such endpoint" in response.json()["message"]

    def test_traversal_out_of_the_bundle_is_refused(self, bundle: Path, tmp_path: Path) -> None:
        """A path that escapes the bundle gets the shell, never the file."""

        secret = tmp_path.parent / "secret.txt"
        secret.write_text("do not serve me", encoding="utf-8")

        response = _client(str(bundle)).get("/../secret.txt")

        assert "do not serve me" not in response.text


class TestWithoutABundle:
    def test_the_api_works_with_no_frontend_built(self) -> None:
        """The development container has no bundle and must still serve the API."""

        response = _client("").get("/api/health")

        assert response.status_code == 200

    def test_no_shell_is_invented(self) -> None:
        """Answering `/` with something would hide a broken deployment."""

        response = _client("").get("/")

        assert response.status_code == 404

    def test_a_configured_but_missing_directory_is_treated_as_absent(self, tmp_path: Path) -> None:
        """A path with no index.html is a misconfiguration, not a bundle."""

        response = _client(str(tmp_path / "does-not-exist")).get("/api/health")

        assert response.status_code == 200
