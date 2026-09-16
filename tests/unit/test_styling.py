"""Unit tests for the S07 styling domain: discovery, validation, resolution."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from workflow_cockpit.styling import (
    DEFAULT_ACCENTS,
    NEUTRAL_TOKENS,
    REQUIRED_TOKENS,
    ResolvedStyle,
    TemplateRepository,
    default_template,
    normalize_name,
    resolve_style,
    sanitize_display_name,
    validate_template,
)
from workflow_cockpit.styling.tokens import TemplateValidationError


def template_data(name: str, **overrides) -> dict:
    tokens = dict(NEUTRAL_TOKENS)
    tokens.update(overrides.pop("tokens", {}))
    data = {"name": name, "label": overrides.pop("label", name.title()), "tokens": tokens}
    data.update(overrides)
    return data


def write_template(directory: Path, filename: str, data: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def project_with(integration: str | None) -> Path:
    """A throwaway project; a leading ``{`` is written as a raw malformed file."""
    project = Path(tempfile.mkdtemp())
    specify = project / ".specify"
    specify.mkdir(parents=True, exist_ok=True)
    if integration is None:
        return project
    if integration.startswith("{"):
        (specify / "integration.json").write_text(integration, encoding="utf-8")
    else:
        (specify / "integration.json").write_text(
            json.dumps({"default_integration": integration}), encoding="utf-8"
        )
    return project


class ShippedTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = TemplateRepository.load()
        self.templates = self.repository.templates

    def test_all_shipped_templates_define_required_tokens(self):
        self.assertGreaterEqual(len(self.templates), 4)
        for template in self.templates:
            with self.subTest(template=template.name):
                self.assertEqual(set(REQUIRED_TOKENS) - set(template.tokens), set())

    def test_expected_agent_templates_and_aliases_resolve(self):
        expected = {
            "opencode": ("opencode",),
            "github-copilot": ("github copilot", "copilot", "github-copilot"),
            "claude": ("claude", "claude code"),
        }
        for canonical, aliases in expected.items():
            with self.subTest(name=canonical):
                self.assertEqual(self.repository.resolve(canonical).name, canonical)
                for alias in aliases:
                    self.assertEqual(self.repository.resolve(alias).name, canonical)
        self.assertEqual(self.repository.resolve("cockpit").name, "cockpit")

    def test_neutral_template_matches_documented_baseline(self):
        cockpit = self.repository.resolve("cockpit")
        self.assertEqual(cockpit.tokens, NEUTRAL_TOKENS)
        self.assertEqual(cockpit.accents, DEFAULT_ACCENTS)
        self.assertEqual(default_template().tokens, NEUTRAL_TOKENS)


class ValidationTests(unittest.TestCase):
    def test_missing_required_tokens_names_each_one(self):
        data = template_data("incomplete")
        del data["tokens"]["paper"]
        del data["tokens"]["fault"]
        with self.assertRaises(TemplateValidationError) as caught:
            validate_template(data)
        self.assertEqual(caught.exception.name, "incomplete")
        self.assertEqual(set(caught.exception.missing), {"paper", "fault"})

    def test_extra_tokens_are_accepted(self):
        data = template_data("extra")
        data["tokens"]["brand"] = "#123456"
        template = validate_template(data)
        self.assertEqual(template.tokens["brand"] if "brand" in template.tokens else None, None)
        self.assertEqual(set(template.tokens), set(REQUIRED_TOKENS))

    def test_non_color_token_is_rejected(self):
        data = template_data("badcolor")
        data["tokens"]["signal"] = "not-a-color"
        with self.assertRaises(TemplateValidationError) as caught:
            validate_template(data)
        self.assertIn("signal", caught.exception.missing)

    def test_missing_name_is_rejected(self):
        with self.assertRaises(TemplateValidationError):
            validate_template({"tokens": dict(NEUTRAL_TOKENS)})


class DiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        self.local = self.project / ".specify" / "cockpit" / "templates"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_project_local_template_is_discovered_without_code(self):
        write_template(self.local, "custom.json", template_data("custom", tokens={"paper": "#FFFFFF"}))
        repository = TemplateRepository.load(self.project)
        self.assertEqual(repository.resolve("custom").name, "custom")

    def test_project_local_template_selected_by_override(self):
        write_template(self.local, "custom.json", template_data("custom", label="Custom"))
        resolved = resolve_style(self.project, override="custom")
        self.assertEqual((resolved.name, resolved.source), ("custom", "override"))
        self.assertFalse(resolved.is_fallback)

    def test_builtin_wins_on_name_collision(self):
        shipped_ink = TemplateRepository.load().resolve("opencode").tokens["ink"]
        write_template(self.local, "opencode.json", template_data("opencode", tokens={"ink": "#000000"}))
        repository = TemplateRepository.load(self.project)
        self.assertEqual(repository.resolve("opencode").tokens["ink"], shipped_ink)

    def test_first_sorted_project_filename_wins(self):
        write_template(self.local, "b.json", template_data("dup", tokens={"ink": "#111111"}))
        write_template(self.local, "a.json", template_data("dup", tokens={"ink": "#222222"}))
        repository = TemplateRepository.load(self.project)
        self.assertEqual(repository.resolve("dup").tokens["ink"], "#222222")

    def test_cockpit_cannot_be_shadowed(self):
        write_template(self.local, "cockpit.json", template_data("cockpit", tokens={"ink": "#000000"}))
        repository = TemplateRepository.load(self.project)
        self.assertEqual(repository.resolve("cockpit").tokens["ink"], NEUTRAL_TOKENS["ink"])

    def test_invalid_json_falls_back_and_logs(self):
        self.local.mkdir(parents=True, exist_ok=True)
        (self.local / "broken.json").write_text("{not json", encoding="utf-8")
        with self.assertLogs("workflow_cockpit.styling.loader", level="WARNING"):
            repository = TemplateRepository.load(self.project)
        self.assertEqual(repository.default_style().name, "cockpit")
        self.assertIsNone(repository.resolve("broken"))

    def test_unreadable_definition_falls_back_and_logs(self):
        self.local.mkdir(parents=True, exist_ok=True)
        (self.local / "unreadable.json").mkdir()
        with self.assertLogs("workflow_cockpit.styling.loader", level="WARNING"):
            repository = TemplateRepository.load(self.project)
        self.assertEqual(repository.default_style().name, "cockpit")

    def test_invalid_definition_is_rejected_with_missing_tokens_logged(self):
        data = template_data("partial")
        del data["tokens"]["cold"]
        write_template(self.local, "partial.json", data)
        with self.assertLogs("workflow_cockpit.styling.loader", level="WARNING") as logs:
            repository = TemplateRepository.load(self.project)
        self.assertIsNone(repository.resolve("partial"))
        self.assertIn("cold", "\n".join(logs.output))


class ResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".specify").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _declare(self, value: str | None) -> None:
        payload = {} if value is None else {"default_integration": value}
        (self.project / ".specify" / "integration.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_integration_selects_matching_template(self):
        self._declare("opencode")
        resolved = resolve_style(self.project)
        self.assertIsInstance(resolved, ResolvedStyle)
        self.assertEqual((resolved.name, resolved.source), ("opencode", "integration"))
        self.assertFalse(resolved.is_fallback)

    def test_override_wins_over_integration(self):
        self._declare("claude")
        resolved = resolve_style(self.project, override="opencode")
        self.assertEqual((resolved.name, resolved.source, resolved.requested), ("opencode", "override", "opencode"))

    def test_unknown_integration_falls_back_with_notice(self):
        self._declare("mystery")
        with self.assertLogs("workflow_cockpit.styling.resolver", level="WARNING"):
            resolved = resolve_style(self.project)
        self.assertEqual(resolved.name, "cockpit")
        self.assertTrue(resolved.is_fallback)
        self.assertIn("mystery", resolved.notice)
        self.assertIn("cockpit", resolved.notice)

    def test_unknown_override_falls_back_with_notice(self):
        with self.assertLogs("workflow_cockpit.styling.resolver", level="WARNING"):
            resolved = resolve_style(self.project, override="nope")
        self.assertEqual(resolved.name, "cockpit")
        self.assertIn("nope", resolved.notice)

    def test_missing_integration_file_falls_back(self):
        with self.assertLogs("workflow_cockpit.styling.resolver", level="WARNING"):
            resolved = resolve_style(self.project)
        self.assertEqual(resolved.name, "cockpit")
        self.assertTrue(resolved.is_fallback)

    def test_malformed_integration_file_falls_back(self):
        (self.project / ".specify" / "integration.json").write_text("}{", encoding="utf-8")
        with self.assertLogs("workflow_cockpit.styling.resolver", level="WARNING"):
            resolved = resolve_style(self.project)
        self.assertEqual(resolved.name, "cockpit")
        self.assertTrue(resolved.is_fallback)

    def test_absent_default_integration_falls_back(self):
        self._declare(None)
        with self.assertLogs("workflow_cockpit.styling.resolver", level="WARNING"):
            resolved = resolve_style(self.project)
        self.assertEqual(resolved.name, "cockpit")
        self.assertTrue(resolved.is_fallback)

    def test_no_project_yields_neutral_without_notice(self):
        resolved = resolve_style()
        self.assertEqual(resolved.name, "cockpit")
        self.assertFalse(resolved.is_fallback)

    def test_bad_style_fixtures_never_block_and_always_target_cockpit(self):
        cases: list[tuple[str, Path | None]] = []
        cases.append(("matching integration", project_with("opencode")))
        cases.append(("unknown integration", project_with("plain-integration")))
        cases.append(("missing file", project_with(None)))
        cases.append(("malformed file", project_with("{not json")))
        for label, project in cases:
            with self.subTest(case=label):
                resolved = resolve_style(project)  # must never raise
                self.assertIsNotNone(resolved.template)
                if resolved.is_fallback:
                    self.assertEqual(resolved.name, "cockpit")


class NameTests(unittest.TestCase):
    def test_normalization_collapses_case_and_separators(self):
        self.assertEqual(normalize_name("GitHub Copilot"), "github copilot")
        self.assertEqual(normalize_name("github-copilot"), "github copilot")
        self.assertEqual(normalize_name("  GitHub_Copilot  "), "github copilot")

    def test_sanitize_strips_control_chars_and_collapses_space(self):
        self.assertEqual(sanitize_display_name("  Hello\n\tWorld  "), "Hello World")

    def test_sanitize_middle_truncates_long_names(self):
        value = sanitize_display_name("A" * 80)
        self.assertLessEqual(len(value), 32)
        self.assertIn("…", value)

    def test_sanitize_handles_empty(self):
        self.assertEqual(sanitize_display_name(None), "")


class LaunchOptionTests(unittest.TestCase):
    def test_style_option_is_parsed(self):
        from workflow_cockpit.cli import build_parser

        self.assertEqual(build_parser().parse_args(["--style", "claude"]).style, "claude")
        self.assertIsNone(build_parser().parse_args([]).style)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
