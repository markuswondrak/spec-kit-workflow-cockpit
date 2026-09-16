"""Verified per-version interactive-prompt contract for non-verdict gates.

The contract is the single source of truth for prompt readiness and the
choice-to-input mapping. Versions are matched by exact identity (including
prerelease, postrelease, and local segments); a version without a recorded
contract is unsupported and interactive submission is never guessed for it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version

TERMINATOR = b"\n"

#: Control characters (C0 except nothing useful, DEL, and C1) that would let a
#: value-mapped option corrupt the prompt line.
_UNSAFE_CONTROL = frozenset(chr(code) for code in range(0x20)) | {chr(0x7F)}


@dataclass(frozen=True)
class PromptContract:
    """Recorded behavior of one ``specify`` release's interactive gate prompt."""

    release: tuple[int, int, int]
    readiness: str
    strategy: str
    terminator: bytes = TERMINATOR
    prompt_library: str = "builtin input()"

    def map_choice(
        self, choice: str, options: Iterable[str]
    ) -> tuple[bytes | None, str | None]:
        """Map one declared choice to exactly one prompt input.

        Returns ``(input_bytes, None)`` on success or ``(None, reason)`` when
        the mapping is ambiguous, unknown, or unsupported. The ``index``
        strategy emits only ASCII digits plus the terminator, so an option
        label can never inject content into the prompt.
        """
        declared = tuple(str(option) for option in options)
        if not declared:
            return None, "The gate declares no options."
        if len({option.lower() for option in declared}) != len(declared):
            return None, "The declared options are ambiguous when matched case-insensitively."
        if choice not in declared:
            return None, "The chosen option is not one of the declared options."
        if self.strategy == "value":
            if any(character in _UNSAFE_CONTROL for character in choice):
                return None, "The chosen option contains control characters and cannot be written safely."
            payload = choice.encode("utf-8")
        elif self.strategy == "index":
            payload = str(declared.index(choice) + 1).encode("ascii")
        else:
            return None, "The prompt mapping strategy is not supported."
        return payload + self.terminator, None


#: Verified contracts keyed by exact ``packaging.Version`` identity. The dev
#: and released ``1.0.6`` builds were both confirmed against the interactive
#: prompt (see ``docs/architecture/03-context-and-scope.md``, Engine contract). Index mapping
#: is recorded because the engine accepts a 1-based decimal index and it emits
#: only ASCII digits, so an option label can never be injected.
_SUPPORTED: dict[Version, PromptContract] = {
    Version("1.0.6"): PromptContract(
        release=(1, 0, 6),
        readiness=(
            "A live supervised run whose persisted state is running at a declared "
            "non-verdict gate is deterministically waiting at the interactive prompt."
        ),
        strategy="index",
        terminator=TERMINATOR,
        prompt_library="builtin input()",
    ),
    Version("1.0.6.dev0"): PromptContract(
        release=(1, 0, 6),
        readiness=(
            "A live supervised run whose persisted state is running at a declared "
            "non-verdict gate is deterministically waiting at the interactive prompt."
        ),
        strategy="index",
        terminator=TERMINATOR,
        prompt_library="builtin input()",
    ),
}


def _parse(version: object) -> Version | None:
    try:
        return version if isinstance(version, Version) else Version(str(version))
    except (InvalidVersion, TypeError):
        return None


def resolve_contract(version: object) -> PromptContract | None:
    """Return the verified contract for ``version``, or ``None`` if unverified.

    Matching is exact: a different prerelease, postrelease, local segment, or
    release is a different, unverified engine and must never inherit a
    recorded contract.
    """
    parsed = _parse(version)
    if parsed is None:
        return None
    return _SUPPORTED.get(parsed)


def verified_releases() -> tuple[Version, ...]:
    return tuple(sorted(_SUPPORTED, key=str))
