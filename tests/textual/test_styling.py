"""Textual tests for applied styling, visible name, and cross-template equality."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from textual.app import App

from tests.support import STYLES, FakeSession
from workflow_cockpit.styling import TemplateRepository, resolve_style
from workflow_cockpit.styling.tokens import REQUIRED_TOKENS
from workflow_cockpit.ui.palette import palette
from workflow_cockpit.ui.screens.cockpit import CockpitScreen
from workflow_cockpit.ui.screens.launch import LaunchScreen
from workflow_cockpit.ui.theme import active_style, install_style
from workflow_cockpit.ui.view_model import STATUS_GRAMMAR, state_grammar


class StyleApp(App):
    """Minimal app that installs a resolved style before mounting screens."""

    CSS_PATH = str(STYLES)

    def __init__(self, resolved, **kwargs) -> None:
        super().__init__(**kwargs)
        install_style(self, resolved)


def project_with_integration(value: str | None, *, malformed: bool = False) -> Path:
    directory = Path(tempfile.mkdtemp())
    specify = directory / ".specify"
    specify.mkdir(parents=True, exist_ok=True)
    if malformed:
        (specify / "integration.json").write_text("{not json", encoding="utf-8")
    elif value is not None:
        (specify / "integration.json").write_text(json.dumps({"default_integration": value}), encoding="utf-8")
    return directory


class AppliedStyleTests(unittest.IsolatedAsyncioTestCase):
    async def _with_cockpit(self, resolved, check):
        app = StyleApp(resolved)
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(CockpitScreen(FakeSession(status="running")))
            await pilot.pause()
            check(app)

    async def test_integration_template_tokens_are_applied(self):
        project = project_with_integration("opencode")
        resolved = resolve_style(project)
        template = resolved.template

        def check(app):
            variables = app.get_css_variables()
            for token in REQUIRED_TOKENS:
                with self.subTest(token=token):
                    self.assertEqual(variables[token], template.tokens[token])
                    self.assertEqual(getattr(palette, token), template.tokens[token])
            self.assertEqual(active_style().name, "opencode")

        await self._with_cockpit(resolved, check)

    async def test_resolved_name_is_visible(self):
        resolved = resolve_style(project_with_integration("claude"))

        def check(app):
            rendered = str(app.screen.query_one("#style-field").render())
            self.assertIn("STYLE", rendered)
            self.assertIn(resolved.display_name, rendered)
            self.assertNotIn("FALLBACK", rendered)

        await self._with_cockpit(resolved, check)

    async def test_unknown_integration_falls_back_with_visible_notice(self):
        resolved = resolve_style(project_with_integration("mystery"))
        self.assertTrue(resolved.is_fallback)

        def check(app):
            rendered = str(app.screen.query_one("#style-field").render())
            self.assertIn("Cockpit", rendered)
            self.assertIn("FALLBACK", rendered)
            self.assertEqual(app.get_css_variables()["ink"], resolved.template.tokens["ink"])

        await self._with_cockpit(resolved, check)

    async def test_malformed_integration_falls_back(self):
        resolved = resolve_style(project_with_integration(None, malformed=True))
        self.assertEqual(resolved.name, "cockpit")
        self.assertTrue(resolved.is_fallback)

        def check(app):
            self.assertIn("FALLBACK", str(app.screen.query_one("#style-field").render()))

        await self._with_cockpit(resolved, check)

    async def test_override_applies_named_template(self):
        resolved = resolve_style(project_with_integration("claude"), override="opencode")

        def check(app):
            self.assertEqual(app.get_css_variables()["ink"], resolved.template.tokens["ink"])
            self.assertIn("OpenCode", str(app.screen.query_one("#style-field").render()))

        await self._with_cockpit(resolved, check)

    async def test_unknown_override_shows_neutral_and_fallback(self):
        resolved = resolve_style(project_with_integration("opencode"), override="does-not-exist")
        self.assertEqual(resolved.name, "cockpit")

        def check(app):
            rendered = str(app.screen.query_one("#style-field").render())
            self.assertIn("Cockpit", rendered)
            self.assertIn("FALLBACK", rendered)

        await self._with_cockpit(resolved, check)


class ScreenStyleNoteTests(unittest.IsolatedAsyncioTestCase):
    async def test_launch_screen_shows_resolved_name(self):
        resolved = resolve_style(project_with_integration("opencode"))
        app = StyleApp(resolved)
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(LaunchScreen(FakeSession()))
            await pilot.pause()
            note = str(app.screen.query_one("#style-note").render())
            self.assertIn("OpenCode", note)
            self.assertNotIn("FALLBACK", note)

    async def test_launch_screen_shows_fallback_reason(self):
        resolved = resolve_style(project_with_integration("mystery"))
        app = StyleApp(resolved)
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(LaunchScreen(FakeSession()))
            await pilot.pause()
            note = str(app.screen.query_one("#style-note").render())
            self.assertIn("Cockpit", note)
            self.assertIn("mystery", note)


class CrossTemplateGrammarTests(unittest.TestCase):
    def test_status_grammar_is_identical_across_templates(self):
        baseline = dict(STATUS_GRAMMAR)
        for template in TemplateRepository.load().templates:
            palette.install(template)
            with self.subTest(template=template.name):
                for status in baseline:
                    self.assertEqual(state_grammar(status), baseline[status])
        palette.install(TemplateRepository.load().default_style())

    def test_every_status_has_symbol_and_word(self):
        for status, (symbol, word) in STATUS_GRAMMAR.items():
            with self.subTest(status=status):
                self.assertTrue(symbol)
                self.assertTrue(word)


@dataclass
class _FakeReport:
    project: object
    ok: bool = False
    checks: tuple = ()
    compatibility: object = None


class _FakePreflight:
    def __init__(self, root: Path) -> None:
        self._root = root

    def run(self):
        return _FakeReport(project=type("P", (), {"root": self._root})())


class EndToEndStyleTests(unittest.IsolatedAsyncioTestCase):
    """The shipped app path applies the resolved template and never blocks."""

    async def _run_app(self, resolved, check):
        from workflow_cockpit.ui.app import CockpitApp

        app = CockpitApp(
            preflight=_FakePreflight(Path("/tmp/demo")),
            session_factory=lambda result: None,
            style=resolved,
        )
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            check(app)

    async def test_cockpit_app_applies_integration_template(self):
        resolved = resolve_style(project_with_integration("opencode"))

        def check(app):
            self.assertEqual(app.get_css_variables()["ink"], resolved.template.tokens["ink"])
            self.assertIn("OpenCode", str(app.screen.query_one("#style-note").render()))

        await self._run_app(resolved, check)

    async def test_cockpit_app_launches_on_bad_style_fixture(self):
        resolved = resolve_style(project_with_integration("no-such-integration"))

        def check(app):
            self.assertEqual(app.get_css_variables()["ink"], resolved.template.tokens["ink"])
            note = str(app.screen.query_one("#style-note").render())
            self.assertIn("Cockpit", note)
            self.assertIn("no-such-integration", note)

        await self._run_app(resolved, check)


class CrossTemplateSurfaceTests(unittest.IsolatedAsyncioTestCase):
    """Only visuals may differ: plain text and controls stay identical (FR-006)."""

    async def _surface_text(self, resolved):
        app = StyleApp(resolved)
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(CockpitScreen(FakeSession(status="running")))
            await pilot.pause()
            screen = app.screen
            widgets = ["#view-label", "#overview-content", "#run-progress", "#identity"]
            return {widget: str(screen.query_one(widget).render()) for widget in widgets}

    async def test_plain_text_identical_for_every_template(self):
        project = project_with_integration("opencode")
        baseline = await self._surface_text(resolve_style(project))
        for name in ("opencode", "claude", "github-copilot"):
            resolved = resolve_style(project, override=name)
            current = await self._surface_text(resolved)
            with self.subTest(template=name):
                self.assertEqual(current, baseline)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
