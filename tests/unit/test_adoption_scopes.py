"""Adoption of composed runs is scope-aware and version-guarded."""

import tempfile
import unittest
from pathlib import Path

from tests.fixtures import composition as fx
from workflow_cockpit.services.execution_tree import parse as parse_execution
from workflow_cockpit.services.run_catalog import RunCatalog
from workflow_cockpit.services.run_claim import RunClaimStore
from workflow_cockpit.session.adoption import AdoptError, RunAdopter


class AdoptionScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, scenario: str, *, state=None, run_id="run-composed") -> str:
        fx.write_run(self.root, scenario, run_id=run_id, state=state)
        return run_id

    def test_a_composed_run_is_adoptable_and_described_scope_aware(self):
        run_id = self._run("failed-child")
        descriptor = RunCatalog(self.root).describe(run_id)
        self.assertTrue(descriptor.adoptable)
        binding = RunAdopter(self.root).prepare(run_id, "owner-1")
        self.assertEqual(binding.definition.id, "failed-release")
        # The failing leaf is inside the call, and the tree is the authority.
        tree = parse_execution(fx.load_state("failed-child"))
        self.assertEqual(tree.active.step_id, "boom")
        self.assertEqual(tree.active.enclosing_calls, ("broken-call",))

    def test_unsupported_execution_version_is_view_only(self):
        state = fx.with_version(fx.load_state("reference"), 3)
        run_id = self._run("reference", state=state)
        descriptor = RunCatalog(self.root).describe(run_id)
        self.assertTrue(descriptor.usable)
        self.assertTrue(descriptor.viewable)
        self.assertFalse(descriptor.execution_supported)
        self.assertFalse(descriptor.adoptable)
        self.assertIn("execution version", descriptor.reason)

        adopter = RunAdopter(self.root)
        with self.assertRaisesRegex(AdoptError, "execution version is not supported"):
            adopter.prepare(run_id, "owner-1")
        # Inspecting it read-only still works and claims nothing.
        described, definition = adopter.prepare_inspect(run_id)
        self.assertEqual(described.run_id, run_id)
        self.assertEqual(definition.id, "release")

    def test_view_only_inspection_does_not_claim_ownership(self):
        run_id = self._run("reference")
        adopter = RunAdopter(self.root)
        adopter.prepare_inspect(run_id)
        self.assertFalse(RunClaimStore(self.root).claim_path(run_id).exists())
        # Control: adopting the same run does write the claim file checked above.
        adopter.prepare(run_id, "owner-1")
        self.assertTrue(RunClaimStore(self.root).claim_path(run_id).exists())

    def test_legacy_run_adoption_is_unchanged(self):
        state = fx.without_execution(fx.load_state("reference"))
        run_id = self._run("reference", state=state)
        descriptor = RunCatalog(self.root).describe(run_id)
        self.assertTrue(descriptor.execution_supported)
        self.assertTrue(descriptor.adoptable)


if __name__ == "__main__":
    unittest.main()
