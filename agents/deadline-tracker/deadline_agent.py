"""Deadline tracking specialist agent node (LangGraph + Claude)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic

from agents.claude_client import call_claude_json
from config.settings import HUMAN_REVIEW_CONFIDENCE_THRESHOLD
from schemas.models import DeadlineFindings, PipelineState


def _read_instructions() -> str:
    """Load behavioral rules from INSTRUCTIONS.md.

    Returns:
        Markdown instructions text.
    """
    return (Path(__file__).resolve().parent / "INSTRUCTIONS.md").read_text(
        encoding="utf-8"
    )


def build_system_prompt(program_type: str, state: str) -> str:
    """Construct the system prompt for deadline extraction.

    Args:
        program_type: Housing program label.
        state: Jurisdiction code.

    Returns:
        System prompt for Claude.
    """
    rules = _read_instructions()
    return """
You extract deadlines and notice windows from regulatory text and reply ONLY with JSON.
Program type: {program_type}
State: {state}

Behavioral rules from INSTRUCTIONS.md:
{rules}

JSON shape:
{{
  "deadlines": [{{"name": "string", "description": "string", "due_text": "string", "citation": "string"}}],
  "recert_windows": [{{"description": "string", "window_text": "string", "citation": "string"}}],
  "notice_requirements": [{{"description": "string", "notice_text": "string", "citation": "string"}}],
  "confidence": 0.0
}}
""".strip().format(program_type=program_type, state=state, rules=rules)


def deadline_node(state: PipelineState) -> dict[str, Any]:
    """Parse deadline-related obligations from the routed section text.

    Args:
        state: Pipeline state including `section_text`.

    Returns:
        Partial state update for deadlines and audit log.
    """
    program_type = str(state.get("program_type") or "HUD")
    us_state = str(state.get("us_state") or "")
    section_text = str(state.get("deadline_section_text") or "")
    system = build_system_prompt(program_type, us_state)
    user = """
Extract deadlines from the following excerpt. Output JSON only.

SECTION_TEXT:
{section_text}
""".strip().format(section_text=section_text)
    try:
        parsed = call_claude_json(system, user)
        findings = DeadlineFindings.model_validate(parsed)
        conf = float(findings.confidence)
    except (
        anthropic.APIError,
        json.JSONDecodeError,
        ValueError,
        RuntimeError,
    ) as exc:
        findings = DeadlineFindings(
            deadlines=[],
            recert_windows=[],
            notice_requirements=[],
            confidence=0.0,
        )
        conf = 0.0
        _ = exc
    audit = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "agent": "deadline_agent",
        "confidence": conf,
        "note": "Completed deadline_agent",
    }
    if conf < HUMAN_REVIEW_CONFIDENCE_THRESHOLD:
        audit["note"] += " — low confidence triggers human review at synthesis."
    return {
        "deadline_findings": findings.model_dump(),
        "audit_log": [audit],
    }


def run(state: PipelineState) -> dict[str, Any]:
    """Public alias for the LangGraph node function name convention.

    Args:
        state: Pipeline state.

    Returns:
        Partial update dict.
    """
    return deadline_node(state)
