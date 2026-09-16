"""Legibility checks for every shipped template (FR-011, SC-002)."""

from __future__ import annotations

import itertools
import unittest

from workflow_cockpit.styling import ACCENT_TOKENS, REQUIRED_TOKENS, TemplateRepository

#: WCAG-style minimum ratios for normal text drawn on a working surface.
TEXT_CONTRAST_MIN = 4.5
#: Minimum ratio for focus and status accents against their surfaces.
ACCENT_CONTRAST_MIN = 3.0
#: Minimum Euclidean RGB distance between the four status accents.
STATUS_DISTANCE_MIN = 40.0

_STATUS_TOKENS = ("signal", "hold", "fault", "fog")
_SURFACES = ("ink", "deck", "raised")


def _channels(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    if len(value) == 3:
        value = "".join(channel * 2 for channel in value)
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def _luminance(color: str) -> float:
    def linearize(channel: int) -> float:
        srgb = channel / 255
        return srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4

    red, green, blue = (linearize(channel) for channel in _channels(color))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: str, second: str) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def distance(first: str, second: str) -> float:
    return sum((a - b) ** 2 for a, b in zip(_channels(first), _channels(second), strict=True)) ** 0.5


class ShippedTemplateContrastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.templates = TemplateRepository.load().templates

    def test_shipped_set_is_complete(self):
        self.assertGreaterEqual(len(self.templates), 4)
        self.assertIn("cockpit", {template.name for template in self.templates})

    def test_primary_and_secondary_text_contrast_on_every_surface(self):
        for template in self.templates:
            for token in ("paper", "fog"):
                for surface in _SURFACES:
                    with self.subTest(template=template.name, token=token, surface=surface):
                        self.assertGreaterEqual(
                            contrast(template.tokens[token], template.tokens[surface]),
                            TEXT_CONTRAST_MIN,
                        )

    def test_focus_and_status_accents_contrast_on_every_surface(self):
        for template in self.templates:
            for token in ("cold", *_STATUS_TOKENS):
                for surface in _SURFACES:
                    with self.subTest(template=template.name, token=token, surface=surface):
                        self.assertGreaterEqual(
                            contrast(template.tokens[token], template.tokens[surface]),
                            ACCENT_CONTRAST_MIN,
                        )

    def test_focus_accent_contrasts_with_focus_background(self):
        for template in self.templates:
            with self.subTest(template=template.name):
                self.assertGreaterEqual(
                    contrast(template.tokens["cold"], template.accent("focus")),
                    ACCENT_CONTRAST_MIN,
                )

    def test_status_accents_are_pairwise_distinguishable(self):
        for template in self.templates:
            for first, second in itertools.combinations(_STATUS_TOKENS, 2):
                with self.subTest(template=template.name, pair=(first, second)):
                    self.assertGreaterEqual(
                        distance(template.tokens[first], template.tokens[second]),
                        STATUS_DISTANCE_MIN,
                    )

    def test_every_template_has_full_required_and_accent_set(self):
        for template in self.templates:
            with self.subTest(template=template.name):
                self.assertEqual(set(REQUIRED_TOKENS) - set(template.tokens), set())
                for accent in ACCENT_TOKENS:
                    self.assertTrue(template.accent(accent).startswith("#"))


class ContrastHelperTests(unittest.TestCase):
    def test_known_ratio_for_black_and_white(self):
        self.assertAlmostEqual(contrast("#000000", "#FFFFFF"), 21.0, places=1)

    def test_identical_color_has_unit_ratio(self):
        self.assertAlmostEqual(contrast("#123456", "#123456"), 1.0, places=5)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
