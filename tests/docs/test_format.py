"""Format tests: no image embeds, and diagrams are Mermaid fenced blocks."""

from __future__ import annotations

import unittest

from tests.docs.support import (
    _DIAGRAM_LANGS,
    _IMAGE_EMBED,
    _IMAGE_EXT,
    _MERMAID_STARTS,
    ARCH_DIR,
    doc_files,
    fenced_blocks,
    links,
    read,
)


class FormatTests(unittest.TestCase):
    def test_no_image_embeds(self):
        offenders: list[str] = []
        for path in doc_files():
            text = read(path)
            if _IMAGE_EMBED.search(text) or "<img" in text:
                offenders.append(path.name)
        self.assertEqual(offenders, [], f"image embeds in: {offenders}")

    def test_no_image_link_targets(self):
        offenders: list[str] = []
        for path in doc_files():
            for label, target in links(read(path)):
                if target.lower().split("#", 1)[0].endswith(_IMAGE_EXT):
                    offenders.append(f"{path.name}: [{label}]({target})")
        self.assertEqual(offenders, [], "image links:\n" + "\n".join(offenders))

    def test_no_non_mermaid_diagram_fences(self):
        offenders: list[str] = []
        for path in doc_files():
            for info, _body in fenced_blocks(read(path)):
                if info.lower() in _DIAGRAM_LANGS:
                    offenders.append(f"{path.name}: ```{info}")
        self.assertEqual(offenders, [], "non-mermaid diagram fences:\n" + "\n".join(offenders))

    def test_mermaid_blocks_are_well_formed(self):
        found = 0
        for path in doc_files():
            for info, body in fenced_blocks(read(path)):
                if info.lower() != "mermaid":
                    continue
                found += 1
                lines = [line for line in body.splitlines() if line.strip()]
                self.assertTrue(lines, f"{path.name}: empty mermaid block")
                self.assertTrue(
                    lines[0].strip().lower().startswith(_MERMAID_STARTS),
                    f"{path.name}: unrecognized mermaid start: {lines[0]!r}",
                )
        self.assertGreater(found, 0, "expected Mermaid diagrams in the architecture set")

    def test_architecture_uses_mermaid_for_structure_diagrams(self):
        architecture = [path for path in doc_files() if path.parent == ARCH_DIR]
        mermaid = sum(
            1
            for path in architecture
            for info, _body in fenced_blocks(read(path))
            if info.lower() == "mermaid"
        )
        self.assertGreaterEqual(mermaid, 5)


if __name__ == "__main__":
    unittest.main()
