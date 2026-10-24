"""Wake immediately on the existing owner-scoped queue completion event."""
import asyncio
import time
from fastapi import HTTPException
from .latency import record_latency


async def wait_for_job(queue, snapshot, owner, request, timeout, message):
    if snapshot['status'] not in ('queued', 'processing'):
        return snapshot
    started = time.monotonic()
    waiter = asyncio.create_task(queue.wait(snapshot['job_id'], owner))
    try:
        while True:
            if await request.is_disconnected():
                raise asyncio.CancelledError()
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise HTTPException(504, message)
            done, _ = await asyncio.wait({waiter}, timeout=min(.2, remaining))
            if done:
                result = await waiter
                if result is None:
                    raise HTTPException(503, 'The AI job is no longer available. Please try again.')
                return result
    finally:
        if not waiter.done():
            waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        record_latency('queue_completion', wait_seconds=time.monotonic()-started)
