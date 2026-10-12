"""Cached service configuration and background read-only RPC connectivity probes."""
import asyncio
from copy import deepcopy
import os
import time
from urllib.parse import urlsplit

import aiohttp
from http_client import get_session
from service_monitor import monitor, package_available


class ServiceStatus:
    def __init__(self):
        self.config = None
        self.rpc = {"state": "not_checked", "checked_at": None, "chain_id": None, "block_number": None, "message": "RPC has not been checked."}
        self._task = None
        self._rpc_url = None

    def configure(self):
        import polygon_service as polygon
        mode = "unavailable"
        problem = None
        try:
            mode = "simulation" if polygon._resolve_simulation_mode() else "live"
        except ValueError:
            problem = "Invalid POLYGON_MODE configuration."
        key_present = bool(polygon.POLYGON_PRIVATE_KEY.strip())
        web3_available = package_available("web3")
        if mode == "live" and not key_present:
            problem = "Live mode requires a configured wallet key."
        elif mode == "live" and not web3_available:
            problem = "The Web3 dependency is unavailable."
        self._rpc_url = polygon.POLYGON_RPC_URL
        try:
            rpc_host = urlsplit(self._rpc_url).hostname
        except ValueError:
            rpc_host = None
        self.config = {
            "pygad": {"available": package_available("pygad"), "default_profile": os.getenv("PYGAD_DECOMPOSITION_PROFILE", "balanced"),
                      "execution": "One standalone CPU worker; decomposition runs inside the inference worker."},
            "laya": {"mode": os.getenv("LAYA_MODE", "model"), "device": os.getenv("LAYA_DEVICE", "cpu"),
                     "execution": "Starts on demand inside the inference worker."},
            "blockchain": {"mode": mode, "configured_mode": polygon.POLYGON_MODE or "auto", "available": problem is None,
                           "chain_id": polygon.POLYGON_CHAIN_ID, "network": "Polygon Amoy" if polygon.POLYGON_CHAIN_ID == 80002 else f"Chain {polygon.POLYGON_CHAIN_ID}",
                           "rpc_host": rpc_host, "wallet_configured": key_present, "problem": problem,
                           "execution": "One wallet worker; blockchain calls do not use the GPU."},
        }
        if mode == "simulation":
            self.rpc.update(state="not_required", message="Simulation mode does not contact the chain.")
        elif problem:
            self.rpc.update(state="unavailable", message=problem)

    async def probe_rpc(self):
        chain = self.config["blockchain"]
        if chain["mode"] != "live" or not chain["available"]:
            return
        snapshot = {"state": "unreachable", "checked_at": time.time(), "chain_id": None,
                    "block_number": None, "message": "RPC connectivity check failed."}
        try:
            session = await get_session()
            async def read(method):
                async with session.post(self._rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": []},
                                        timeout=aiohttp.ClientTimeout(total=5)) as response:
                    response.raise_for_status()
                    data = await response.json()
                    return int(data["result"], 16)
            # Probe only public network data; never submit/sign transactions.
            actual_chain, block = await asyncio.gather(read("eth_chainId"), read("eth_blockNumber"))
            matches = actual_chain == chain["chain_id"]
            snapshot.update(state="connected" if matches else "wrong_network", chain_id=actual_chain, block_number=block,
                            message="RPC reachable; network matches configuration." if matches else "RPC network does not match the configured chain.")
        except asyncio.CancelledError:
            raise
        except Exception:
            # URLs/providers can include credentials; never return raw exceptions.
            pass
        self.rpc = snapshot

    async def _run(self):
        while True:
            await self.probe_rpc()
            await asyncio.sleep(60)

    async def start(self):
        self.configure()
        self._task = asyncio.create_task(self._run(), name="eflow-service-status")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def snapshot(self):
        if self.config is None:
            self.configure()
        runtime = monitor.snapshot()
        return {"started_at": monitor.started_at, "history_limit": 60,
                **{key: {**deepcopy(value), **runtime[key]} for key, value in self.config.items()},
                "rpc": deepcopy(self.rpc)}


service_status = ServiceStatus()
