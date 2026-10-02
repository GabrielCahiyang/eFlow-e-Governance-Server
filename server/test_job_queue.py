import asyncio
import unittest

from job_queue import AiJobQueue, report_job_progress


class AiJobQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_thread_progress_is_scoped_to_the_owner_and_result_is_unchanged(self):
        async def processor(payload):
            await asyncio.to_thread(report_job_progress, "breaking_down", "Breaking this section into tasks.")
            await asyncio.sleep(0)
            report_job_progress("assigning_team", "Suggesting team assignments.")
            return {"message": {"content": "original response"}}

        queue = AiJobQueue(processor)
        await queue.start()
        job = await queue.submit("owner", {"private_input": "must stay private"})
        await queue.stop()
        await asyncio.sleep(0)
        result = await queue.snapshot(job["job_id"], "owner")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"], {"message": {"content": "original response"}})
        self.assertEqual([step["stage"] for step in result["progress"]["history"]], ["breaking_down", "assigning_team"])
        self.assertNotIn("private_input", str(result))
        self.assertIsNone(await queue.snapshot(job["job_id"], "another-owner"))

    async def test_failed_job_releases_the_queue_and_does_not_leak_progress(self):
        async def processor(payload):
            if payload["fail"]:
                report_job_progress("checking_structure", "Checking the task structure.")
                await asyncio.sleep(0)
                raise ValueError("Could not prepare the plan")
            return {"content": "next job"}

        queue = AiJobQueue(processor)
        await queue.start()
        first = await queue.submit("owner", {"fail": True})
        second = await queue.submit("owner", {"fail": False})
        await queue.stop()
        failed = await queue.snapshot(first["job_id"], "owner")
        following = await queue.snapshot(second["job_id"], "owner")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"], "Could not prepare the plan")
        self.assertEqual(following["status"], "completed")
        self.assertIsNone(following["progress"])

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
        overview = await queue.overview()
        self.assertEqual(overview["processing"], 1)
        self.assertEqual(overview["waiting"], 1)
        self.assertEqual(overview["depth"], 2)
        self.assertTrue(overview["worker_online"])
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
