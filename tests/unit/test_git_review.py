import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from workflow_cockpit.services.git import (
    DEFAULT_PREVIEW_BYTES,
    GitService,
    is_binary_bytes,
    is_specify_path,
    parse_name_status,
    truncate_utf8,
)
from workflow_cockpit.services.review import ChangedFile, ChangeKind


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)


@unittest.skipUnless(shutil.which("git"), "git executable is unavailable")
class WorktreeChangesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        run(self.root, "init", "-q", "-b", "main")
        run(self.root, "config", "user.email", "cockpit@example.test")
        run(self.root, "config", "user.name", "Cockpit Test")
        (self.root / "tracked.txt").write_text("one\n", encoding="utf-8")
        (self.root / "delete.txt").write_text("bye\n", encoding="utf-8")
        (self.root / "rename.txt").write_text("old\n", encoding="utf-8")
        (self.root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        run(self.root, "add", "-A")
        run(self.root, "commit", "-qm", "base")
        self.baseline = run(self.root, "rev-parse", "HEAD").stdout.strip()
        self.service = GitService(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_classifies_and_excludes(self):
        (self.root / "tracked.txt").write_text("two\n", encoding="utf-8")
        (self.root / "delete.txt").unlink()
        run(self.root, "mv", "rename.txt", "renamed.txt")
        (self.root / "untracked.txt").write_text("new\n", encoding="utf-8")
        (self.root / "ignored.txt").write_text("noise\n", encoding="utf-8")
        (self.root / ".specify" / "workflows").mkdir(parents=True)
        (self.root / ".specify" / "workflows" / "artifact.json").write_text("{}", encoding="utf-8")

        snapshot = self.service.worktree_changes(self.baseline)
        by_path = {item.path: item for item in snapshot.files}
        self.assertEqual(by_path["tracked.txt"].kind, ChangeKind.MODIFIED)
        self.assertEqual(by_path["delete.txt"].kind, ChangeKind.DELETED)
        self.assertEqual(by_path["renamed.txt"].kind, ChangeKind.RENAMED)
        self.assertEqual(by_path["renamed.txt"].old_path, "rename.txt")
        self.assertEqual(by_path["untracked.txt"].kind, ChangeKind.ADDED)
        self.assertNotIn("ignored.txt", by_path)
        self.assertFalse(any(path.startswith(".specify") for path in by_path))

    def test_dirty_pre_start_change_is_included(self):
        (self.root / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        snapshot = self.service.worktree_changes(self.baseline)
        self.assertIn("tracked.txt", {item.path for item in snapshot.files})

    def test_branch_commit_after_baseline_is_included(self):
        (self.root / "branch.txt").write_text("branch\n", encoding="utf-8")
        run(self.root, "add", "branch.txt")
        run(self.root, "commit", "-qm", "branch change")
        snapshot = self.service.worktree_changes(self.baseline)
        self.assertIn("branch.txt", {item.path for item in snapshot.files})

    def test_empty_change_set(self):
        snapshot = self.service.worktree_changes(self.baseline)
        self.assertTrue(snapshot.empty)
        self.assertEqual(snapshot.status, "ready")

    def test_missing_baseline_returns_empty(self):
        self.assertTrue(self.service.worktree_changes(None).empty)


@unittest.skipUnless(shutil.which("git"), "git executable is unavailable")
class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        run(self.root, "init", "-q", "-b", "main")
        run(self.root, "config", "user.email", "cockpit@example.test")
        run(self.root, "config", "user.name", "Cockpit Test")
        (self.root / "tracked.txt").write_text("one\ntwo\n", encoding="utf-8")
        (self.root / "gone.txt").write_text("gone content\n", encoding="utf-8")
        run(self.root, "add", "-A")
        run(self.root, "commit", "-qm", "base")
        self.baseline = run(self.root, "rev-parse", "HEAD").stdout.strip()
        self.service = GitService(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_modified_diff_and_rendered(self):
        (self.root / "tracked.txt").write_text("one\nchanged\n", encoding="utf-8")
        changed = ChangedFile(path="tracked.txt", kind=ChangeKind.MODIFIED)
        diff = self.service.document(changed, "diff", baseline=self.baseline)
        self.assertIn("+changed", diff.text)
        rendered = self.service.document(changed, "rendered", baseline=self.baseline)
        self.assertIn("changed", rendered.text)
        self.assertFalse(rendered.binary)

    def test_deleted_rendered_reads_baseline_blob(self):
        (self.root / "gone.txt").unlink()
        changed = ChangedFile(path="gone.txt", kind=ChangeKind.DELETED)
        rendered = self.service.document(changed, "rendered", baseline=self.baseline)
        self.assertIn("gone content", rendered.text)

    def test_binary_file_reports_metadata(self):
        (self.root / "blob.bin").write_bytes(b"\x00\x01\x02binary")
        changed = ChangedFile(path="blob.bin", kind=ChangeKind.ADDED)
        document = self.service.document(changed, "diff", baseline=self.baseline)
        self.assertTrue(document.binary)
        self.assertIn("Binary", document.note)
        self.assertEqual(document.text, "")

    def test_untracked_added_diff_is_synthesized(self):
        (self.root / "new.txt").write_text("fresh\n", encoding="utf-8")
        changed = ChangedFile(path="new.txt", kind=ChangeKind.ADDED)
        document = self.service.document(changed, "diff", baseline=self.baseline)
        self.assertIn("+fresh", document.text)

    def test_large_file_is_bounded_then_full(self):
        big = "line\n" * (DEFAULT_PREVIEW_BYTES // 4)
        (self.root / "big.txt").write_text(big, encoding="utf-8")
        changed = ChangedFile(path="big.txt", kind=ChangeKind.ADDED)
        preview = self.service.document(changed, "rendered", baseline=self.baseline)
        self.assertTrue(preview.truncated)
        self.assertEqual(preview.limit_bytes, DEFAULT_PREVIEW_BYTES)
        full = self.service.document(changed, "rendered", baseline=self.baseline, full=True)
        self.assertFalse(full.truncated)

    def test_path_traversal_is_rejected(self):
        self.assertIsNone(self.service.resolve_path("../outside.txt"))
        self.assertIsNone(self.service.resolve_path("/etc/passwd"))
        self.assertIsNotNone(self.service.resolve_path("tracked.txt"))


class PureHelperTests(unittest.TestCase):
    def test_parse_name_status_handles_rename(self):
        raw = "M\0a.txt\0R100\0old.txt\0new.txt\0A\0b.txt\0"
        files = parse_name_status(raw)
        self.assertEqual([(item.path, item.kind) for item in files], [
            ("a.txt", ChangeKind.MODIFIED),
            ("new.txt", ChangeKind.RENAMED),
            ("b.txt", ChangeKind.ADDED),
        ])
        self.assertEqual(files[1].old_path, "old.txt")

    def test_specify_prefix(self):
        self.assertTrue(is_specify_path(".specify"))
        self.assertTrue(is_specify_path(".specify/workflows/x"))
        self.assertFalse(is_specify_path(".specifyx"))
        self.assertFalse(is_specify_path("src/.specify"))
        self.assertFalse(is_specify_path(".specify\\workflows\\x"))

    def test_binary_detection(self):
        self.assertTrue(is_binary_bytes(b"a\x00b"))
        self.assertFalse(is_binary_bytes(b"hello"))

    def test_truncate_utf8_keeps_character_boundary(self):
        text = "ääää"
        truncated = truncate_utf8(text, 5)
        self.assertLessEqual(len(truncated.encode("utf-8")), 5)
        self.assertTrue(text.startswith(truncated))


if __name__ == "__main__":
    unittest.main()
