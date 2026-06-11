"""P1-A skeleton constraint: FastAPI present, health endpoint only
(spec v0.3 §12 constraints)."""

from fastapi.testclient import TestClient

from hearth import __version__
from hearth.api.app import app


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "hearth",
        "version": __version__,
        "phase": "P1",
    }


def test_no_other_routes_in_phase_1():
    # §12: "FastAPI present but only health endpoint in P1". Catch scope creep.
    # Only count user-defined endpoints; FastAPI's own docs/openapi routes
    # are framework furniture, not product surface.
    from fastapi.routing import APIRoute

    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert paths == {"/health"}
