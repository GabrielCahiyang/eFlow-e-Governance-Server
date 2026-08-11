#!/usr/bin/env python3
"""
Start script for the Local LLM Backend.

Usage:
    python server/start.py          # first run: creates venv, installs deps, starts
    python server/start.py --skip-setup   # skip venv setup, just start

This script:
1. Creates a Python virtual environment (server/.venv) if it doesn't exist
2. Installs requirements.txt into the venv
3. Supervises the private FastAPI server on port 8321
4. Supervises the automatic Cloudflare/Supabase endpoint publisher

The eFlow gateway on port 8322 remains a separate service. The tunnel
supervisor waits for it and never starts or owns that process.
"""

import os
import sys
import subprocess
import platform
import signal
import time
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

SERVER_DIR = Path(__file__).parent.resolve()
VENV_DIR = SERVER_DIR / ".venv"
REQUIREMENTS = SERVER_DIR / "requirements.txt"

IS_WINDOWS = platform.system() == "Windows"
PYTHON_BIN = VENV_DIR / ("Scripts" if IS_WINDOWS else "bin") / ("python.exe" if IS_WINDOWS else "python")
PIP_BIN = VENV_DIR / ("Scripts" if IS_WINDOWS else "bin") / ("pip.exe" if IS_WINDOWS else "pip")


def find_python() -> str:
    """Find a working Python 3.10+ interpreter."""
    for cmd in ["python", "python3", "py -3"]:
        try:
            result = subprocess.run(
                cmd.split(), capture_output=True, text=True,
                timeout=5,
            )
            if result.returncode == 0 or "Python 3" in (result.stdout + result.stderr):
                # Verify version
                ver_result = subprocess.run(
                    [*cmd.split(), "--version"],
                    capture_output=True, text=True, timeout=5,
                )
                version_str = ver_result.stdout.strip() + ver_result.stderr.strip()
                if "3.1" in version_str or "3.9" in version_str:
                    return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return "python"


def setup_venv():
    """Create virtual environment and install dependencies."""
    if PYTHON_BIN.exists():
        print(f"  [OK] Virtual environment exists at {VENV_DIR}")
    else:
        print(f"  -> Creating virtual environment at {VENV_DIR} ...")
        python_cmd = find_python()
        subprocess.run(
            [*python_cmd.split(), "-m", "venv", str(VENV_DIR)],
            check=True,
        )
        print("  [OK] Virtual environment created")

    # Check if deps already installed (skip slow pip checks)
    marker = VENV_DIR / ".deps_installed"
    if marker.exists():
        print("  [OK] Dependencies already installed (delete server/.venv/.deps_installed to force reinstall)")
        return

    # Install / upgrade dependencies
    print("  -> Installing dependencies ...")

    # Upgrade pip (non-fatal -- old pip still works fine)
    subprocess.run(
        [str(PYTHON_BIN), "-m", "pip", "install", "--upgrade", "pip"],
        capture_output=True,
    )

    # Install llama-cpp-python from prebuilt wheels (avoids C++ compilation)
    print("  -> Installing llama-cpp-python (prebuilt wheel) ...")
    result = subprocess.run(
        [
            str(PYTHON_BIN), "-m", "pip", "install",
            "llama-cpp-python>=0.3.0",
            "--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/cpu",
            "--prefer-binary",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Fallback: try normal install (will compile from source)
        print("  [WARN] Prebuilt wheel not found, compiling from source (this may take a few minutes) ...")
        subprocess.run(
            [str(PYTHON_BIN), "-m", "pip", "install", "llama-cpp-python>=0.3.0"],
            check=True,
        )

    # Install remaining dependencies
    subprocess.run(
        [str(PYTHON_BIN), "-m", "pip", "install", "-r", str(REQUIREMENTS)],
        check=True,
    )

    # Write marker so we skip this next time
    marker.write_text("installed")
    print("  [OK] Dependencies installed")


def _stop_child(process: subprocess.Popen | None) -> None:
    if not process or process.poll() is not None:
        return
    if IS_WINDOWS:
        subprocess.run(
            ["taskkill", "/T", "/PID", str(process.pid)],
            capture_output=True,
            timeout=10,
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                timeout=10,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)


def supervise_services() -> int:
    """Keep both the AI API and tunnel supervisor alive until shutdown."""
    print("\n[START] Supervising private AI API on 127.0.0.1:8321")
    print("[START] Supervising automatic Cloudflare endpoint publishing")
    print("[INFO]  The separate eFlow gateway must be running on 127.0.0.1:8322")
    print(f"[INFO]  Models directory: {SERVER_DIR.parent / 'models'}\n")

    commands = {
        "AI server": [str(PYTHON_BIN), str(SERVER_DIR / "main.py")],
        "tunnel supervisor": [
            str(PYTHON_BIN),
            str(SERVER_DIR / "tunnel_supervisor.py"),
        ],
    }
    processes: dict[str, subprocess.Popen | None] = {
        name: None for name in commands
    }
    stopping = False

    def request_shutdown(_signum=None, _frame=None):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_shutdown)

    try:
        while not stopping:
            for name, command in commands.items():
                process = processes[name]
                if process is not None and process.poll() is None:
                    continue
                if process is not None:
                    print(
                        f"[RESTART] {name} exited with code {process.returncode}; "
                        "restarting automatically in 5 seconds.",
                        flush=True,
                    )
                    for _ in range(50):
                        if stopping:
                            break
                        time.sleep(0.1)
                if stopping:
                    break
                processes[name] = subprocess.Popen(
                    command,
                    cwd=str(SERVER_DIR),
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
                    ),
                    start_new_session=not IS_WINDOWS,
                )
            time.sleep(1)
    except KeyboardInterrupt:
        stopping = True
    finally:
        print("[STOP] Shutting down supervised AI services.", flush=True)
        for process in processes.values():
            _stop_child(process)
    return 0


def main():
    print("\n========================================")
    print("    Local LLM Backend — Setup & Run")
    print("========================================\n")

    skip_setup = "--skip-setup" in sys.argv

    if not skip_setup:
        setup_venv()

    raise SystemExit(supervise_services())


if __name__ == "__main__":
    main()
