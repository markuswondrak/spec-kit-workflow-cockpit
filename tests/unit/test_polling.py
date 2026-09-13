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


if __name__ == "__main__":
    unittest.main()
