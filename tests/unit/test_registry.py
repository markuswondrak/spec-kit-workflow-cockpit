import tempfile
import unittest
from pathlib import Path

from tests.support import write_registry
from workflow_cockpit.services.registry import RegistryError, WorkflowRegistry


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_enabled_only_sorted(self):
        write_registry(
            self.root,
            {
                "zeta": {"name": "Zeta", "enabled": True},
                "alpha": {"name": "Alpha", "enabled": True},
                "hidden": {"name": "Hidden", "enabled": False},
            },
        )
        entries = WorkflowRegistry(self.root).list_runnable()
        self.assertEqual([entry.id for entry in entries], ["alpha", "zeta"])

    def test_missing_registry_is_fatal(self):
        with self.assertRaises(RegistryError):
            WorkflowRegistry(self.root).list_runnable()

    def test_corrupt_registry_is_fatal(self):
        path = self.root / ".specify" / "workflows" / "workflow-registry.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(RegistryError):
            WorkflowRegistry(self.root).entries()

    def test_corrupt_entry_is_fatal(self):
        write_registry(self.root, {"demo": "not-a-mapping"})
        with self.assertRaises(RegistryError):
            WorkflowRegistry(self.root).entries()


if __name__ == "__main__":
    unittest.main()
