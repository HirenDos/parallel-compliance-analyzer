"""Split long regulatory text into thematic sections for parallel agents."""

from __future__ import annotations

import re
from collections import defaultdict

from config.settings import ORCHESTRATOR_MAX_SECTION_CHARS

_INCOME_KW = [
    "income limit",
    "ami",
    "area median",
    "household income",
    "gross income",
]
_DEADLINE_KW = [
    "recertification",
    "annual",
    "notice",
    "within days",
    "submission deadline",
]
_VIOLATION_KW = [
    "non-compliance",
    "penalty",
    "termination",
    "eviction",
    "audit",
    "finding",
]
_REPORTING_KW = [
    "form",
    "submit",
    "hud-",
    "report to",
    "annual report",
    "required documentation",
]


def _normalize_para(paragraph: str) -> str:
    """Collapse internal whitespace for keyword matching.

    Args:
        paragraph: Raw paragraph text.

    Returns:
        Normalized single-line text.
    """
    return re.sub(r"\s+", " ", paragraph).strip().lower()


def _keyword_hits(text_lower: str, keywords: list[str]) -> bool:
    """Return True if any keyword appears in text (case-insensitive for ASCII).

    Args:
        text_lower: Lowercased paragraph.
        keywords: Keywords to search.

    Returns:
        Whether any keyword matched.
    """
    for kw in keywords:
        if kw.lower() in text_lower:
            return True
    return False


def _assign_themes(paragraph: str) -> list[str]:
    """Map a paragraph to one or more section themes.

    Args:
        paragraph: Paragraph text.

    Returns:
        List of theme keys; duplicates allowed logic handled by caller.
    """
    tl = _normalize_para(paragraph)
    themes: list[str] = []
    if _keyword_hits(tl, _INCOME_KW):
        themes.append("income")
    if _keyword_hits(tl, _DEADLINE_KW):
        themes.append("deadlines")
    if _keyword_hits(tl, _VIOLATION_KW):
        themes.append("violations")
    if _keyword_hits(tl, _REPORTING_KW):
        themes.append("reporting")
    return themes


def _chunk_oversized(section_text: str, max_chars: int) -> str:
    """Trim or split oversized sections at paragraph boundaries.

    Args:
        section_text: Combined section body.
        max_chars: Maximum characters allowed.

    Returns:
        Possibly truncated section text within max_chars.
    """
    if len(section_text) <= max_chars:
        return section_text
    parts = section_text.split("\n\n")
    out: list[str] = []
    size = 0
    for part in parts:
        sep_len = 2 if out else 0
        if size + sep_len + len(part) > max_chars:
            break
        out.append(part)
        size += sep_len + len(part)
    if not out:
        return section_text[:max_chars]
    return "\n\n".join(out)


def split_sections(text: str, program_type: str) -> dict[str, str]:
    """Split regulatory document text into four thematic sections.

    Paragraphs that match multiple themes are duplicated into each bucket per
    product rules. If no headers/themes match, all text is returned under
    ``general`` and also copied into the four standard keys where applicable.

    Args:
        text: Full document text.
        program_type: Program label (passed through for future tuning).

    Returns:
        dict with keys income, deadlines, violations, reporting (and optionally
        general), each a string section body.
    """
    _ = program_type
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    buckets: dict[str, list[str]] = defaultdict(list)
    if not paragraphs:
        return {
            "income": "",
            "deadlines": "",
            "violations": "",
            "reporting": "",
            "general": "",
        }

    for para in paragraphs:
        themes = _assign_themes(para)
        if not themes:
            buckets["general"].append(para)
            continue
        for th in themes:
            buckets[th].append(para)

    if buckets["general"] and not any(
        k in buckets for k in ("income", "deadlines", "violations", "reporting")
    ):
        blob = "\n\n".join(buckets["general"])
        for key in ("income", "deadlines", "violations", "reporting"):
            buckets[key].append(blob)

    def _join(key: str) -> str:
        return "\n\n".join(buckets.get(key, []))

    sections = {
        "income": _chunk_oversized(_join("income"), ORCHESTRATOR_MAX_SECTION_CHARS),
        "deadlines": _chunk_oversized(
            _join("deadlines"), ORCHESTRATOR_MAX_SECTION_CHARS
        ),
        "violations": _chunk_oversized(
            _join("violations"), ORCHESTRATOR_MAX_SECTION_CHARS
        ),
        "reporting": _chunk_oversized(
            _join("reporting"), ORCHESTRATOR_MAX_SECTION_CHARS
        ),
    }
    if buckets["general"]:
        sections["general"] = _chunk_oversized(
            _join("general"), ORCHESTRATOR_MAX_SECTION_CHARS
        )
    return sections
