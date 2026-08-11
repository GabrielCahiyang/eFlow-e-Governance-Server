import asyncio
import unittest

from job_queue import AiJobQueue


class AiJobQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_jobs_run_in_fifo_order_and_report_position(self):
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        execution_order: list[str] = []

        async def processor(payload):
            execution_order.append(payload["name"])
            if payload["name"] == "first":
                first_started.set()
                await release_first.wait()
            return {"name": payload["name"]}

        queue = AiJobQueue(processor)
        await queue.start()
        first = await queue.submit("user-1", {"name": "first"})
        await first_started.wait()
        second = await queue.submit("user-2", {"name": "second"})

        second_waiting = await queue.snapshot(second["job_id"], "user-2")
        self.assertEqual(second_waiting["status"], "queued")
        self.assertEqual(second_waiting["position"], 2)
        self.assertEqual(second_waiting["jobs_ahead"], 1)
        self.assertIsNone(await queue.snapshot(second["job_id"], "user-1"))

        release_first.set()
        for _ in range(50):
            second_done = await queue.snapshot(second["job_id"], "user-2")
            if second_done["status"] == "completed":
                break
            await asyncio.sleep(0.01)

        self.assertEqual(execution_order, ["first", "second"])
        self.assertEqual(second_done["result"], {"name": "second"})
        self.assertIsNotNone(first["job_id"])
        await queue.stop()


if __name__ == "__main__":
    unittest.main()
