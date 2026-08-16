"""Regression tests for the SPA catch-all route.

Bug: when frontend/build/index.html existed, ANY unmatched path — including
/api/* — was answered with HTTP 200 + the HTML shell. In the browser,
`res.json()` on that response failed with:

    Unexpected token '<', "<!doctype "... is not valid JSON

Unknown API paths must return a JSON 404 instead, so the client sees a real
error status and a parseable body.
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import pytest  # noqa: E402

import server  # noqa: E402


@pytest.fixture()
def built_frontend(tmp_path, monkeypatch):
    """Simulate a deployment where the React build exists."""
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    (build_dir / "index.html").write_text(
        '<!doctype html><html><body><div id="root"></div></body></html>'
    )
    (build_dir / "asset.js").write_text("console.log('hi');")
    monkeypatch.setattr(server, "FRONTEND_BUILD_DIR", build_dir)
    return build_dir


@pytest.mark.parametrize(
    "path",
    [
        "/api/nope",
        "/api/content/queue/",  # trailing slash — not a registered route
        "/api/content/does-not-exist",
        "/api/analytics/overviewX",
    ],
)
def test_unknown_api_paths_return_json_404(client, built_frontend, path):
    res = client.get(path)

    assert res.status_code == 404, f"{path} should 404, got {res.status_code}"
    assert "json" in res.headers["content-type"]
    assert not res.text.lstrip().lower().startswith("<!doctype")
    res.json()  # must be parseable — this is what the browser client does


def test_real_api_routes_still_serve_json(client, mentor_headers, built_frontend):
    res = client.get("/api/content/stats", headers=mentor_headers)

    assert res.status_code == 200
    assert "json" in res.headers["content-type"]
    assert "total" in res.json()


def test_docs_and_openapi_are_not_shadowed_by_spa(client, built_frontend):
    assert client.get("/openapi.json").status_code == 200
    assert "json" in client.get("/openapi.json").headers["content-type"]
    assert client.get("/docs").status_code == 200


def test_spa_routes_still_serve_index_html(client, built_frontend):
    for path in ["/", "/ai-content/queue", "/dashboard"]:
        res = client.get(path)
        assert res.status_code == 200, path
        assert "text/html" in res.headers["content-type"], path
        assert "<div id=\"root\">" in res.text


def test_static_assets_still_served(client, built_frontend):
    res = client.get("/asset.js")
    assert res.status_code == 200
    assert "console.log" in res.text


def test_unknown_api_path_404s_without_a_build_dir(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "FRONTEND_BUILD_DIR", tmp_path / "missing")
    res = client.get("/api/nope")
    assert res.status_code == 404
    assert "json" in res.headers["content-type"]
