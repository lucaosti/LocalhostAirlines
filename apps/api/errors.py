"""RFC 9457 problem-details error model.

Every error response — ours or FastAPI's own validation and routing errors —
serializes to the same `application/problem+json` shape (docs/api.md §4). A client
never has to special-case which layer produced the failure.
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_BASE = "https://localhostairlines.local/problems"


class AppProblem(Exception):
    """Base for every domain error the application raises deliberately.

    `status` follows the mapping in docs/api.md §4. A failing external source is
    never represented as an AppProblem with a 5xx status (spec §82): source
    failure is a domain outcome carried inside a 200 response body as an
    UNKNOWN-state field, not an API error.
    """

    status: int = status.HTTP_400_BAD_REQUEST
    slug: str = "bad-request"
    title: str = "Bad request"

    def __init__(self, detail: str | None = None, **extra: Any) -> None:
        self.detail = detail
        self.extra = extra
        super().__init__(detail or self.title)

    def to_problem(self, instance: str) -> dict[str, Any]:
        problem = {
            "type": f"{PROBLEM_BASE}/{self.slug}",
            "title": self.title,
            "status": self.status,
            "instance": instance,
        }
        if self.detail:
            problem["detail"] = self.detail
        problem.update(self.extra)
        return problem


class BadRequestProblem(AppProblem):
    status = status.HTTP_400_BAD_REQUEST
    slug = "bad-request"
    title = "Bad request"


class UnauthorizedProblem(AppProblem):
    status = status.HTTP_401_UNAUTHORIZED
    slug = "unauthorized"
    title = "Authentication required"


class ForbiddenProblem(AppProblem):
    status = status.HTTP_403_FORBIDDEN
    slug = "forbidden"
    title = "Not permitted"


class NotFoundProblem(AppProblem):
    status = status.HTTP_404_NOT_FOUND
    slug = "not-found"
    title = "Resource not found"


class ConflictProblem(AppProblem):
    status = status.HTTP_409_CONFLICT
    slug = "conflict"
    title = "Conflicting state"


class UnprocessableProblem(AppProblem):
    status = status.HTTP_422_UNPROCESSABLE_CONTENT
    slug = "unprocessable"
    title = "Semantically invalid request"


class RateLimitProblem(AppProblem):
    status = status.HTTP_429_TOO_MANY_REQUESTS
    slug = "rate-limited"
    title = "Too many requests"


class ServiceUnavailableProblem(AppProblem):
    """Reserved for a hard dependency being unreachable (spec §82) — PostgreSQL
    only. Never used for a failing external source; that is a domain outcome,
    not an API error (docs/api.md §4).
    """

    status = status.HTTP_503_SERVICE_UNAVAILABLE
    slug = "service-unavailable"
    title = "A required dependency is unavailable"


def _json_problem(status_code: int, content: dict[str, Any]) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content=content, media_type="application/problem+json"
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppProblem)
    async def handle_app_problem(request: Request, exc: AppProblem) -> JSONResponse:
        return _json_problem(exc.status, exc.to_problem(str(request.url.path)))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # FastAPI's own body/query parsing failures are semantically invalid
        # requests (spec 422), not malformed ones (400) — the request was
        # well-formed JSON that failed our schema.
        problem = {
            "type": f"{PROBLEM_BASE}/unprocessable",
            "title": "Semantically invalid request",
            "status": status.HTTP_422_UNPROCESSABLE_CONTENT,
            "instance": str(request.url.path),
            "errors": exc.errors(),
        }
        return _json_problem(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Routing-level failures (404 on an unknown path, 405 on a wrong method)
        # that never reach our own handlers still come out as problem+json.
        problem = {
            "type": f"{PROBLEM_BASE}/http-{exc.status_code}",
            "title": exc.detail or "Request error",
            "status": exc.status_code,
            "instance": str(request.url.path),
        }
        return _json_problem(exc.status_code, problem)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # The client never sees exception internals — only that something broke.
        # The caller's own logging middleware is responsible for recording the
        # real detail server-side.
        problem = {
            "type": f"{PROBLEM_BASE}/internal-error",
            "title": "Internal error",
            "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "instance": str(request.url.path),
        }
        return _json_problem(status.HTTP_500_INTERNAL_SERVER_ERROR, problem)
