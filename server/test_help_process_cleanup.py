"""A cancelled Windows venv worker must not leave its child alive."""
import asyncio
import os
import subprocess
import sys
import unittest
from help_assistant.decoder_process import reap

@unittest.skipUnless(os.name == 'nt', 'Windows launcher regression')
class WorkerCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_reaps_the_owned_worker_and_its_descendant(self):
        code = 'import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); print(p.pid,flush=True); time.sleep(60)'
        process = await asyncio.create_subprocess_exec(sys.executable, '-u', '-c', code, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=0x08000000)
        try:
            child = int(await asyncio.wait_for(process.stdout.readline(), 10))
            await reap(process)
            # tasklist is a read-only liveness check; it cannot terminate a PID.
            listing = subprocess.run(['tasklist', '/FI', f'PID eq {child}', '/FO', 'CSV', '/NH'], capture_output=True, text=True, creationflags=0x08000000, check=True)
            self.assertNotIn(f'"{child}"', listing.stdout)
            self.assertIsNotNone(process.returncode)
        finally:
            await reap(process)
