"""Structure tests for the arc42 documentation set."""

from __future__ import annotations

import os
import unittest

from tests.docs.support import ARCH_DIR, ARCH_INDEX, SECTIONS, TIER3, read


class StructureTests(unittest.TestCase):
    def test_all_twelve_sections_present(self):
        self.assertEqual([section.number for section in SECTIONS], list(range(1, 13)))

    def test_section_files_exist(self):
        for section in SECTIONS:
            self.assertTrue(section.path.is_file(), f"missing {section.path}")

    def test_section_files_declare_number_and_tier(self):
        for section in SECTIONS:
            text = read(section.path)
            first_line = text.splitlines()[0]
            self.assertEqual(first_line, f"# {section.number}. {section.title}", section.path.name)
            self.assertIn(f"| arc42 | {section.number}. {section.title} |", text, section.path.name)
            self.assertIn(f"| Tier | {section.tier} |", text, section.path.name)

    def test_section_files_contain_promised_headings(self):
        for section in SECTIONS:
            text = read(section.path)
            for heading in section.headings:
                self.assertIn(f"## {heading}", text, f"{section.path.name}: {heading}")

    def test_architecture_filenames_are_numbered(self):
        for section in SECTIONS:
            if section.number == 12:
                continue
            self.assertEqual(section.path.parent, ARCH_DIR)
            self.assertTrue(section.path.name.startswith(f"{section.number:02d}-"), section.path.name)

    def test_tier3_sections_are_reference_only(self):
        self.assertEqual({section.number for section in TIER3}, {4, 10, 11, 12})

    def test_index_links_every_section(self):
        index = read(ARCH_INDEX)
        for section in SECTIONS:
            relative = os.path.relpath(section.path, ARCH_DIR).replace(os.sep, "/")
            self.assertIn(f"]({relative})", index, f"index does not link {section.path.name}")

    def test_index_table_has_expected_columns(self):
        index = read(ARCH_INDEX)
        self.assertIn("| Section | File | Load when |", index)

    def test_index_declares_reference_sections(self):
        index = read(ARCH_INDEX)
        self.assertIn("§4", index)
        self.assertIn("§10", index)
        self.assertIn("§11", index)


if __name__ == "__main__":
    unittest.main()
