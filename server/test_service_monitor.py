"""Offline monitoring regression tests: real thread/process boundaries, no chain writes."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import logging
import threading
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

import service_monitor
from service_monitor import ServiceMonitor, observed_executor, update_current
import inference_worker
from inference_worker import InferenceWorker
from server_logging import BufferAndBroadcastHandler, LogBuffer, SSEManager
from service_status import ServiceStatus


def monitored_child(connection):
    body = connection.recv()
    record = {"run_id": "child-stage", "service": "pygad", "operation": "assign_and_schedule",
              "origin": "decomposition", "status": "running", "submitted_at": time.time(),
              "started_at": time.time(), "completed_at": None, "metadata": {"generation": 1}}
    connection.send(("service", record))
    if body.get("hang"):
        time.sleep(60)
    else:
        record.update(status="completed", completed_at=time.time(), duration_ms=3)
        connection.send(("service", record))
        connection.send(("result", {"eval_count": 2, "timings_ms": {"total": 3}}))
    while True:
        connection.recv()


class MetadataTests(unittest.TestCase):
    def test_metadata_whitelist_and_bounded_history(self):
        monitor = ServiceMonitor(history_limit=2)
        for _ in range(4):
            run = monitor.begin("pygad", "assign", {"tasks": 4, "employees": 2, "prompt": "PRIVATE", "private_key": "SECRET"})
            monitor.finish(run, result={"fitness_score": 81, "generation_history": list(range(300)),
                                       "tasks": [{"name": "PRIVATE"}], "metrics": {"skill_match_score": 9, "PRIVATE": 3}})
        result = monitor.snapshot()["pygad"]
        self.assertEqual(result["counts"]["completed"], 4)
        self.assertEqual(len(result["recent_runs"]), 2)
        self.assertEqual(len(result["recent_runs"][0]["metadata"]["generation_history"]), 200)
        self.assertEqual(result["recent_runs"][0]["metadata"]["tasks"], 4)
        self.assertNotIn("PRIVATE", str(result))
        self.assertNotIn("SECRET", str(result))
        result["recent_runs"][0]["metadata"]["tasks"] = 500
        self.assertEqual(monitor.snapshot()["pygad"]["recent_runs"][0]["metadata"]["tasks"], 4)

    def test_timeout_after_submission_is_unconfirmed_and_simulation_is_explicit(self):
        monitor = ServiceMonitor()
        run = monitor.begin("blockchain", "anchor_genesis", {"simulated": False})
        monitor.update(run, {"tx_hash": "0x" + "a" * 64})
        monitor.finish(run, "failed", error="Receipt deadline exceeded.")
        self.assertEqual(monitor.snapshot()["blockchain"]["recent_runs"][0]["status"], "unconfirmed")
        run = monitor.begin("blockchain", "anchor_genesis", {"simulated": True})
        monitor.finish(run, result={"tx_hash": "SIMULATION:example", "block_number": None})
        latest = monitor.snapshot()["blockchain"]["recent_runs"][0]
        self.assertTrue(latest["metadata"]["simulated"])
        self.assertNotIn("block_number", latest["metadata"])

    def test_reverted_receipt_is_failed_and_retains_submitted_hash(self):
        import polygon_service
        monitor = ServiceMonitor()
        web3 = MagicMock()
        web3.is_connected.return_value = True
        web3.eth.send_raw_transaction.return_value = bytes.fromhex("a" * 64)
        web3.eth.wait_for_transaction_receipt.return_value = {"blockNumber": 123, "status": 0}
        with patch.object(service_monitor, "monitor", monitor), patch.object(polygon_service, "POLYGON_PRIVATE_KEY", "1" * 64), patch.object(polygon_service, "_get_web3", return_value=web3), patch.dict("sys.modules", {"web3": SimpleNamespace(Web3=MagicMock())}):
            with self.assertRaisesRegex(RuntimeError, "reverted"):
                service_monitor.observe_sync("blockchain", "anchor_genesis", lambda: polygon_service._send_anchor_tx("0x" + "b" * 64, simulation=False))
        run = monitor.snapshot()["blockchain"]["recent_runs"][0]
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["metadata"]["block_number"], 123)
        self.assertEqual(run["metadata"]["tx_hash"], "0x" + "a" * 64)


class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.monitor = ServiceMonitor()
        self.patch = patch.object(service_monitor, "monitor", self.monitor)
        self.patch.start()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.slots = asyncio.Semaphore(1)

    async def asyncTearDown(self):
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.patch.stop()

    async def wait_until(self, predicate):
        async with asyncio.timeout(3):
            while not predicate():
                await asyncio.sleep(.01)

    async def test_disconnect_keeps_real_running_state_and_slot_until_thread_finishes(self):
        started, finish = threading.Event(), threading.Event()
        calls = []
        def first():
            calls.append("first")
            started.set()
            finish.wait(3)
            update_current({"generation": 10, "generations": 10})
            return {"fitness_score": 80}
        task = asyncio.create_task(observed_executor(self.executor, self.slots, "pygad", "assign", first))
        await self.wait_until(started.is_set)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        second = asyncio.create_task(observed_executor(self.executor, self.slots, "pygad", "assign", lambda: calls.append("second")))
        await self.wait_until(lambda: self.monitor.snapshot()["pygad"]["waiting"] == 1)
        self.assertEqual(self.monitor.snapshot()["pygad"]["running"], 1)
        self.assertEqual(calls, ["first"])
        finish.set()
        await second
        self.assertEqual(calls, ["first", "second"])
        result = self.monitor.snapshot()["pygad"]
        self.assertEqual(result["running"], 0)
        self.assertEqual(result["counts"]["completed"], 2)
        self.assertEqual(result["recent_runs"][1]["metadata"]["generation"], 10)

    async def test_cancel_waiting_request_removes_it_without_running(self):
        await self.slots.acquire()
        function = MagicMock()
        task = asyncio.create_task(observed_executor(self.executor, self.slots, "blockchain", "verify_on_chain", function))
        await self.wait_until(lambda: self.monitor.snapshot()["blockchain"]["waiting"] == 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.slots.release()
        function.assert_not_called()
        self.assertEqual(self.monitor.snapshot()["blockchain"]["waiting"], 0)
        self.assertEqual(self.monitor.snapshot()["blockchain"]["counts"]["cancelled"], 1)

    async def test_cancel_executor_backlog_does_not_start_a_pending_wallet_call(self):
        slots = asyncio.Semaphore(2)
        started, release = threading.Event(), threading.Event()
        def first():
            started.set()
            release.wait(3)
        first_task = asyncio.create_task(observed_executor(self.executor, slots, "blockchain", "anchor_genesis", first))
        await self.wait_until(started.is_set)
        second_function = MagicMock()
        second_task = asyncio.create_task(observed_executor(self.executor, slots, "blockchain", "anchor_genesis", second_function))
        await self.wait_until(lambda: self.monitor.snapshot()["blockchain"]["waiting"] == 1)
        await asyncio.sleep(.01)
        second_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await second_task
        release.set()
        await first_task
        second_function.assert_not_called()
        self.assertEqual(self.monitor.snapshot()["blockchain"]["counts"]["cancelled"], 1)

    async def test_executor_errors_are_not_exposed_as_credentials(self):
        def failure():
            raise ValueError("https://rpc.example/SECRET_PROVIDER_KEY")
        with self.assertRaises(ValueError):
            await observed_executor(self.executor, self.slots, "blockchain", "verify_on_chain", failure)
        self.assertNotIn("SECRET_PROVIDER_KEY", str(self.monitor.snapshot()))
        self.assertEqual(self.monitor.snapshot()["blockchain"]["counts"]["failed"], 1)


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_child_events_reach_parent_and_cancel_closes_active_stage(self):
        monitor = ServiceMonitor()
        with patch.object(inference_worker, "monitor", monitor):
            worker = InferenceWorker(target=monitored_child, timeout_seconds=8)
            task = asyncio.create_task(worker.execute({"model": "test", "hang": True}))
            try:
                async with asyncio.timeout(6):
                    while monitor.snapshot()["pygad"]["running"] == 0:
                        await asyncio.sleep(.01)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                state = monitor.snapshot()["pygad"]
                self.assertEqual(state["running"], 0)
                self.assertEqual(state["counts"]["cancelled"], 1)
                self.assertIsNone(worker.pid)
            finally:
                await worker.close()

    async def test_child_completion_is_retained_without_prompt_or_owner(self):
        monitor = ServiceMonitor()
        with patch.object(inference_worker, "monitor", monitor):
            worker = InferenceWorker(target=monitored_child, timeout_seconds=8)
            try:
                await worker.execute({"model": "test", "messages": [{"content": "PRIVATE"}]})
                state = monitor.snapshot()["pygad"]
                self.assertEqual(state["counts"]["completed"], 1)
                self.assertEqual(state["recent_runs"][0]["origin"], "decomposition")
                self.assertNotIn("PRIVATE", str(state))
            finally:
                await worker.close()


class ServiceStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_simulation_never_probes_rpc_or_serializes_keys(self):
        import polygon_service
        status = ServiceStatus()
        with patch.object(polygon_service, "POLYGON_MODE", "simulation"), patch.object(polygon_service, "POLYGON_PRIVATE_KEY", "SECRET"), patch.object(polygon_service, "POLYGON_RPC_URL", "https://rpc.example/SECRET?token=SECRET"), patch("service_status.get_session", new_callable=AsyncMock) as session:
            status.configure()
            await status.probe_rpc()
            snapshot = status.snapshot()
            self.assertEqual(snapshot["blockchain"]["mode"], "simulation")
            self.assertEqual(snapshot["rpc"]["state"], "not_required")
            self.assertEqual(snapshot["blockchain"]["rpc_host"], "rpc.example")
            self.assertNotIn("SECRET", str(snapshot))
            session.assert_not_awaited()

    async def test_rpc_chain_mismatch_and_failures_are_visible_but_redacted(self):
        status = ServiceStatus()
        status.config = {"blockchain": {"mode": "live", "available": True, "chain_id": 80002}}
        status._rpc_url = "https://rpc.example/SECRET"
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = AsyncMock(return_value={"result": "0x1"})
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post.return_value = context
        with patch("service_status.get_session", AsyncMock(return_value=session)):
            await status.probe_rpc()
            self.assertEqual(status.rpc["state"], "wrong_network")
            response.json.side_effect = ValueError("SECRET")
            await status.probe_rpc()
            self.assertEqual(status.rpc["state"], "unreachable")
            self.assertNotIn("SECRET", str(status.rpc))

    async def test_thread_logs_reach_sse_on_bound_api_loop(self):
        sse = SSEManager()
        queue = sse.subscribe()
        handler = BufferAndBroadcastHandler(LogBuffer(), sse)
        handler.bind_loop(asyncio.get_running_loop())
        record = logging.LogRecord("eflow.service.pygad", logging.INFO, __file__, 1, "Optimizer finished", (), None)
        await asyncio.to_thread(handler.emit, record)
        entry = await asyncio.wait_for(queue.get(), 1)
        self.assertEqual(entry["source"], "eflow.service.pygad")
        sse.unsubscribe(queue)
