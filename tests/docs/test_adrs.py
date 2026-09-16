"""ADR integrity tests: every ADR is listed, and every listed ADR resolves."""

from __future__ import annotations

import re
import unittest

from tests.docs.support import DECISIONS_DIR, ROOT, read

ADR_INDEX = DECISIONS_DIR / "README.md"
ARCH_ADR_SECTION = ROOT / "docs" / "architecture" / "09-architecture-decisions.md"
ADR_NAME = re.compile(r"^\d{4}-[a-z0-9-]+\.md$")
ADR_LINK = re.compile(r"\]\((\d{4}-[a-z0-9-]+\.md)\)")


class AdrTests(unittest.TestCase):
    def _files(self) -> list[str]:
        return sorted(path.name for path in DECISIONS_DIR.glob("*.md") if ADR_NAME.match(path.name))

    def _listed(self) -> list[str]:
        return ADR_LINK.findall(read(ADR_INDEX))

    def test_every_adr_is_listed(self):
        self.assertEqual(self._files(), self._listed())

    def test_every_listed_adr_resolves(self):
        for name in self._listed():
            self.assertTrue((DECISIONS_DIR / name).is_file(), name)

    def test_adr_numbers_are_contiguous(self):
        numbers = [int(name[:4]) for name in self._files()]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))

    def test_adrs_record_decision_and_rejection(self):
        for name in self._files():
            text = read(DECISIONS_DIR / name)
            self.assertIn("# ", text.splitlines()[0], name)
            self.assertIn("## Decision", text, name)
            self.assertIn("## Rejected alternatives", text, name)
            self.assertIn("Status: Accepted", text, name)

    def test_architecture_section_links_every_adr(self):
        section = read(ARCH_ADR_SECTION)
        for name in self._files():
            self.assertIn(name, section, f"{name} missing from 09-architecture-decisions.md")


if __name__ == "__main__":
    unittest.main()
