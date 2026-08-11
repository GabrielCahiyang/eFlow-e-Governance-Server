@echo off
REM ── Control Panel Eflow — One-Click Start ──────────────────────────
REM Starts the private FastAPI LLM server. The Cloudflare tunnel belongs on
REM eFlow's JWT-protected gateway (port 8322), never this raw service.
REM ────────────────────────────────────────────────────────────────────

title ControlPanel Eflow Server

echo.
echo  ╔═══════════════════════════════════════════════╗
echo  ║   ControlPanel Eflow — Starting Services …   ║
echo  ╚═══════════════════════════════════════════════╝
echo.

REM Change to the directory where this script lives
cd /d "%~dp0"

REM Activate venv and run the supervisor. It keeps the private AI server and
REM automatic Cloudflare endpoint publisher alive. The eFlow gateway remains
REM a separate process on port 8322.
echo Starting AI server and automatic tunnel supervisor …
echo.

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo WARNING: .venv not found — running with system Python
)

python start.py --skip-setup
