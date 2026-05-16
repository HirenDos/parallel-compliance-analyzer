"""Income rules specialist agent node (LangGraph + Claude)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic

from agents.claude_client import call_claude_json
from config.settings import HUMAN_REVIEW_CONFIDENCE_THRESHOLD
from schemas.models import IncomeFindings, PipelineState


def _read_instructions() -> str:
    """Load behavioral rules shipped alongside this agent.

    Returns:
        Markdown instructions for the system prompt.
    """
    return (Path(__file__).resolve().parent / "INSTRUCTIONS.md").read_text(
        encoding="utf-8"
    )


def build_system_prompt(program_type: str, state: str) -> str:
    """Combine static behavioral rules with jurisdiction context.

    Args:
        program_type: Housing program label (HUD, LIHTC, etc.).
        state: US state or jurisdiction code.

    Returns:
        System prompt text for Claude.
    """
    rules = _read_instructions()
    return """
You extract HUD/LIHTC-style income rules from regulatory text and reply ONLY with JSON.
Program type: {program_type}
State: {state}

Rules you MUST follow (verbatim policy loaded from INSTRUCTIONS.md):
{rules}

Respond with JSON ONLY (no markdown) matching this shape:
{{
  "rules": [{{"rule_id": "string", "text": "string", "citation": "string"}}],
  "ami_thresholds": [{{"ami_percent": null or int, "household_size": null or int, "limit_amount": null or string, "citation": "string"}}],
  "exceptions": ["string"],
  "confidence": 0.0,
  "source_citations": ["string"]
}}
""".strip().format(program_type=program_type, state=state, rules=rules)


def income_rules_node(state: PipelineState) -> dict[str, Any]:
    """Analyze income-related excerpts and persist structured findings.

    Args:
        state: Pipeline state including section_text and program metadata.

    Returns:
        Partial state update with income_findings and audit_log append-only entry.
    """
    program_type = str(state.get("program_type") or "HUD")
    us_state = str(state.get("us_state") or "")
    section_text = str(state.get("income_section_text") or "")
    system = build_system_prompt(program_type, us_state)
    user = """
Analyze the following regulatory excerpt and output JSON for IncomeFindings.

SECTION_TEXT:
{section_text}
""".strip().format(section_text=section_text)
    try:
        parsed = call_claude_json(system, user)
        findings = IncomeFindings.model_validate(parsed)
        conf = float(findings.confidence)
    except (
        anthropic.APIError,
        json.JSONDecodeError,
        ValueError,
        RuntimeError,
    ) as exc:
        findings = IncomeFindings(
            rules=[],
            ami_thresholds=[],
            exceptions=[f"Income agent failed: {exc}"],
            confidence=0.0,
            source_citations=[],
        )
        conf = 0.0
    audit = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "agent": "income_rules_agent",
        "confidence": conf,
        "note": "Completed income_rules_agent",
    }
    if conf < HUMAN_REVIEW_CONFIDENCE_THRESHOLD:
        audit["note"] += " — low confidence triggers human review at synthesis."
    return {
        "income_findings": findings.model_dump(),
        "audit_log": [audit],
    }


def run(state: PipelineState) -> dict[str, Any]:
    """Alias entrypoint matching project agent conventions.

    Args:
        state: Pipeline state.

    Returns:
        Partial state update.
    """
    return income_rules_node(state)
