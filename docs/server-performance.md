# Server performance verification — 2026-10-12

Host: Intel i7-8750H, 16 GB RAM, GTX 1070 Max-Q with 8 GB VRAM.
Runtime: llama-cpp-python 0.3.36 CUDA 12.4, Q4_K_M GGUF models.

## GPU smoke benchmark

One persistent spawn worker, one model at a time, short synthetic project-task
prompt, output capped at 64 tokens. Each model had one cold and one warm request.
Cold values include model switching and request setup, not a reboot/cold filesystem
cache. First-frame times are visible streamed output and may include reasoning;
these are not speech latency, answer-quality evaluations, or two-user concurrency
measurements. Longer tutorial context and reasoning will change timings.

| Model | Cold request | Warm request | Warm first visible frame |
| --- | ---: | ---: | ---: |
| Qwen3.5 2B | 11.17 s | 1.53 s | 46.5 ms |
| Qwen3.5 4B | 9.46 s | 2.37 s | 76.3 ms |
| DeepSeek R1 8B | 16.27 s | 2.72 s | 46.7 ms |

All six requests completed on the real GPU. The maximum observed delay over a
20 ms event-loop heartbeat was 27.2 ms during this run. Raw measurements are in
[runtime-benchmark.json](runtime-benchmark.json). This demonstrates a responsive
parent loop and warm model reuse, not an end-to-end generation speedup relative
to an earlier version. Existing generation still depends on this laptop's GPU.

## Optimizer comparison

Compared the repository HEAD optimizer with the new optimizer using 30 synthetic
tasks and 15 employees based on existing test fixtures. Ran 2,000 fitness
evaluations three times per implementation and reported the median:

- Previous: 4064.8 ms
- Updated: 483.6 ms
- Speedup: 8.41× in the fitness loop

The same employee assignment produced the same fitness score to within 1e-10.
This isolates repeated text matching and chromosome overhead. It is not an 8.41×
speedup for the entire AI decomposition pipeline. Source budget figures remain
immutable, and dependency scheduling behavior is unchanged.

## Behavioral verification

Offline tests cover FIFO/admission limits, idempotency, owner isolation,
cancellation cleanup before the next request, result expiry, spawn-worker reuse,
real child cancellation/crash/deadline recovery, streamed frame delivery, Unicode
chunk budgets, bounded log readers, and API health responsiveness. Wallet tests
use simulation, and LAYA tests use heuristic mode. No on-chain transactions or
Supabase schema changes were made during verification.

The dashboard was checked with real local hardware telemetry and local test jobs,
including cancelling a queued job and an active GPU job. The QA session used a
local credential and disabled remote logging/tunnel publication. Production
credentials and public endpoints were not rotated.

## Remaining dependency audit

The npm audit reported 70 findings (including development and transitive
packages) and 64 with development dependencies omitted. Some tooling packages
arrive through the official Vibe style package; others belong to pre-existing
Firebase/router/Vite dependencies. These counts do not establish exposure in the
built browser bundle. No forced major upgrades or automatic audit fixes were
applied as part of the UI/backend changes. Review these dependencies separately
before treating this local development stack as a hardened deployment.

## Dashboard development startup

Vite was registering filesystem watchers throughout the root `.venv`, including
Torch headers. Debugging the stalled local process confirmed that watcher path.
The dashboard now ignores both Python environments, model files, backend files,
and Git metadata, scans only its frontend entry, and explicitly prebundles its
current React/Vibe dependencies. The verified cold startup reported 3354 ms;
the browser then loaded normally. No Python environment was deleted.
