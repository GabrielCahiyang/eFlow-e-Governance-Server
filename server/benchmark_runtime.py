"""Local GPU benchmark. No API credentials, database writes or transactions.

Run from the repository: server/.venv/Scripts/python.exe server/benchmark_runtime.py
Reports short synthetic chat timings, not decomposition quality or voice latency.
"""
import argparse
import asyncio
import json
from pathlib import Path
import time

from inference_worker import InferenceWorker


async def benchmark(tags, tokens):
    worker = InferenceWorker()
    samples = []
    gaps = []
    async def heartbeat():
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.02)
            now = time.perf_counter()
            gaps.append(max(0, now - last - 0.02) * 1000)
            last = now
    monitor = asyncio.create_task(heartbeat())
    try:
        for tag in tags:
            for mode in ('cold', 'warm'):
                frames = []
                first_frame_ms = None
                started = time.perf_counter()
                async def on_chunk(frame):
                    nonlocal first_frame_ms
                    if first_frame_ms is None:
                        first_frame_ms = (time.perf_counter() - started) * 1000
                    frames.append(frame)
                result = await worker.execute({'model': tag, '_stream_id': 'benchmark', 'max_tokens': tokens,
                    'messages': [{'role': 'user', 'content': 'Briefly explain what a project task is.'}]}, on_chunk=on_chunk)
                elapsed = (time.perf_counter() - started) * 1000
                samples.append({'model': tag, 'mode': mode, 'request_ms': round(elapsed, 1),
                    'first_frame_including_load_ms': round(first_frame_ms, 1) if first_frame_ms else None,
                    'visible_tokens': result['eval_count'], **result['timings_ms'],
                    'first_token_ms': result['first_token_ms']})
                print(f"Completed {tag} {mode}", flush=True)
    finally:
        await worker.close()
        monitor.cancel()
        try: await monitor
        except asyncio.CancelledError: pass
    return {'timestamp': time.time(), 'output_cap': tokens, 'samples': samples,
            'maximum_event_loop_delay_ms': round(max(gaps, default=0), 1)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--models', nargs='+', default=['qwen3.5:2b', 'qwen3.5:4b', 'deepseek-r1:8b'])
    parser.add_argument('--tokens', type=int, default=64)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = asyncio.run(benchmark(args.models, args.tokens))
    print(json.dumps(report, indent=2))
    if args.output:
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
