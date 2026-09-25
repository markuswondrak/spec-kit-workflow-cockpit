import json
import tempfile
import unittest
from pathlib import Path

from workflow_cockpit.services.feature_review import (
    DEFAULT_PREVIEW_BYTES,
    FeatureReviewService,
    is_markdown_path,
    resolve_feature_directory,
)


class FeatureDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "specs" / "demo" / "nested").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _declare(self, value) -> None:
        (self.root / ".specify").mkdir(exist_ok=True)
        (self.root / ".specify" / "feature.json").write_text(
            json.dumps({"feature_directory": value}), encoding="utf-8"
        )

    def test_declared_directory_is_returned(self):
        self._declare("specs/demo")
        self.assertEqual(resolve_feature_directory(self.root), "specs/demo")

    def test_missing_or_invalid_declarations_yield_none(self):
        self.assertIsNone(resolve_feature_directory(self.root))
        self._declare("../outside")
        self.assertIsNone(resolve_feature_directory(self.root))
        self._declare("/etc")
        self.assertIsNone(resolve_feature_directory(self.root))
        self._declare("specs/missing")
        self.assertIsNone(resolve_feature_directory(self.root))


class FeatureReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.feature = self.root / "specs" / "demo"
        self.feature.mkdir(parents=True)
        (self.root / ".specify").mkdir()
        (self.root / ".specify" / "feature.json").write_text(
            json.dumps({"feature_directory": "specs/demo"}), encoding="utf-8"
        )
        self.service = FeatureReviewService(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_files_recursively_sorted(self):
        (self.feature / "spec.md").write_text("spec\n", encoding="utf-8")
        nested = self.feature / "nested"
        nested.mkdir()
        (nested / "plan.md").write_text("plan\n", encoding="utf-8")

        snapshot = self.service.refresh()
        self.assertEqual(snapshot.status, "ready")
        self.assertEqual(snapshot.feature_dir, "specs/demo")
        self.assertEqual(
            [item.path for item in snapshot.files],
            ["specs/demo/nested/plan.md", "specs/demo/spec.md"],
        )
        # Display labels drop the repeated feature-directory prefix.
        self.assertEqual(
            [item.label for item in snapshot.files],
            ["nested/plan.md", "spec.md"],
        )

    def test_empty_feature_directory_is_ready(self):
        snapshot = self.service.refresh()
        self.assertTrue(snapshot.empty)
        self.assertEqual(snapshot.status, "ready")

    def test_missing_feature_json_is_an_error(self):
        (self.root / ".specify" / "feature.json").unlink()
        snapshot = self.service.refresh()
        self.assertEqual(snapshot.status, "error")
        self.assertIn("feature.json", snapshot.error)

    def test_markdown_detection_is_extension_based(self):
        for path in ("a.md", "a.markdown", "a.MD", "nested/x.Markdown"):
            with self.subTest(path=path):
                self.assertTrue(is_markdown_path(path))
        for path in ("a.txt", "a.mdx", "README", "", None):
            with self.subTest(path=path):
                self.assertFalse(is_markdown_path(path))

    def test_document_renders_text(self):
        (self.feature / "spec.md").write_text("hello\n", encoding="utf-8")
        document = self.service.document("specs/demo/spec.md")
        self.assertEqual(document.path, "specs/demo/spec.md")
        self.assertEqual(document.display, "spec.md")
        self.assertEqual(document.text, "hello\n")
        self.assertFalse(document.binary)
        self.assertFalse(document.truncated)

    def test_document_display_is_relative_to_the_feature_directory(self):
        nested = self.feature / "nested"
        nested.mkdir()
        (nested / "plan.md").write_text("plan\n", encoding="utf-8")
        document = self.service.document("specs/demo/nested/plan.md")
        self.assertEqual(document.path, "specs/demo/nested/plan.md")
        self.assertEqual(document.display, "nested/plan.md")

    def test_markdown_flag_is_set_for_markdown_extensions(self):
        (self.feature / "spec.md").write_text("# Title\n", encoding="utf-8")
        (self.feature / "notes.txt").write_text("plain\n", encoding="utf-8")
        self.assertTrue(self.service.document("specs/demo/spec.md").markdown)
        self.assertFalse(self.service.document("specs/demo/notes.txt").markdown)

    def test_binary_markdown_stays_metadata_only(self):
        (self.feature / "spec.md").write_bytes(b"\x00\x01\x02binary")
        document = self.service.document("specs/demo/spec.md")
        self.assertTrue(document.binary)
        self.assertEqual(document.text, "")

    def test_large_markdown_honors_bounded_preview_then_full(self):
        big = "# Heading\n\n" + ("line\n" * (DEFAULT_PREVIEW_BYTES // 4))
        (self.feature / "spec.md").write_text(big, encoding="utf-8")
        preview = self.service.document("specs/demo/spec.md")
        self.assertTrue(preview.markdown)
        self.assertTrue(preview.truncated)
        self.assertEqual(preview.limit_bytes, DEFAULT_PREVIEW_BYTES)
        full = self.service.document("specs/demo/spec.md", full=True)
        self.assertTrue(full.markdown)
        self.assertFalse(full.truncated)

    def test_binary_file_reports_metadata(self):
        (self.feature / "blob.bin").write_bytes(b"\x00\x01\x02binary")
        document = self.service.document("specs/demo/blob.bin")
        self.assertTrue(document.binary)
        self.assertIn("Binary", document.note)
        self.assertEqual(document.text, "")

    def test_large_file_is_bounded_then_full(self):
        big = "line\n" * (DEFAULT_PREVIEW_BYTES // 4)
        (self.feature / "big.txt").write_text(big, encoding="utf-8")
        preview = self.service.document("specs/demo/big.txt")
        self.assertTrue(preview.truncated)
        self.assertEqual(preview.limit_bytes, DEFAULT_PREVIEW_BYTES)
        full = self.service.document("specs/demo/big.txt", full=True)
        self.assertFalse(full.truncated)

    def test_missing_file_is_reported(self):
        document = self.service.document("specs/demo/absent.md")
        self.assertTrue(document.error)

    def test_path_traversal_is_rejected(self):
        self.assertIsNone(self.service.resolve_path("../outside.txt"))
        self.assertIsNone(self.service.resolve_path("/etc/passwd"))
        self.assertIsNotNone(self.service.resolve_path("specs/demo/spec.md"))


if __name__ == "__main__":
    unittest.main()
