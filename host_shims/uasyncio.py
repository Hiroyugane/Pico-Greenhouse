"""Host-compatible shim for MicroPython uasyncio.

Maps uasyncio APIs to CPython asyncio so the code can run on Windows.
"""

import asyncio as _asyncio

CancelledError = _asyncio.CancelledError
Event = _asyncio.Event


def run(coro):
    return _asyncio.run(coro)


def create_task(coro):
    return _asyncio.create_task(coro)


async def sleep(delay):
    return await _asyncio.sleep(delay)


def get_event_loop():
    return _asyncio.get_event_loop()
