"""Host protocol: framing, envelopes, correlation ids, error codes, events."""

from __future__ import annotations

import json
import unittest

from workflow_cockpit.host import protocol as p


class FrameBufferTests(unittest.TestCase):
    def test_splits_on_newlines_and_buffers_a_partial_line(self):
        buffer = p.FrameBuffer()
        self.assertEqual([f.line for f in buffer.feed(b'{"a":1}\n{"b')], [b'{"a":1}'])
        self.assertEqual([f.line for f in buffer.feed(b'":2}\n')], [b'{"b":2}'])

    def test_oversized_line_produces_one_marker_and_keeps_the_connection(self):
        buffer = p.FrameBuffer(max_line_bytes=8)
        frames = buffer.feed(b"12345678901234567890")
        self.assertEqual(len(frames), 1)
        self.assertTrue(frames[0].oversized)
        # The rest of the over-long line is discarded; later frames still arrive.
        frames = buffer.feed(b"tail\nok\n")
        self.assertEqual([f.line for f in frames if f.line is not None], [b"ok"])

    def test_oversized_line_with_a_newline_in_the_same_chunk(self):
        buffer = p.FrameBuffer(max_line_bytes=4)
        frames = buffer.feed(b"toolong\nok\n")
        self.assertEqual(len(frames), 2)
        self.assertTrue(frames[0].oversized)
        self.assertEqual(frames[1].line, b"ok")

    def test_buffer_never_grows_past_the_bound(self):
        buffer = p.FrameBuffer(max_line_bytes=16)
        for _ in range(10):
            buffer.feed(b"x" * 64)
        self.assertLessEqual(len(buffer._buffer), 16)


class DecodeTests(unittest.TestCase):
    def test_decodes_one_json_object(self):
        self.assertEqual(p.decode(b'{"id":"1","op":"status"}'), {"id": "1", "op": "status"})

    def test_rejects_invalid_json(self):
        with self.assertRaises(p.ProtocolError):
            p.decode(b"{not json")

    def test_rejects_a_non_object_frame(self):
        with self.assertRaises(p.ProtocolError):
            p.decode(b"[1,2,3]")

    def test_rejects_invalid_utf8(self):
        with self.assertRaises(p.ProtocolError):
            p.decode(b"\xff\xfe")

    def test_rejects_an_empty_frame(self):
        with self.assertRaises(p.ProtocolError):
            p.decode(b"   ")


class EnvelopeTests(unittest.TestCase):
    def test_encode_is_one_newline_terminated_utf8_line(self):
        encoded = p.encode({"a": 1})
        self.assertTrue(encoded.endswith(b"\n"))
        self.assertEqual(encoded.count(b"\n"), 1)
        self.assertEqual(json.loads(encoded.decode("utf-8")), {"a": 1})

    def test_success_echoes_the_id_and_carries_the_version(self):
        message = p.success("abc", {"run": None})
        self.assertEqual(message["id"], "abc")
        self.assertTrue(message["ok"])
        self.assertEqual(message["protocol_version"], p.PROTOCOL_VERSION)
        self.assertNotIn("error", message)

    def test_failure_is_a_structured_error_object(self):
        message = p.failure("abc", p.HostError(p.GATE_NOT_OPEN, "no gate", "wait"))
        self.assertEqual(message["id"], "abc")
        self.assertFalse(message["ok"])
        self.assertEqual(message["error"]["code"], p.GATE_NOT_OPEN)
        self.assertEqual(message["error"]["message"], "no gate")
        self.assertEqual(message["error"]["action"], "wait")
        self.assertEqual(message["protocol_version"], p.PROTOCOL_VERSION)

    def test_error_details_are_optional_but_preserved(self):
        error = p.HostError(p.UNDECLARED_OPTION, "bad option", "choose", {"options": ["a", "b"]})
        self.assertEqual(error.to_dict()["details"], {"options": ["a", "b"]})
        self.assertNotIn("details", p.HostError(p.BAD_REQUEST, "x").to_dict())

    def test_event_has_no_id_and_carries_seq_and_version(self):
        message = p.event(p.GATE_OPEN, {"gate": {}}, 7)
        self.assertNotIn("id", message)
        self.assertEqual(message["event"], p.GATE_OPEN)
        self.assertEqual(message["seq"], 7)
        self.assertEqual(message["protocol_version"], p.PROTOCOL_VERSION)

    def test_correlation_id_is_echoed_verbatim_and_null_when_unparseable(self):
        self.assertEqual(p.correlation_id({"id": "req-1"}), "req-1")
        self.assertEqual(p.correlation_id({"id": 12}), "12")
        self.assertIsNone(p.correlation_id({"id": {"nested": 1}}))
        self.assertIsNone(p.correlation_id({}))
        self.assertIsNone(p.correlation_id(None))


class ErrorCodeTests(unittest.TestCase):
    def test_every_contract_code_is_declared(self):
        expected = {
            "host_already_running",
            "run_in_progress",
            "undeclared_option",
            "claim_live_foreign",
            "gate_not_open",
            "stale_token",
            "unknown_op",
            "bad_request",
            "user_only",
            "socket_path_too_long",
        }
        self.assertEqual(p.ERROR_CODES, expected)

    def test_every_error_code_builds_a_structured_object(self):
        for code in sorted(p.ERROR_CODES):
            with self.subTest(code=code):
                payload = p.error_object(code, "message", "action")
                self.assertEqual(payload["code"], code)
                self.assertEqual(payload["message"], "message")
                self.assertEqual(payload["action"], "action")

    def test_operations_and_events_match_the_contract(self):
        self.assertEqual(
            p.OPERATIONS,
            {"list", "validate", "start", "status", "gate", "decide", "abort", "adopt", "resume"},
        )
        self.assertEqual(p.EVENTS, {"gate_open", "status_changed", "terminal"})
        self.assertTrue(p.MUTATING_OPERATIONS <= p.OPERATIONS)


if __name__ == "__main__":
    unittest.main()
