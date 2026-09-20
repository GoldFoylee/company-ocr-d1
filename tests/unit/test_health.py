from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    """This is the pattern every future endpoint test follows: spin up the
    app in-memory (no real server, no network), hit a route, assert on the
    response. Fast enough to run hundreds of these in CI in seconds."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
