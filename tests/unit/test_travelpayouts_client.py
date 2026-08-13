"""Travelpayouts adapter — contract tests against recorded/synthesized response
shapes (spec §21). Never touches the network: httpx.MockTransport stands in
for the real API so this suite never depends on it (CLAUDE.md §6)."""

import httpx
import pytest

from providers.errors import SourceError, SourceErrorKind
from providers.travelpayouts.client import PriceCalendarRequest, fetch_price_calendar

# Shape confirmed against the vendor's own published API reference
# (https://travelpayouts.github.io/slate/) before writing the adapter.
SUCCESS_BODY = {
    "success": True,
    "data": {
        "2026-10-01": {
            "origin": "MXP",
            "destination": "NRT",
            "price": 612,
            "transfers": 1,
            "airline": "LH",
            "flight_number": 510,
            "departure_at": "2026-10-01T09:15:00Z",
            "return_at": None,
            "expires_at": "2026-08-20T00:00:00Z",
        }
    },
}


async def _run(handler, request=None) -> dict:
    req = request or PriceCalendarRequest(origin="MXP", destination="NRT", depart_date="2026-10")
    return await fetch_price_calendar(
        req, token="test-token", _transport=httpx.MockTransport(handler)
    )


async def test_successful_response_returns_body_unchanged() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-access-token"] == "test-token"
        assert request.url.params["origin"] == "MXP"
        assert request.url.params["calendar_type"] == "departure_date"
        return httpx.Response(200, json=SUCCESS_BODY)

    body = await _run(handler)
    assert body == SUCCESS_BODY


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_failure_classified(status) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "invalid token"})

    with pytest.raises(SourceError) as exc_info:
        await _run(handler)
    assert exc_info.value.kind == SourceErrorKind.AUTHENTICATION


async def test_rate_limit_classified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "too many requests"})

    with pytest.raises(SourceError) as exc_info:
        await _run(handler)
    assert exc_info.value.kind == SourceErrorKind.RATE_LIMIT


async def test_server_error_classified_as_upstream() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    with pytest.raises(SourceError) as exc_info:
        await _run(handler)
    assert exc_info.value.kind == SourceErrorKind.UPSTREAM_ERROR


async def test_success_false_is_not_available_not_an_error_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "data": []})

    with pytest.raises(SourceError) as exc_info:
        await _run(handler)
    # NOT_AVAILABLE, never SCHEMA_CHANGE: the API answered in its documented
    # shape, it just has nothing for this query (spec §45).
    assert exc_info.value.kind == SourceErrorKind.NOT_AVAILABLE


async def test_malformed_json_is_schema_change() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json at all")

    with pytest.raises(SourceError) as exc_info:
        await _run(handler)
    assert exc_info.value.kind == SourceErrorKind.SCHEMA_CHANGE


async def test_unrecognised_json_shape_is_schema_change() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Valid JSON, but not this endpoint's documented envelope — the
        # kind of drift a real vendor change could plausibly introduce.
        return httpx.Response(200, json={"results": []})

    with pytest.raises(SourceError) as exc_info:
        await _run(handler)
    assert exc_info.value.kind == SourceErrorKind.SCHEMA_CHANGE


async def test_unexpected_4xx_is_schema_change() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    with pytest.raises(SourceError) as exc_info:
        await _run(handler)
    assert exc_info.value.kind == SourceErrorKind.SCHEMA_CHANGE


async def test_bad_request_classified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid origin"})

    with pytest.raises(SourceError) as exc_info:
        await _run(handler)
    assert exc_info.value.kind == SourceErrorKind.BAD_REQUEST
