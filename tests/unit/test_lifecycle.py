import unittest

from workflow_cockpit.services.run_state import RunStateData
from workflow_cockpit.services.snapshot import OutcomeKind
from workflow_cockpit.session.lifecycle import (
    FAILURE_DETAIL_LIMIT,
    _failure_detail,
    classify_outcome,
)


def classify(state, **kwargs):
    return classify_outcome(
        contract_error=None,
        abort_requested=False,
        reaped=True,
        state=state,
        **kwargs,
    )


class FailureDetailTests(unittest.TestCase):
    def test_prefers_step_stderr_over_stdout(self):
        state = RunStateData(
            status="failed",
            current_step_id="init-quick",
            step_results={
                "init-quick": {
                    "type": "shell",
                    "output": {"stdout": "stdout text", "stderr": "stderr text"},
                }
            },
            error="Shell command exited with code 1.",
        )
        outcome = classify(state)
        self.assertIs(outcome.kind, OutcomeKind.FAILURE)
        self.assertEqual(outcome.detail, "stderr text")
        self.assertEqual(outcome.step_id, "init-quick")

    def test_falls_back_to_stdout_when_stderr_blank(self):
        state = RunStateData(
            status="failed",
            current_step_id="init-quick",
            step_results={"init-quick": {"output": {"stdout": "stdout text", "stderr": "   "}}},
        )
        self.assertEqual(classify(state).detail, "stdout text")

    def test_trims_captured_output(self):
        state = RunStateData(
            status="failed",
            current_step_id="init-quick",
            step_results={"init-quick": {"output": {"stderr": "\n  real cause  \n"}}},
        )
        self.assertEqual(classify(state).detail, "real cause")

    def test_prefers_step_error_over_top_level_error(self):
        state = RunStateData(
            status="failed",
            current_step_id="init-quick",
            step_results={"init-quick": {"output": {}, "error": "step boom"}},
            error="top boom",
        )
        self.assertEqual(classify(state).detail, "step boom")

    def test_falls_back_to_top_level_error_without_step_output(self):
        state = RunStateData(
            status="failed",
            current_step_id="init-quick",
            step_results={},
            error="top boom",
        )
        self.assertEqual(classify(state).detail, "top boom")

    def test_falls_back_to_generic_without_any_error(self):
        state = RunStateData(status="failed", current_step_id="init-quick", step_results={})
        self.assertEqual(classify(state).detail, "Engine status: failed")

    def test_missing_state_falls_back_to_generic(self):
        self.assertEqual(_failure_detail(None, "failed"), "Engine status: failed")

    def test_read_only_failure_uses_step_output(self):
        state = RunStateData(
            status="failed",
            current_step_id="init-quick",
            step_results={"init-quick": {"output": {"stderr": "read-only cause"}}},
        )
        self.assertEqual(classify(state, read_only=True).detail, "read-only cause")

    def test_oversized_output_is_bounded(self):
        huge = "x" * (FAILURE_DETAIL_LIMIT + 500)
        state = RunStateData(
            status="failed",
            current_step_id="init-quick",
            step_results={"init-quick": {"output": {"stderr": huge}}},
        )
        detail = classify(state).detail
        self.assertLessEqual(len(detail), FAILURE_DETAIL_LIMIT + 1)
        self.assertTrue(detail.endswith("…"))


if __name__ == "__main__":
    unittest.main()
