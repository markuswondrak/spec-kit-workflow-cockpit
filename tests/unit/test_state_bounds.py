"""Bounds and version handling: legacy runs unchanged, misreads impossible."""

import tempfile
import time
import unittest
from pathlib import Path

from tests.fixtures import composition as fx
from workflow_cockpit.services.limits import MAX_STATE_BYTES
from workflow_cockpit.services.run_catalog import RunCatalog
from workflow_cockpit.services.run_state import RunStateReader

ABOVE_OLD_BOUND = 300 * 1024


class LegacyBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_legacy_state_has_no_execution_and_reads_as_before(self):
        state = fx.without_execution(fx.load_state("reference"))
        fx.write_run(self.root, "reference", run_id="legacy", state=state)
        data = RunStateReader(self.root, "legacy").read()
        self.assertIsNone(data.execution)
        self.assertFalse(data.too_large)
        self.assertEqual(data.diagnostic, "")
        self.assertEqual(data.status, state["status"])
        # The current result is the flat root-scope lookup, unchanged: the
        # child-scope step id is not addressable in ``step_results``.
        self.assertIsNone(data.current_result())
        self.assertEqual(state["step_results"]["review-release"]["status"], "paused")

    def test_legacy_state_is_identical_when_the_same_run_also_has_inputs(self):
        state = fx.without_execution(fx.load_state("reference"))
        fx.write_run(self.root, "reference", run_id="legacy", state=state)
        first = RunStateReader(self.root, "legacy").read()
        second = RunStateReader(self.root, "legacy").read()
        self.assertEqual(first, second)


class VersionDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_unsupported_versions_report_a_diagnostic_and_no_scope(self):
        for version in (1, 3, "2"):
            with self.subTest(version=version):
                state = fx.with_version(fx.load_state("reference"), version)
                fx.write_run(self.root, "reference", run_id="odd", state=state)
                data = RunStateReader(self.root, "odd").read()
                self.assertFalse(data.too_large)
                self.assertIn("execution version", data.diagnostic)
                # No scope is inferred from current_step_id.
                self.assertIsNone(data.active_node)

    def test_unsupported_version_is_not_adoptable_in_discovery(self):
        state = fx.with_version(fx.load_state("reference"), 1)
        fx.write_run(self.root, "reference", run_id="odd", state=state)
        descriptor = RunCatalog(self.root).describe("odd")
        self.assertFalse(descriptor.adoptable)
        self.assertTrue(descriptor.viewable)
        self.assertIn("execution version", descriptor.reason)


class SizeBoundTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_state_above_the_old_bound_loads_in_both_readers(self):
        state = fx.inflated_state(fx.load_state("reference"), ABOVE_OLD_BOUND)
        self.assertGreater(fx.serialized_size(state), 256 * 1024)
        fx.write_run(self.root, "reference", run_id="big", state=state)
        data = RunStateReader(self.root, "big").read()
        self.assertFalse(data.too_large)
        self.assertIsNotNone(data.execution)
        self.assertIsNotNone(data.execution.active)
        descriptor = RunCatalog(self.root).describe("big")
        self.assertTrue(descriptor.usable)
        self.assertEqual(descriptor.current_step_id, "review")

    def test_state_above_the_shared_bound_is_reported_too_large(self):
        state = fx.inflated_state(fx.load_state("reference"), MAX_STATE_BYTES + 4096)
        self.assertGreater(fx.serialized_size(state), MAX_STATE_BYTES)
        fx.write_run(self.root, "reference", run_id="huge", state=state)
        data = RunStateReader(self.root, "huge").read()
        self.assertTrue(data.too_large)
        self.assertIn("too large", data.diagnostic)
        self.assertIsNone(data.execution)
        descriptor = RunCatalog(self.root).describe("huge")
        self.assertFalse(descriptor.usable)
        self.assertIn("exceeds", descriptor.reason)

    def test_a_state_near_the_bound_parses_within_the_update_budget(self):
        state = fx.inflated_state(fx.load_state("reference"), MAX_STATE_BYTES - 4096)
        fx.write_run(self.root, "reference", run_id="near", state=state)
        reader = RunStateReader(self.root, "near")
        started = time.perf_counter()
        data = reader.read()
        elapsed = time.perf_counter() - started
        self.assertFalse(data.too_large)
        self.assertIsNotNone(data.execution)
        # SC-007: a persisted change becomes visible within 500 ms.
        self.assertLess(elapsed, 0.5, f"parse took {elapsed:.3f}s")

    def test_a_cached_second_read_does_not_reparse(self):
        state = fx.inflated_state(fx.load_state("reference"), ABOVE_OLD_BOUND)
        fx.write_run(self.root, "reference", run_id="big", state=state)
        reader = RunStateReader(self.root, "big")
        first = reader.read()
        started = time.perf_counter()
        second = reader.read()
        elapsed = time.perf_counter() - started
        self.assertIs(first.execution, second.execution)
        self.assertLess(elapsed, 0.1)

    def test_yaml_heavy_state_documents_the_worst_case_parse_cost(self):
        """A near-bound state whose *definitions* carry the bytes.

        The realistic case (retained step output) stays far inside the update
        budget; this measures the pathological one so the cost is known. A
        generous ceiling guards against a pathological regression without
        pretending the worst case is fast.
        """
        state = fx.yaml_inflated_state(fx.load_state("reference"), MAX_STATE_BYTES - 4096)
        self.assertGreater(fx.serialized_size(state), ABOVE_OLD_BOUND)
        fx.write_run(self.root, "reference", run_id="yaml-heavy", state=state)
        started = time.perf_counter()
        data = RunStateReader(self.root, "yaml-heavy").read()
        elapsed = time.perf_counter() - started
        self.assertFalse(data.too_large)
        self.assertIsNotNone(data.execution)
        self.assertLess(elapsed, 5.0, f"worst-case parse took {elapsed:.3f}s")


class MalformedTreeTests(unittest.TestCase):
    def test_malformed_tree_is_diagnosed_and_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fx.write_run(root, "reference", run_id="broken", state=fx.corrupt_tree(fx.load_state("reference")))
            data = RunStateReader(root, "broken").read()
            self.assertIsNotNone(data)
            self.assertIn("malformed", data.diagnostic)
            self.assertIsNone(data.active_node)

    def test_sequence_length_mismatch_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = fx.with_sequence_length_mismatch(fx.load_state("reference"))
            fx.write_run(root, "reference", run_id="broken", state=state)
            data = RunStateReader(root, "broken").read()
            self.assertIsNotNone(data)
            self.assertIn("malformed", data.diagnostic)


if __name__ == "__main__":
    unittest.main()
