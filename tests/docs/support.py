"""Shared paths, the section manifest, and Markdown helpers for the docs tests."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCH_DIR = ROOT / "docs" / "architecture"
DECISIONS_DIR = ROOT / "docs" / "decisions"
GLOSSARY = ROOT / "docs" / "glossary.md"
ARCH_INDEX = ARCH_DIR / "README.md"


@dataclass(frozen=True)
class Section:
    """One arc42 section and the headings the index promises for it."""

    number: int
    title: str
    path: Path
    tier: int
    headings: tuple[str, ...]


#: The twelve arc42 sections, their tier, and the headings each must contain.
SECTIONS: tuple[Section, ...] = (
    Section(1, "Introduction and Goals", ARCH_DIR / "01-introduction-and-goals.md", 1,
            ("Product promise", "Top quality goals", "Stakeholders", "Success criteria",
             "Functional requirements")),
    Section(2, "Constraints", ARCH_DIR / "02-constraints.md", 1,
            ("Technical constraints", "Organizational constraints", "Boundaries")),
    Section(3, "Context and Scope", ARCH_DIR / "03-context-and-scope.md", 2,
            ("Business context", "Technical context", "External interfaces", "Engine contract")),
    Section(4, "Solution Strategy", ARCH_DIR / "04-solution-strategy.md", 3,
            ("Architectural principles", "Technology decisions", "Quality tactics")),
    Section(5, "Building Block View", ARCH_DIR / "05-building-block-view.md", 2,
            ("Level 1: process", "Bootstrap and environment", "Engine boundary",
             "Read model and domain services", "Coordination", "Presentation",
             "Styling and shipped artifact")),
    Section(6, "Runtime View", ARCH_DIR / "06-runtime-view.md", 2,
            ("Launch and start", "Observe", "Gate decision", "Abort and lifecycle",
             "Process and state reconciliation", "Dogfooding workflow")),
    Section(7, "Deployment View", ARCH_DIR / "07-deployment-view.md", 2,
            ("Distribution", "Project layout", "CI and platforms")),
    Section(8, "Crosscutting Concepts", ARCH_DIR / "08-crosscutting-concepts.md", 2,
            ("Services without Textual imports", "Render-path isolation", "Bounded reads",
             "Immutable snapshots", "Output normalization", "Tolerance and recovery",
             "Theme and palette", "Accessibility", "Testing seams")),
    Section(9, "Architecture Decisions", ARCH_DIR / "09-architecture-decisions.md", 2,
            ("Decision log", "How to add an ADR")),
    Section(10, "Quality Requirements", ARCH_DIR / "10-quality-requirements.md", 3,
            ("Quality tree", "Quality scenarios", "Verification")),
    Section(11, "AI Debt Register", ARCH_DIR / "11-ai-debt-register.md", 3,
            ("Entry format", "Known debt")),
    Section(12, "Glossary", GLOSSARY, 3, ("Terms", "Naming rules")),
)

TIER1 = tuple(section for section in SECTIONS if section.tier == 1)
TIER3 = tuple(section for section in SECTIONS if section.tier == 3)

#: Estimated-token ceiling for the always-on context (AGENTS.md plus Tier 1).
ALWAYS_ON_TOKEN_CEILING = 3200
#: Line ceiling for the always-on context.
ALWAYS_ON_LINE_CEILING = 240
#: Estimated-token ceiling for the architecture index (target: roughly 200).
INDEX_TOKEN_CEILING = 400

_MD_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
_IMAGE_EMBED = re.compile(r"!\[[^\]]*\]\(")
_FENCE = re.compile(r"^```\s*([^\s`]*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico")
_DIAGRAM_LANGS = {"plantuml", "puml", "dot", "graphviz"}
_MERMAID_STARTS = (
    "flowchart", "graph", "sequencediagram", "statediagram", "classdiagram", "erdiagram",
    "mindmap", "journey", "gantt", "pie", "gitgraph", "c4context", "quadrantchart",
    "xychart", "block", "requirementdiagram",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def estimated_tokens(text: str) -> int:
    """A dependency-free token estimate: one token per four characters."""
    return math.ceil(len(text) / 4)


def slugify(heading: str) -> str:
    """GitHub-style heading anchor used by the link test."""
    text = heading.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_]+", "-", text).strip("-")


def headings(text: str) -> set[str]:
    return {match.group(2) for match in _HEADING.finditer(text)}


def anchors(text: str) -> set[str]:
    return {slugify(match.group(2)) for match in _HEADING.finditer(text)}


def links(text: str) -> list[tuple[str, str]]:
    """Return ``(label, target)`` for every non-image Markdown link."""
    return [(match.group(1), match.group(2)) for match in _MD_LINK.finditer(text)]


def fenced_blocks(text: str) -> list[tuple[str, str]]:
    """Return ``(info, body)`` for every fenced code block."""

    blocks: list[tuple[str, str]] = []
    info: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        if info is None:
            match = _FENCE.match(line)
            if match is not None:
                info = match.group(1)
                body = []
            continue
        if _FENCE.match(line) is not None:
            blocks.append((info, "\n".join(body)))
            info = None
            continue
        body.append(line)
    return blocks


def doc_files() -> list[Path]:
    """Every Markdown file owned by the architecture context."""
    files = [ROOT / "AGENTS.md", ROOT / "tests" / "AGENTS.md", ARCH_INDEX, GLOSSARY]
    files += sorted(ARCH_DIR.glob("*.md"))
    files += sorted(DECISIONS_DIR.glob("*.md"))
    files += [ROOT / "workflow_ui" / "prototype" / "AGENTS.md"]
    return [path for path in dict.fromkeys(files) if path.exists()]
