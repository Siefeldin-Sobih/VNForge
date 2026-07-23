"""Structural checkers for generated Ren'Py and project flag names.

These helpers power offline tester assertions. They inspect text and project
data only — they never call a language-model provider.
"""

from __future__ import annotations

import re
from collections import defaultdict

from core.schemas import VNProject

DEFAULT_BOOL_RE = re.compile(
    r"(?m)^default\s+([A-Za-z][A-Za-z0-9_]*)\s*=\s*(True|False)\s*$"
)
LABEL_RE = re.compile(r"(?m)^label\s+([A-Za-z][A-Za-z0-9_]*):")
JUMP_RE = re.compile(r"(?m)^\s+jump\s+([A-Za-z][A-Za-z0-9_]*)\s*$")

_SUFFIXES = ("ing", "ed", "es", "s")


def boolean_defaults(script: str) -> list[tuple[str, bool]]:
    """Return ``(name, value)`` pairs for every boolean ``default`` line."""
    return [(name, value == "True") for name, value in DEFAULT_BOOL_RE.findall(script)]


def labels_and_jumps(script: str) -> tuple[set[str], set[str]]:
    """Return the set of defined labels and jump targets in Ren'Py source."""
    return set(LABEL_RE.findall(script)), set(JUMP_RE.findall(script))


def unresolved_jumps(script: str) -> set[str]:
    """Return jump targets that do not resolve to any label in ``script``."""
    labels, jumps = labels_and_jumps(script)
    return jumps - labels


def _normalize_token(token: str) -> str:
    """Strip common English suffixes so mild form variants share a stem."""
    lowered = token.lower()
    for suffix in _SUFFIXES:
        if len(lowered) > len(suffix) + 2 and lowered.endswith(suffix):
            return lowered[: -len(suffix)]
    return lowered


def flag_signature(name: str) -> frozenset[str]:
    """Return an order-insensitive token signature for a flag identifier."""
    tokens = [part for part in name.lower().split("_") if part]
    return frozenset(_normalize_token(token) for token in tokens)


def project_flag_names(project: VNProject) -> set[str]:
    """Collect every state-change flag name used across the project."""
    names: set[str] = set()
    for scene in project.scenes:
        for choice in scene.plan.choices:
            for change in choice.state_changes:
                names.add(change.name)
    return names


def near_duplicate_flag_groups(project: VNProject) -> list[list[str]]:
    """Group flag names that look like the same concept under different spellings.

    Matching is intentionally approximate: same stem tokens in any order
    (``examined_latch`` vs ``latch_examined``) count as near-duplicates.
    """
    groups: dict[frozenset[str], set[str]] = defaultdict(set)
    for name in project_flag_names(project):
        signature = flag_signature(name)
        if signature:
            groups[signature].add(name)
    return [sorted(names) for names in groups.values() if len(names) > 1]
