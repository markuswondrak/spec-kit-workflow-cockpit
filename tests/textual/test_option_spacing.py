"""Reproduces workflow-card spacing in the launch picker.

Textual's OptionList measures option height from the option text alone and
ignores vertical component padding. This test pins the spacing that every
workflow card must have: one blank line above the title, one blank line below
the last content line, and the full card body (including "Enter to configure")
visible within its region.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from textual.widgets import OptionList

from tests.support import FakeSession, StyledApp
from workflow_cockpit.ui.screens.launch import LaunchScreen

LONG_DESCRIPTION = (
    "The Bugfix Flow: TDD bugfix with QA review. Runs root-cause analysis, a RED test, a "
    "GREEN fix, a QA review loop, and issue-to-PR automation. When started from a GitHub "
    "issue, automatically creates a fix branch, cleans up temporary files, and opens a PR."
)


@dataclass
class Entry:
    id: str
    name: str
    version: str = "1.0.0"
    description: str = LONG_DESCRIPTION
    source: str = ""
    enabled: bool = True
    raw: dict | None = None


class LongDescriptionSession(FakeSession):
    """Three workflows with descriptions long enough to wrap."""

    def list_workflows(self):
        return tuple(
            Entry(id=f"flow-{index}", name=f"Spec-Kit Extended Flow - Flow {index}")
            for index in (1, 2, 3)
        )


class WorkflowCardSpacingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = StyledApp()

    async def _render_cards(self) -> list[list[str]]:
        session = LongDescriptionSession()
        async with self.app.run_test(size=(110, 60)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            listing = screen.query_one("#workflows", OptionList)
            cache = listing._line_cache
            return [
                [
                    listing.render_line(y).text
                    for y in range(cache.index_to_line[index], cache.index_to_line[index] + cache.heights[index])
                ]
                for index in range(len(listing.options))
            ]

    async def test_cards_have_leading_and_trailing_space(self):
        cards = await self._render_cards()
        self.assertEqual(len(cards), 3)
        for index, region in enumerate(cards):
            self.assertEqual(region[0].strip(), "", f"card {index} is missing its leading blank line")
            self.assertEqual(region[-1].strip(), "", f"card {index} is missing its trailing blank line")

    async def test_cards_show_full_body(self):
        cards = await self._render_cards()
        for index, region in enumerate(cards):
            body = "\n".join(region)
            self.assertIn("Enter to configure", body, f"card {index} is clipped before its final line")


if __name__ == "__main__":
    unittest.main()
