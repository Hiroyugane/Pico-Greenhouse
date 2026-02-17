"""Host-compatible shim for MicroPython uasyncio.

Maps uasyncio APIs to CPython asyncio so the code can run on Windows.

Additions over the original shim:
- ``sleep_ms(ms)`` — MicroPython-specific millisecond sleep.
- ``wait_for_ms(coro, timeout_ms)`` — MicroPython-specific timed wait.
- ``Lock`` — re-export of ``asyncio.Lock``.
"""

import asyncio as _asyncio

CancelledError = _asyncio.CancelledError
Event = _asyncio.Event
Lock = _asyncio.Lock


def run(coro):
    return _asyncio.run(coro)


def create_task(coro):
    return _asyncio.create_task(coro)


async def sleep(delay):
    return await _asyncio.sleep(delay)


async def sleep_ms(ms):
    """Sleep for *ms* milliseconds (MicroPython-specific)."""
    return await _asyncio.sleep(ms / 1000)


async def wait_for_ms(coro, timeout_ms):
    """Wait for *coro* with a timeout in milliseconds."""
    return await _asyncio.wait_for(coro, timeout=timeout_ms / 1000)


def get_event_loop():
    return _asyncio.get_event_loop()
