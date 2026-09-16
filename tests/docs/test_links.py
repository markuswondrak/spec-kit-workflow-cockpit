"""Link tests for the architecture context and root agent guidance."""

from __future__ import annotations

import unittest
from urllib.parse import urlparse

from tests.docs.support import anchors, doc_files, links, read

EXTERNAL_SCHEMES = {"http", "https", "mailto"}


class LinkTests(unittest.TestCase):
    def test_all_relative_links_resolve(self):
        broken: list[str] = []
        for path in doc_files():
            for label, target in links(read(path)):
                parsed = urlparse(target)
                if parsed.scheme in EXTERNAL_SCHEMES:
                    continue
                target_path = target.split("#", 1)[0]
                if not target_path:
                    continue
                resolved = (path.parent / target_path).resolve()
                if not resolved.exists():
                    broken.append(f"{path.relative_to(path.parents[1])}: [{label}]({target})")
        self.assertEqual(broken, [], "broken links:\n" + "\n".join(broken))

    def test_anchors_resolve(self):
        broken: list[str] = []
        for path in doc_files():
            for label, target in links(read(path)):
                if "#" not in target:
                    continue
                parsed = urlparse(target)
                if parsed.scheme in EXTERNAL_SCHEMES:
                    continue
                target_path, anchor = target.split("#", 1)
                destination = (path.parent / target_path).resolve() if target_path else path
                if not destination.exists() or not anchor:
                    continue
                if anchor not in anchors(read(destination)):
                    broken.append(f"{path.name}: [{label}]({target})")
        self.assertEqual(broken, [], "unresolved anchors:\n" + "\n".join(broken))

    def test_root_agents_points_at_the_context_entry_points(self):
        text = read(doc_files()[0])
        self.assertIn("docs/architecture/README.md", text)
        self.assertIn("docs/decisions/README.md", text)
        self.assertIn("docs/glossary.md", text)

    def test_root_agents_carries_commands_and_goals(self):
        text = read(doc_files()[0])
        for heading in ("## Top quality goals", "## Universal rules", "## Commands"):
            self.assertIn(heading, text)


if __name__ == "__main__":
    unittest.main()
