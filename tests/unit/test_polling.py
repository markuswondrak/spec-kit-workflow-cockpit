import unittest

from tests.support import FakeSession
from workflow_cockpit.session.polling import PollingLoop


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class PollingTests(unittest.TestCase):
    def test_interval_and_snapshot_publication(self):
        clock = Clock()
        loop = PollingLoop(FakeSession(), interval=0.25, clock=clock)
        self.assertTrue(loop.due())
        first = loop.tick()
        self.assertEqual(first.workflow_id, "demo")
        clock.value = 0.10
        self.assertFalse(loop.due())
        clock.value = 0.30
        self.assertTrue(loop.due())
        loop.tick()
        self.assertIs(loop.last_snapshot, loop._snapshot)

    def test_begin_suppresses_overlapping_polls(self):
        clock = Clock()
        loop = PollingLoop(FakeSession(), interval=0.25, clock=clock)
        self.assertTrue(loop.begin())
        self.assertFalse(loop.begin())
        self.assertTrue(loop.pending)
        loop.produce()
        self.assertFalse(loop.pending)

    def test_begin_respects_the_cadence(self):
        clock = Clock()
        loop = PollingLoop(FakeSession(), interval=0.25, clock=clock)
        loop.produce()
        self.assertFalse(loop.begin())
        clock.value = 0.25
        self.assertTrue(loop.begin())

    def test_failed_snapshot_keeps_last_good_and_records_error(self):
        class FlakySession(FakeSession):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def snapshot(self):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("boom")
                return super().snapshot()

        loop = PollingLoop(FlakySession())
        good = loop.produce()
        self.assertIsNotNone(good)
        after = loop.produce()
        self.assertIs(after, good)
        self.assertIn("boom", loop.last_error)
        self.assertFalse(loop.pending)


if __name__ == "__main__":
    unittest.main()
