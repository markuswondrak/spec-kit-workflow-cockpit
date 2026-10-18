"""Host process concerns: the socket precheck, stale remnants, and .gitignore."""

from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path

from workflow_cockpit.host.launcher import ensure_gitignore
from workflow_cockpit.host.server import SOCKET_NAME, probe_socket, remove_stale_socket


def bound_socket(path: Path, *, listen: bool) -> socket.socket:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    if listen:
        server.listen(1)
    return server


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / SOCKET_NAME

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_path_is_not_a_live_host(self):
        self.assertFalse(probe_socket(self.path))

    def test_a_plain_file_is_not_a_live_host(self):
        self.path.write_text("not a socket", encoding="utf-8")
        self.assertFalse(probe_socket(self.path))

    def test_a_stale_socket_is_not_a_live_host(self):
        server = bound_socket(self.path, listen=False)
        try:
            self.assertFalse(probe_socket(self.path))
        finally:
            server.close()

    def test_a_listening_host_is_detected(self):
        server = bound_socket(self.path, listen=True)
        try:
            self.assertTrue(probe_socket(self.path))
        finally:
            server.close()

    def test_stale_socket_remnant_is_unlinked(self):
        server = bound_socket(self.path, listen=False)
        server.close()
        remove_stale_socket(self.path)
        self.assertFalse(self.path.exists())

    def test_live_socket_is_never_unlinked(self):
        server = bound_socket(self.path, listen=True)
        try:
            remove_stale_socket(self.path)
            self.assertTrue(self.path.exists())
        finally:
            server.close()


class GitignoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_appends_the_socket_name_once(self):
        (self.root / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
        ensure_gitignore(self.root)
        ensure_gitignore(self.root)
        lines = (self.root / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines.count(SOCKET_NAME), 1)
        self.assertIn("*.pyc", lines)

    def test_creates_the_file_when_absent(self):
        ensure_gitignore(self.root)
        self.assertEqual(
            (self.root / ".gitignore").read_text(encoding="utf-8").strip(), SOCKET_NAME
        )

    def test_keeps_the_existing_newline(self):
        (self.root / ".gitignore").write_text("build/", encoding="utf-8")
        ensure_gitignore(self.root)
        self.assertEqual(
            (self.root / ".gitignore").read_text(encoding="utf-8"),
            f"build/\n{SOCKET_NAME}\n",
        )

    def test_is_non_fatal_when_the_path_is_a_directory(self):
        (self.root / ".gitignore").mkdir()
        ensure_gitignore(self.root)


if __name__ == "__main__":
    unittest.main()
