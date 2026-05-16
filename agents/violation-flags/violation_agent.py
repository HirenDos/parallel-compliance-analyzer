"""Violation risk specialist agent node (LangGraph + Claude)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic

from agents.claude_client import call_claude_json
from config.settings import HUMAN_REVIEW_CONFIDENCE_THRESHOLD
from schemas.models import PipelineState, ViolationFindings, ViolationFlag


def _read_instructions() -> str:
    """Load behavioral rules from INSTRUCTIONS.md.

    Returns:
        Markdown instruction body for the Claude system prompt.
    """
    return (Path(__file__).resolve().parent / "INSTRUCTIONS.md").read_text(
        encoding="utf-8"
    )


def build_system_prompt(program_type: str, state: str) -> str:
    """Build system prompt for violation scanning.

    Args:
        program_type: Housing program label.
        state: Jurisdiction code.

    Returns:
        Static system prompt string plus embedded behavioral rules.
    """
    rules = _read_instructions()
    return """
You identify compliance risk language in regulatory text and reply ONLY with JSON.
Program type: {program_type}
State: {state}

Behavioral rules from INSTRUCTIONS.md:
{rules}

JSON shape:
{{
  "flags": [{{"code": "string", "description": "string", "severity": "HIGH|MEDIUM|LOW", "citation": "string"}}],
  "severity_scores": {{"HIGH": 3, "MEDIUM": 2, "LOW": 1}},
  "remediation_hints": ["string"],
  "confidence": 0.0
}}
""".strip().format(program_type=program_type, state=state, rules=rules)


def violation_node(state: PipelineState) -> dict[str, Any]:
    """Classify penalty and enforcement language for synthesis ranking.

    Args:
        state: Pipeline state including `violation_section_text`.

    Returns:
        Partial update with `violation_findings` and `audit_log` entry.
    """
    program_type = str(state.get("program_type") or "HUD")
    us_state = str(state.get("us_state") or "")
    section_text = str(state.get("violation_section_text") or "")
    system = build_system_prompt(program_type, us_state)
    user = """
Scan for non-compliance risk indicators in the excerpt. Output JSON only.

SECTION_TEXT:
{section_text}
""".strip().format(section_text=section_text)
    try:
        parsed = call_claude_json(system, user)
        findings = ViolationFindings.model_validate(parsed)
        conf = float(findings.confidence)
    except (
        anthropic.APIError,
        json.JSONDecodeError,
        ValueError,
        RuntimeError,
    ) as exc:
        findings = ViolationFindings(
            flags=[
                ViolationFlag(
                    code="PARSE_FAILURE",
                    description="Violation agent could not complete structured extraction.",
                    severity="LOW",
                    citation="N/A",
                )
            ],
            severity_scores={"HIGH": 3, "MEDIUM": 2, "LOW": 1},
            remediation_hints=[str(exc)],
            confidence=0.0,
        )
        conf = 0.0
    audit = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "agent": "violation_agent",
        "confidence": conf,
        "note": "Completed violation_agent",
    }
    if conf < HUMAN_REVIEW_CONFIDENCE_THRESHOLD:
        audit["note"] += " — low confidence triggers human review at synthesis."
    return {
        "violation_findings": findings.model_dump(),
        "audit_log": [audit],
    }


def run(state: PipelineState) -> dict[str, Any]:
    """Compatibility alias for orchestration layers expecting `run`.

    Args:
        state: Pipeline state.

    Returns:
        Partial update dict.
    """
    return violation_node(state)
