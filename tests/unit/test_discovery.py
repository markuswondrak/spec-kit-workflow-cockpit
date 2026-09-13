import tempfile
import unittest
from pathlib import Path

from workflow_cockpit.bootstrap.discovery import ProjectDiscovery, ProjectDiscoveryError


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_finds_nearest_root_from_nested(self):
        nested = self.root / "a" / "b"
        nested.mkdir(parents=True)
        info = ProjectDiscovery(nested).discover()
        self.assertEqual(info.root, self.root.resolve())

    def test_explicit_path(self):
        info = ProjectDiscovery().discover(self.root)
        self.assertEqual(info.root, self.root.resolve())

    def test_missing_project_raises(self):
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaises(ProjectDiscoveryError):
                ProjectDiscovery(other).discover()

    def test_explicit_uninitialized_raises(self):
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaises(ProjectDiscoveryError):
                ProjectDiscovery().discover(other)


if __name__ == "__main__":
    unittest.main()
