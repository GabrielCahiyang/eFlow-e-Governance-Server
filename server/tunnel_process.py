"""Start, observe, and stop one Cloudflare Quick Tunnel process."""

from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time


TUNNEL_URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def find_cloudflared(explicit_path: str | None) -> str:
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if path.is_file():
            return str(path)
        raise FileNotFoundError(f"cloudflared was not found at {path}")

    executable = shutil.which("cloudflared")
    if executable:
        return executable
    raise FileNotFoundError(
        "cloudflared is not installed or is not on PATH. "
        "Install it with `winget install Cloudflare.cloudflared`."
    )


class QuickTunnelProcess:
    def __init__(self, executable: str, gateway_origin: str) -> None:
        self._connected = threading.Event()
        self._process = subprocess.Popen(
            [
                executable,
                "tunnel",
                "--url",
                gateway_origin,
                "--no-autoupdate",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._output: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._read_output, daemon=True).start()

    @property
    def return_code(self) -> int | None:
        return self._process.poll()

    def wait_for_url(self, timeout_seconds: float = 45.0) -> str:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.return_code is not None and self._output.empty():
                raise RuntimeError(f"cloudflared exited with code {self.return_code}")
            try:
                line = self._output.get(timeout=0.5)
            except queue.Empty:
                continue
            if line is None:
                break
            print(f"[cloudflared] {line}", flush=True)
            match = TUNNEL_URL_PATTERN.search(line)
            if match:
                threading.Thread(target=self._drain_output, daemon=True).start()
                return match.group(0).rstrip("/")
        raise RuntimeError("Timed out waiting for a trycloudflare.com URL")

    def wait_until_connected(self, timeout_seconds: float = 45.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self._connected.wait(0.5):
                return
            if self.return_code is not None:
                raise RuntimeError(f"cloudflared exited with code {self.return_code}")
        raise RuntimeError("Cloudflare did not register the tunnel connection")

    def stop(self) -> None:
        if self.return_code is not None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._process.kill()

    def _read_output(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            clean_line = line.rstrip()
            if "Registered tunnel connection" in clean_line:
                self._connected.set()
            self._output.put(clean_line)
        self._output.put(None)

    def _drain_output(self) -> None:
        while True:
            line = self._output.get()
            if line is None:
                return
            print(f"[cloudflared] {line}", flush=True)
