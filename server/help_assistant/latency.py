"""Duration-only local diagnostics. Never record prompts, identities or audio."""
import json
import logging
from pathlib import Path


def record_latency(stage, **durations):
    # Callers pass measurements, never arbitrary response/payload dictionaries.
    values = {key: round(value, 4) for key, value in durations.items()
              if isinstance(value, (int, float)) and not isinstance(value, bool)}
    try:
        with (Path(__file__).resolve().parents[1] / 'help-latency.jsonl').open('a', encoding='utf-8') as output:
            output.write(json.dumps({'schema': 1, 'stage': stage, **values}, separators=(',', ':')) + '\n')
    except OSError:
        logging.getLogger(__name__).warning('Could not record help timing')
