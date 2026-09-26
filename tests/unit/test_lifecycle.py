import unittest

from workflow_cockpit.services.run_state import RunStateData
from workflow_cockpit.services.snapshot import OutcomeKind
from workflow_cockpit.session.lifecycle import (
    FAILURE_DETAIL_LIMIT,
    STREAM_DETAIL_LABEL,
    STREAM_TAIL_LINES,
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


class StreamFallbackTests(unittest.TestCase):
    def _failed_command_state(self, **result):
        return RunStateData(
            status="failed",
            current_step_id="finish",
            step_results={"finish": {"type": "command", **result}},
        )

    def test_uses_stream_when_step_output_blank(self):
        state = self._failed_command_state(output={"stdout": "", "stderr": ""})
        outcome = classify(state, stream_tail=["PR creation failed", "exit 1"])
        self.assertIs(outcome.kind, OutcomeKind.FAILURE)
        self.assertEqual(outcome.detail, "PR creation failed\nexit 1")
        self.assertEqual(outcome.detail_label, STREAM_DETAIL_LABEL)

    def test_captured_output_wins_over_stream(self):
        state = RunStateData(
            status="failed",
            current_step_id="init-quick",
            step_results={"init-quick": {"type": "shell", "output": {"stderr": "captured"}}},
        )
        outcome = classify(state, stream_tail=["stream noise"])
        self.assertEqual(outcome.detail, "captured")
        self.assertEqual(outcome.detail_label, "")

    def test_stream_wins_over_generic_step_error(self):
        state = self._failed_command_state(error="Command exited with code 1")
        outcome = classify(state, stream_tail=["real cause"])
        self.assertEqual(outcome.detail, "real cause")
        self.assertEqual(outcome.detail_label, STREAM_DETAIL_LABEL)

    def test_no_stream_falls_back_to_step_error(self):
        state = self._failed_command_state(error="Command exited with code 1")
        outcome = classify(state, stream_tail=[])
        self.assertEqual(outcome.detail, "Command exited with code 1")
        self.assertEqual(outcome.detail_label, "")

    def test_top_level_error_kept_without_step_result(self):
        state = RunStateData(status="failed", current_step_id="finish", step_results={}, error="boom")
        outcome = classify(state, stream_tail=["stream noise"])
        self.assertEqual(outcome.detail, "boom")
        self.assertEqual(outcome.detail_label, "")

    def test_blank_stream_lines_are_ignored(self):
        state = self._failed_command_state(output={"stdout": "  ", "stderr": ""})
        outcome = classify(state, stream_tail=["   ", ""])
        self.assertEqual(outcome.detail, "Engine status: failed")
        self.assertEqual(outcome.detail_label, "")

    def test_read_only_ignores_stream(self):
        state = self._failed_command_state(output={"stdout": "", "stderr": ""})
        outcome = classify(state, read_only=True, stream_tail=["live cause"])
        self.assertEqual(outcome.detail, "Engine status: failed")
        self.assertEqual(outcome.detail_label, "")

    def test_stream_tail_is_line_bounded(self):
        lines = [f"line {index}" for index in range(STREAM_TAIL_LINES + 10)]
        state = self._failed_command_state(output={"stdout": "", "stderr": ""})
        detail = classify(state, stream_tail=lines).detail
        kept = detail.splitlines()
        self.assertEqual(len(kept), STREAM_TAIL_LINES)
        self.assertEqual(kept[0], f"line {10}")

    def test_stream_excerpt_is_char_bounded(self):
        huge = "x" * (FAILURE_DETAIL_LIMIT + 500)
        state = self._failed_command_state(output={"stdout": "", "stderr": ""})
        detail = classify(state, stream_tail=[huge]).detail
        self.assertLessEqual(len(detail), FAILURE_DETAIL_LIMIT + 1)
        self.assertTrue(detail.endswith("…"))

    def test_failure_detail_helper_accepts_stream(self):
        state = self._failed_command_state(output={"stdout": "", "stderr": ""})
        self.assertEqual(_failure_detail(state, "failed", ["stream cause"]), "stream cause")


if __name__ == "__main__":
    unittest.main()
