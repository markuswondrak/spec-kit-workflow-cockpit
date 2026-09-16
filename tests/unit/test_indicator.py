import unittest

from workflow_cockpit.ui.widgets.indicator import BounceIndicator


class BounceIndicatorTests(unittest.TestCase):
    def test_blends_dwell_then_sweep_right_then_back(self):
        travel = BounceIndicator.SPAN / BounceIndicator.RATE
        dwell = BounceIndicator.DWELL

        start = BounceIndicator._blends(0.0)
        self.assertEqual(start[0], 0.0)
        self.assertEqual(start[-1], 1.0)
        self.assertTrue(all(a <= b for a, b in zip(start, start[1:], strict=False)))
        # The dot rests at the left before reversing.
        self.assertEqual(start, BounceIndicator._blends(dwell / 2))

        peak = BounceIndicator._blends(dwell + travel)
        self.assertEqual(peak[0], 1.0)
        self.assertEqual(peak[-1], 0.0)
        self.assertTrue(all(a >= b for a, b in zip(peak, peak[1:], strict=False)))
        # The dot rests at the right before reversing.
        self.assertEqual(peak, BounceIndicator._blends(2 * dwell + travel))

        back = BounceIndicator._blends(2 * (travel + dwell))
        self.assertEqual(start, back)

    def test_blends_stay_in_unit_range(self):
        samples = [BounceIndicator._blends(t / 100) for t in range(0, 400)]
        for blends in samples:
            for blend in blends:
                self.assertGreaterEqual(blend, 0.0)
                self.assertLessEqual(blend, 1.0)


if __name__ == "__main__":
    unittest.main()
