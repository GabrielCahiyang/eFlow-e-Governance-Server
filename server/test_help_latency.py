import json
import unittest
from unittest.mock import mock_open, patch
from help_assistant.latency import record_latency


class LatencyPrivacyTests(unittest.TestCase):
    def test_diagnostics_never_serialize_text_audio_or_credentials(self):
        output=mock_open()
        with patch('help_assistant.latency.Path.open',output):
            record_latency('asr',worker_seconds=1.23456,raw_question='PRIVATE QUESTION',
                           audio=b'PRIVATE AUDIO',jwt='PRIVATE TOKEN')
        record=json.loads(output().write.call_args.args[0])
        self.assertEqual(record,{'schema':1,'stage':'asr','worker_seconds':1.2346})

    def test_unwritable_diagnostics_do_not_break_the_voice_turn(self):
        with patch('help_assistant.latency.Path.open',side_effect=OSError('Disk unavailable')),patch('help_assistant.latency.logging.getLogger'):
            record_latency('asr',worker_seconds=1)
