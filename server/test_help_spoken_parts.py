import unittest
from help_assistant.spoken_reply import spoken_parts, spoken_summary

class SpokenPartsTests(unittest.TestCase):
    def test_parts_retain_the_complete_checked_summary_without_added_claims(self):
        text = 'Review the project budget, then choose the task and request petty cash. Keep the receipt for settlement.'
        parts = spoken_parts(text)
        self.assertEqual(' '.join(parts), spoken_summary(text))
        self.assertLessEqual(len(parts), 4)
        self.assertLessEqual(len(parts[0]), 32)

    def test_short_answers_and_large_tokens_remain_intact(self):
        for text in ('Check the project table.', 'A' * 100):
            self.assertEqual(spoken_parts(text), [text])

    def test_overlong_answers_still_use_the_existing_safe_summary(self):
        text = ' '.join(['Very long project name'] * 100)
        self.assertEqual(' '.join(spoken_parts(text)), spoken_summary(text))
