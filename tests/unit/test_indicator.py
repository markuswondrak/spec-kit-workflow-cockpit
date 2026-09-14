import unittest

from workflow_cockpit.ui.widgets.indicator import BounceIndicator


class BounceIndicatorTests(unittest.TestCase):
    def test_blends_sweep_right_then_back(self):
        start = BounceIndicator._blends(0.0)
        self.assertEqual(start[0], 0.0)
        self.assertEqual(start[-1], 1.0)
        self.assertTrue(all(a <= b for a, b in zip(start, start[1:])))

        peak = BounceIndicator._blends(BounceIndicator.SPAN / BounceIndicator.RATE)
        self.assertEqual(peak[0], 1.0)
        self.assertEqual(peak[-1], 0.0)
        self.assertTrue(all(a >= b for a, b in zip(peak, peak[1:])))

        back = BounceIndicator._blends(2 * BounceIndicator.SPAN / BounceIndicator.RATE)
        self.assertEqual(start, back)

    def test_blends_stay_in_unit_range(self):
        samples = [BounceIndicator._blends(t / 100) for t in range(0, 400)]
        for blends in samples:
            for blend in blends:
                self.assertGreaterEqual(blend, 0.0)
                self.assertLessEqual(blend, 1.0)


if __name__ == "__main__":
    unittest.main()
