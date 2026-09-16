"""Budget tests: the always-on context and the architecture index stay small."""

from __future__ import annotations

import unittest

from tests.docs.support import (
    ALWAYS_ON_LINE_CEILING,
    ALWAYS_ON_TOKEN_CEILING,
    ARCH_INDEX,
    INDEX_TOKEN_CEILING,
    ROOT,
    TIER1,
    estimated_tokens,
    read,
)

AGENTS = ROOT / "AGENTS.md"


def lines(text: str) -> int:
    return text.count("\n") + (0 if text.endswith("\n") else 1)


class BudgetTests(unittest.TestCase):
    def test_always_on_context_within_ceiling(self):
        files = [AGENTS] + [section.path for section in TIER1]
        total_lines = sum(lines(read(path)) for path in files)
        total_tokens = sum(estimated_tokens(read(path)) for path in files)
        self.assertLessEqual(total_lines, ALWAYS_ON_LINE_CEILING, f"{total_lines} lines")
        self.assertLessEqual(total_tokens, ALWAYS_ON_TOKEN_CEILING, f"~{total_tokens} tokens")

    def test_architecture_index_near_target(self):
        tokens = estimated_tokens(read(ARCH_INDEX))
        self.assertLessEqual(tokens, INDEX_TOKEN_CEILING, f"~{tokens} tokens")

    def test_agents_is_the_only_always_on_file(self):
        text = read(AGENTS)
        self.assertIn("only always-on context", text)


if __name__ == "__main__":
    unittest.main()
