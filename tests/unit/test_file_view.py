"""The read envelope: bounded, versioned, read-only, and never inferring state."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from tests.composition_support import write_project
from tests.fixtures import composition as fx
from tests.fixtures import run_trees as rt
from tests.support import FakeGit, FakeReviewService, FakeSupervisor, compatibility_result
from workflow_cockpit.services.file_view import (
    SCHEMA_VERSION,
    FileViewError,
    build_envelope,
    envelope_json,
    projection_payload,
)
from workflow_cockpit.services.run_state import RunStateReader
from workflow_cockpit.session.cockpit_session import CockpitSession
from workflow_cockpit.session.dependencies import (
    CockpitEnvironment,
    CockpitServices,
    EngineRuntime,
)


def condition_kinds(envelope: dict) -> set[tuple[str, str]]:
    return {(item["source"], item["kind"]) for item in envelope["conditions"]}


class FileViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, **kwargs):
        return build_envelope(self.root, **kwargs).envelope

    def test_flat_live_run_reports_the_full_envelope(self):
        rt.live_flat(self.root)
        rt.write_feature_directory(self.root)
        envelope = self.build()
        self.assertEqual(envelope["schema_version"], SCHEMA_VERSION)
        self.assertEqual(envelope["pointer"]["state"], "ok")
        self.assertEqual(envelope["run"]["run_id"], rt.RUN_ID)
        self.assertEqual(envelope["run"]["workflow_id"], "demo")
        self.assertEqual(envelope["run"]["status"], "running")
        self.assertEqual(envelope["run"]["owner"], "none")
        self.assertEqual(envelope["step"]["step_id"], "prepare")
        self.assertIsNone(envelope["gate"])
        self.assertEqual(envelope["projection"]["current_node_id"], "prepare")
        self.assertEqual(
            [entry["path"] for entry in envelope["feature_files"]["entries"]],
            ["specs/demo/plan.md", "specs/demo/spec.md"],
        )
        self.assertEqual(envelope["file"], None)

    def test_json_output_is_one_object(self):
        rt.live_flat(self.root)
        rt.write_feature_directory(self.root)
        text = envelope_json(build_envelope(self.root))
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(text.count("\n"), text.rstrip("\n").count("\n") + 1)

    def test_open_gate_reports_exactly_the_declared_options_and_a_null_token(self):
        rt.paused_gate(self.root)
        rt.write_feature_directory(self.root)
        envelope = self.build()
        gate = envelope["gate"]
        self.assertEqual(gate["id"], "review")
        self.assertEqual(gate["options"], ["approve", "reject"])
        self.assertIsNone(gate["token"])
        self.assertEqual(gate["ledger"]["state"], "open")
        self.assertFalse(gate["blocked"])

    def test_composed_run_reports_the_inner_scope(self):
        rt.live_composed(self.root, scenario="reference")
        rt.write_feature_directory(self.root)
        envelope = self.build()
        self.assertEqual(envelope["step"]["step_id"], "review")
        self.assertEqual(envelope["step"]["scope_path"], ["review-release"])
        self.assertEqual(envelope["projection"]["current_node_key"], ["review-release", "review"])
        self.assertEqual(envelope["gate"]["options"], ["approve", "reject"])
        self.assertEqual(envelope["gate"]["ledger"]["attempts"], 1)

    def test_projection_matches_the_ui_for_the_same_run(self):
        write_project(self.root, "reference")
        fx.write_run(self.root, "reference", run_id="run-1")
        environment = CockpitEnvironment(self.root, compatibility_result("1.1.3"))
        services = replace(
            CockpitServices.for_environment(environment),
            git=FakeGit(),
            review_source=FakeReviewService(),
        )
        engine = replace(
            EngineRuntime.for_environment(environment, clock=lambda: 10.0),
            supervisor=FakeSupervisor(),
        )
        session = CockpitSession(environment, services=services, engine=engine)
        snapshot = session.inspect("run-1")
        rt.write_pointer(self.root, "run-1", workflow_id="release")
        envelope = self.build()
        self.assertEqual(envelope["projection"], projection_payload(snapshot.graph_projection))

    def test_missing_state_reports_a_condition_and_nulls_derived_fields(self):
        rt.missing_state(self.root)
        envelope = self.build()
        self.assertIn(("state.json", "missing"), condition_kinds(envelope))
        self.assertIsNone(envelope["run"]["status"])
        self.assertIsNone(envelope["step"])
        self.assertIsNone(envelope["gate"])
        self.assertIsNone(envelope["projection"])

    def test_unreadable_state_is_reported_as_partial(self):
        rt.unreadable_state(self.root)
        envelope = self.build()
        self.assertIn(("state.json", "partial"), condition_kinds(envelope))
        self.assertIsNone(envelope["run"]["status"])

    def test_stale_state_is_reported_after_a_previously_good_read(self):
        rt.live_flat(self.root)
        reader = RunStateReader(self.root, rt.RUN_ID)
        reader.read()
        (self.root / ".specify" / "workflows" / "runs" / rt.RUN_ID / "state.json").unlink()
        envelope = self.build(reader=reader)
        self.assertIn(("state.json", "stale"), condition_kinds(envelope))
        self.assertIsNone(envelope["run"]["status"])
        self.assertIsNone(envelope["step"])

    def test_oversized_state_is_reported_as_too_large(self):
        rt.live_flat(self.root)
        with mock.patch("workflow_cockpit.services.file_view.MAX_STATE_BYTES", 64):
            envelope = self.build()
        self.assertIn(("state.json", "too_large"), condition_kinds(envelope))
        self.assertIsNone(envelope["run"]["status"])

    def test_no_run_is_an_empty_envelope_not_an_error(self):
        rt.no_run(self.root)
        envelope = self.build()
        self.assertEqual(envelope["pointer"]["state"], "empty")
        self.assertIsNone(envelope["run"])
        self.assertIsNone(envelope["step"])
        self.assertEqual(envelope["schema_version"], SCHEMA_VERSION)

    def test_pointer_disagreement_is_reported_and_never_guessed(self):
        rt.live_flat(self.root)
        json_path = self.root / ".specify" / "workflows" / "runs" / "current_run.json"
        json_path.write_text('{"schema_version": 1, "run_id": "cockpit-other"}', encoding="utf-8")
        envelope = self.build()
        self.assertEqual(envelope["pointer"]["state"], "disagreement")
        self.assertIn(("current_run", "partial"), condition_kinds(envelope))
        self.assertIsNone(envelope["run"])

    def test_file_read_is_bounded_and_reported(self):
        rt.live_flat(self.root)
        rt.write_feature_directory(self.root, files={"big.md": "x" * 10})
        envelope = self.build(file_path="specs/demo/big.md")
        self.assertEqual(envelope["file"]["path"], "specs/demo/big.md")
        self.assertEqual(envelope["file"]["content"], "x" * 10)
        self.assertFalse(envelope["file"]["truncated"])

    def test_file_outside_the_index_is_refused(self):
        rt.live_flat(self.root)
        rt.write_feature_directory(self.root)
        with self.assertRaises(FileViewError):
            build_envelope(self.root, file_path=".specify/feature.json")

    def test_file_escaping_the_project_is_refused(self):
        rt.live_flat(self.root)
        rt.write_feature_directory(self.root)
        with self.assertRaises(FileViewError):
            build_envelope(self.root, file_path="../../etc/passwd")
        with self.assertRaises(FileViewError):
            build_envelope(self.root, file_path="/etc/passwd")

    def test_read_never_mutates_the_run_tree(self):
        rt.live_flat(self.root)
        rt.write_feature_directory(self.root)
        before = rt.run_tree_hash(self.root)
        self.build(file_path="specs/demo/spec.md")
        self.assertEqual(before, rt.run_tree_hash(self.root))


if __name__ == "__main__":
    unittest.main()
