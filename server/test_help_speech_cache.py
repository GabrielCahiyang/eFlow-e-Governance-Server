import unittest
from help_assistant.speech_cache import SpeechCache

class SpeechCacheTests(unittest.TestCase):
    def test_audio_is_owner_role_and_text_scoped_and_expires(self):
        now = [10]
        cache = SpeechCache(ttl=5, clock=lambda: now[0])
        audio = {'audio': 'synthetic', 'mimeType': 'audio/wav'}
        cache.put(('one', 'head', 'Open the task.'), audio)
        self.assertIsNone(cache.get(('two', 'head', 'Open the task.')))
        self.assertIsNone(cache.get(('one', 'member', 'Open the task.')))
        self.assertEqual(cache.get(('one', 'head', 'Open the task.')), audio)
        now[0] = 15
        self.assertIsNone(cache.get(('one', 'head', 'Open the task.')))
        self.assertEqual(cache.bytes, 0)

    def test_memory_cap_evicts_older_audio_and_rejects_oversized_reply(self):
        cache = SpeechCache(max_bytes=8)
        cache.put(('a',), {'audio': '1234'})
        cache.put(('b',), {'audio': '5678'})
        cache.get(('a',))
        cache.put(('c',), {'audio': '9012'})
        self.assertIsNone(cache.get(('b',)))
        self.assertIsNotNone(cache.get(('a',)))
        cache.put(('oversized',), {'audio': '0' * 9})
        self.assertIsNone(cache.get(('oversized',)))
        self.assertEqual(cache.bytes, 8)
