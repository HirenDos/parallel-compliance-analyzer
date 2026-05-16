"""Orchestrator node: section splitting and routing metadata (no LLM)."""

from __future__ import annotations

import math
import uuid
from pathlib import Path
from typing import Any

from config.settings import ALLOWED_PROGRAM_TYPES
from schemas.models import PipelineState
from skills.section_splitter import split_sections


def _read_instructions() -> str:
    """Load orchestrator behavioral rules from INSTRUCTIONS.md.

    Returns:
        Markdown instruct text for audit context.
    """
    return (Path(__file__).resolve().parent / "INSTRUCTIONS.md").read_text(
        encoding="utf-8"
    )


def build_system_prompt(program_type: str, state: str) -> str:
    """Build a non-LLM system string for trace logging (orchestrator is deterministic).

    Args:
        program_type: Active housing program label.
        state: US state or jurisdiction code.

    Returns:
        Summary string combining program context and on-disk behavioral rules.
    """
    rules = _read_instructions()
    return """
You are the orchestrator controller (deterministic; no content analysis).
Program type: {program_type}
State: {state}

Behavioral rules (reference only; routing is implemented in Python):
{rules}
""".strip().format(program_type=program_type, state=state, rules=rules)


def _estimate_tokens_from_chars(char_count: int) -> int:
    """Approximate token count from characters using a rough 4 chars/token heuristic.

    Args:
        char_count: Section size in characters.

    Returns:
        Estimated token count (rounded up).
    """
    if char_count <= 0:
        return 0
    return int(math.ceil(char_count / 4))


def orchestrator_node(state: PipelineState) -> dict[str, Any]:
    """Split input text into sections and compute routing metadata.

    Args:
        state: Current LangGraph pipeline state with raw_text and document_metadata.

    Returns:
        State update with sections, routing_log, run_id, program_type, audit entry.
    """
    meta = dict(state.get("document_metadata") or {})
    program_type = str(meta.get("program_type") or "HUD").upper()
    if program_type not in ALLOWED_PROGRAM_TYPES:
        program_type = "HUD"
        meta["program_type"] = program_type
    us_state = str(meta.get("state") or "")
    raw_text = state.get("raw_text") or ""
    run_id = state.get("run_id") or str(uuid.uuid4())
    sections = split_sections(raw_text, program_type)
    routing_log: list[str] = []
    for key in ("income", "deadlines", "violations", "reporting"):
        body = sections.get(key, "") or ""
        est_tok = _estimate_tokens_from_chars(len(body))
        routing_log.append(
            "section={key} chars={chars} est_tokens={tok}".format(
                key=key, chars=len(body), tok=est_tok
            )
        )
        if est_tok > 8000:
            routing_log.append(
                "warning: section '{key}' may exceed 8000-token budget; splitter trimmed."
                .format(key=key)
            )
    confidence = 0.95
    if not us_state.strip():
        confidence = 0.6
        routing_log.append("uncertainty: missing jurisdiction state; defaulted routing.")
    audit_note = build_system_prompt(program_type, us_state or "UNKNOWN")
    return {
        "sections": {
            "income": sections.get("income", ""),
            "deadlines": sections.get("deadlines", ""),
            "violations": sections.get("violations", ""),
            "reporting": sections.get("reporting", ""),
        },
        "routing_log": routing_log,
        "run_id": run_id,
        "program_type": program_type,
        "confidence_in_routing": confidence,
        "document_metadata": meta,
        "audit_log": [
            {
                "ts": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
                "agent": "orchestrator",
                "confidence": confidence,
                "note": audit_note[:1200],
            }
        ],
    }


def run(state: PipelineState) -> dict[str, Any]:
    """Alias for LangGraph node entry per agent module convention.

    Args:
        state: Pipeline state.

    Returns:
        Orchestrator state update.
    """
    return orchestrator_node(state)
