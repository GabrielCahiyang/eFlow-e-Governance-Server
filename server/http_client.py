"""Reusable outbound connections, scoped to each service's event loop."""
import aiohttp

_session = None


async def get_session():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30, connect=10),
                                         connector=aiohttp.TCPConnector(limit=32, limit_per_host=16))
    return _session


async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()
    _session = None
