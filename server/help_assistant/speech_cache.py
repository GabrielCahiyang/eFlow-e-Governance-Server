"""Bounded RAM-only audio reuse, scoped to the verified caller and role."""
from collections import OrderedDict
import time

class SpeechCache:
    def __init__(self, max_bytes=16_000_000, ttl=180, clock=time.monotonic):
        self.entries = OrderedDict()
        self.max_bytes, self.ttl, self.clock = max_bytes, ttl, clock
        self.bytes = 0

    def _remove(self, key):
        _, _, size = self.entries.pop(key)
        self.bytes -= size

    def _expire(self):
        for key, (expires, _, _) in list(self.entries.items()):
            if expires <= self.clock():
                self._remove(key)

    def get(self, key):
        self._expire()
        entry = self.entries.get(key)
        if entry:
            self.entries.move_to_end(key)
            return entry[1]

    def put(self, key, audio):
        self._expire()
        size = len(audio['audio'])
        if size > self.max_bytes:
            return
        if key in self.entries:
            self._remove(key)
        while self.bytes + size > self.max_bytes:
            self._remove(next(iter(self.entries)))
        self.entries[key] = (self.clock() + self.ttl, audio, size)
        self.bytes += size
