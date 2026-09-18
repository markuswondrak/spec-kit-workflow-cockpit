import tempfile
import unittest
from pathlib import Path

from workflow_cockpit.session.identity import generate_run_id, owner_id


class IdentityTests(unittest.TestCase):
    def test_run_id_is_unique_and_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            runs.mkdir()
            first = generate_run_id(runs)
            (runs / first).mkdir()
            second = generate_run_id(runs)
            self.assertNotEqual(first, second)
            self.assertTrue(first.startswith("cockpit-"))
            self.assertFalse((runs / second).exists())

    def test_owner_id_is_non_empty_and_unique(self):
        first = owner_id()
        second = owner_id()
        self.assertTrue(first)
        self.assertTrue(second)
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
