import unittest

from workflow_cockpit.engine.normalizer import OutputNormalizer


class NormalizerTests(unittest.TestCase):
    def test_splits_complete_lines_and_partial(self):
        normalizer = OutputNormalizer()
        normalizer.feed("hello\nwor")
        self.assertEqual(normalizer.lines, ["hello"])
        self.assertEqual(normalizer.partial, "wor")
        normalizer.feed("ld\n")
        self.assertEqual(normalizer.lines, ["hello", "world"])
        self.assertEqual(normalizer.partial, "")

    def test_strips_ansi_and_osc(self):
        normalizer = OutputNormalizer()
        normalizer.feed("\x1b[31mred\x1b[0m\n\x1b]0;title\x07plain\n")
        self.assertEqual(normalizer.lines, ["red", "plain"])

    def test_normalizes_carriage_returns(self):
        normalizer = OutputNormalizer()
        normalizer.feed("a\r\nb\rc")
        self.assertEqual(normalizer.lines, ["a", "b"])
        self.assertEqual(normalizer.partial, "c")

    def test_split_utf8_is_replaced(self):
        normalizer = OutputNormalizer()
        normalizer.feed(b"\xe2\x82")
        normalizer.feed(b"\xac done\n")
        self.assertEqual(normalizer.lines, ["€ done"])

    def test_bounded_tail_sets_truncated(self):
        normalizer = OutputNormalizer(max_lines=2)
        normalizer.feed("1\n2\n3\n")
        self.assertEqual(normalizer.lines, ["2", "3"])
        self.assertTrue(normalizer.truncated)
        self.assertEqual(normalizer.tail(1), ["3"])

    def test_truncation_marker_only_once(self):
        normalizer = OutputNormalizer(max_lines=1)
        normalizer.feed("1\n2\n3\n")
        self.assertTrue(normalizer.truncated)


if __name__ == "__main__":
    unittest.main()
