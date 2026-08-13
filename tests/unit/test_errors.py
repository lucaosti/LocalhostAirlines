"""Verifies every error path serializes to application/problem+json with the
status mapping from docs/api.md §4 — without touching a database.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from apps.api.errors import NotFoundProblem, register_error_handlers


def build_test_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    class Body(BaseModel):
        name: str

    @app.get("/boom/not-found")
    async def not_found() -> None:
        raise NotFoundProblem("no such itinerary", instance_id="itin_123")

    @app.get("/boom/unhandled")
    async def unhandled() -> None:
        raise RuntimeError("something broke")

    @app.post("/echo")
    async def echo(body: Body) -> dict:
        return {"name": body.name}

    return app


client = TestClient(build_test_app(), raise_server_exceptions=False)


def test_app_problem_serializes_as_problem_json() -> None:
    response = client.get("/boom/not-found")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["type"] == "https://localhostairlines.local/problems/not-found"
    assert body["title"] == "Resource not found"
    assert body["detail"] == "no such itinerary"
    assert body["instance_id"] == "itin_123"
    assert body["instance"] == "/boom/not-found"


def test_validation_error_maps_to_422_problem_json() -> None:
    response = client.post("/echo", json={"wrong_field": 1})
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["status"] == 422
    assert "errors" in body


def test_route_not_found_maps_to_404_problem_json() -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


def test_unhandled_exception_maps_to_500_without_leaking_internals() -> None:
    response = client.get("/boom/unhandled")
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert "something broke" not in response.text
    assert body["title"] == "Internal error"
