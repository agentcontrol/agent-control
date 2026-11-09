"""Exercise the real HTTPcore pool rather than a pool-bypassing mock transport."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from agent_control_evaluator_galileo.luna.pool_diagnostics import (
    begin_pool_diagnostics,
    diagnostic_outcome,
)


@asynccontextmanager
async def gated_server():
    gate = asyncio.Event()
    received = asyncio.Event()
    connections = []
    tasks = set()

    async def handle(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        connections.append(writer)
        try:
            while True:
                await reader.readuntil(b"\r\n\r\n")
                received.set()
                await gate.wait()
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            tasks.discard(task)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}", gate, received, connections
    finally:
        gate.set()
        server.close()
        await server.wait_closed()
        for writer in connections:
            writer.close()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_pool_contention_is_measured_and_connection_reused(monkeypatch):
    # Given a real pool with one connection occupied by an unfinished response.
    monkeypatch.setenv("GALILEO_LUNA_HTTP_DIAGNOSTICS", "true")
    async with gated_server() as (url, gate, received, connections):
        async with httpx.AsyncClient(limits=httpx.Limits(max_connections=1)) as client:
            first = asyncio.create_task(client.get(url))
            await asyncio.wait_for(received.wait(), 2)
            request = client.build_request("GET", url)
            timing = begin_pool_diagnostics(request.extensions)
            assert timing is not None
            second = asyncio.create_task(client.send(request))
            # When another request queues and is assigned the released connection.
            await asyncio.sleep(0.03)
            assert not second.done()
            gate.set()
            assert (await first).status_code == 200
            assert (await second).status_code == 200
            assert (await client.get(url)).status_code == 200
            # Then only real connection assignment wait appears in pool_queue.
            queues = [(end - start) / 1e9 for stage, start, end in timing.intervals
                      if stage == "luna_pool_queue"]
            assert len(queues) == 1 and queues[0] >= 0.02
            assert {stage for stage, _, _ in timing.intervals} >= {
                "luna_before_pool", "luna_pool_queue", "luna_pool_resume"
            }
            assert len(connections) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_and_cancellation_keep_pool_usable(monkeypatch, cancel):
    # Given a waiting request with no available connection.
    monkeypatch.setenv("GALILEO_LUNA_HTTP_DIAGNOSTICS", "1")
    async with gated_server() as (url, gate, received, connections):
        async with httpx.AsyncClient(limits=httpx.Limits(max_connections=1)) as client:
            first = asyncio.create_task(client.get(url))
            await asyncio.wait_for(received.wait(), 2)
            request = client.build_request("GET", url, timeout=httpx.Timeout(2, pool=0.03))
            timing = begin_pool_diagnostics(request.extensions)
            second = asyncio.create_task(client.send(request))
            # When the existing timeout or cancellation path ends the request.
            if cancel:
                await asyncio.sleep(0.01)
                second.cancel()
            error_type = asyncio.CancelledError if cancel else httpx.PoolTimeout
            with pytest.raises(error_type) as error:
                await second
            assert timing is not None
            timing.finish(diagnostic_outcome(error.value))
            # Then it is removed from the pool and subsequent traffic still succeeds.
            assert any(stage == "luna_pool_queue" for stage, _, _ in timing.intervals)
            assert diagnostic_outcome(error.value) == ("cancelled" if cancel else "error")
            gate.set()
            await first
            assert (await client.get(url)).status_code == 200
            assert len(connections) == 1


def test_disabled_diagnostics_do_not_tag_requests(monkeypatch):
    # Given the normal disabled configuration, request extensions remain untouched.
    monkeypatch.delenv("GALILEO_LUNA_HTTP_DIAGNOSTICS", raising=False)
    extensions = {}
    assert begin_pool_diagnostics(extensions) is None
    assert extensions == {}
