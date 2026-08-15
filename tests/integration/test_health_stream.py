"""Regression test for the SSE probe.

Verified manually first against the real stack through Caddy — curl
--no-buffer showed heartbeat events arriving one per second rather than all
at once when the connection closed, which is what proves nothing upstream of
this test (ASGI server, StreamingResponse) buffers the stream either.

This automates that same check, but deliberately over a real TCP socket via
a real uvicorn server rather than httpx's ASGITransport. ASGITransport runs
the app in-process without simulating a genuine client disconnect: Starlette's
StreamingResponse waits on a disconnect event that never arrives, and an
early client-side break deadlocks instead of cancelling — discovered when an
ASGITransport-based version of this test hung instead of finishing in ~3s. A
real socket has real disconnect semantics, matching what was already
verified by hand.
"""

import asyncio
import time

import httpx
import pytest
import uvicorn

from apps.api.main import app


@pytest.mark.integration
async def test_health_stream_delivers_events_incrementally() -> None:
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.05)
        port = server.servers[0].sockets[0].getsockname()[1]

        arrival_times: list[float] = []
        async with (
            httpx.AsyncClient() as client,
            client.stream("GET", f"http://127.0.0.1:{port}/health/stream") as response,
        ):
            assert response.headers["content-type"].startswith("text/event-stream")
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    arrival_times.append(time.monotonic())
                if len(arrival_times) >= 3:
                    break
    finally:
        server.should_exit = True
        await asyncio.wait_for(server_task, timeout=5)

    # The handler sleeps 1s between events. If something buffered the
    # response, all three would arrive together in well under 1s total.
    assert arrival_times[-1] - arrival_times[0] >= 1.5
