"""Reporting requirements specialist agent node (LangGraph + Claude)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic

from agents.claude_client import call_claude_json
from config.settings import HUMAN_REVIEW_CONFIDENCE_THRESHOLD
from schemas.models import PipelineState, ReportingFindings


def _read_instructions() -> str:
    """Load behavioral rules from disk next to this module.

    Returns:
        Markdown rules for system prompt assembly.
    """
    return (Path(__file__).resolve().parent / "INSTRUCTIONS.md").read_text(
        encoding="utf-8"
    )


def build_system_prompt(program_type: str, state: str) -> str:
    """Assemble the Claude system prompt for reporting extraction.

    Args:
        program_type: Housing program label.
        state: Jurisdiction code.

    Returns:
        System prompt including behavioral rules.
    """
    rules = _read_instructions()
    return """
You extract required forms and reporting obligations and reply ONLY with JSON.
Program type: {program_type}
State: {state}

Behavioral rules from INSTRUCTIONS.md:
{rules}

JSON shape:
{{
  "required_forms": [{{"form_id": "string", "title": "string", "purpose": "string", "citation": "string"}}],
  "submission_schedules": [{{"name": "string", "frequency": "string", "details": "string", "citation": "string"}}],
  "data_format_requirements": ["string"],
  "confidence": 0.0
}}
""".strip().format(program_type=program_type, state=state, rules=rules)


def reporting_node(state: PipelineState) -> dict[str, Any]:
    """Extract reporting artifacts for synthesis.

    Args:
        state: Pipeline state including `reporting_section_text`.

    Returns:
        Partial update with reporting findings and audit trail row.
    """
    program_type = str(state.get("program_type") or "HUD")
    us_state = str(state.get("us_state") or "")
    section_text = str(state.get("reporting_section_text") or "")
    system = build_system_prompt(program_type, us_state)
    user = """
Extract reporting requirements from the excerpt. Output JSON only.

SECTION_TEXT:
{section_text}
""".strip().format(section_text=section_text)
    try:
        parsed = call_claude_json(system, user)
        findings = ReportingFindings.model_validate(parsed)
        conf = float(findings.confidence)
    except (
        anthropic.APIError,
        json.JSONDecodeError,
        ValueError,
        RuntimeError,
    ) as exc:
        findings = ReportingFindings(
            required_forms=[],
            submission_schedules=[],
            data_format_requirements=[f"Reporting agent failed: {exc}"],
            confidence=0.0,
        )
        conf = 0.0
    audit = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "agent": "reporting_agent",
        "confidence": conf,
        "note": "Completed reporting_agent",
    }
    if conf < HUMAN_REVIEW_CONFIDENCE_THRESHOLD:
        audit["note"] += " — low confidence triggers human review at synthesis."
    return {
        "reporting_findings": findings.model_dump(),
        "audit_log": [audit],
    }


def run(state: PipelineState) -> dict[str, Any]:
    """Alias entrypoint mirroring other agents' `run` hooks.

    Args:
        state: Pipeline state.

    Returns:
        Partial state update.
    """
    return reporting_node(state)
