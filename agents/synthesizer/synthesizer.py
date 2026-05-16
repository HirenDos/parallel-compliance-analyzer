"""Synthesis agent: consolidate parallel findings into a ranked checklist."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic

from agents.claude_client import call_claude_json
from config.settings import HUMAN_REVIEW_CONFIDENCE_THRESHOLD
from schemas.models import (
    DeadlineFindings,
    IncomeFindings,
    PipelineState,
    RankedChecklist,
    ReportingFindings,
    ViolationFindings,
)


def _read_instructions() -> str:
    """Load synthesis behavioral rules from INSTRUCTIONS.md.

    Returns:
        Markdown policy text for the system prompt.
    """
    return (Path(__file__).resolve().parent / "INSTRUCTIONS.md").read_text(
        encoding="utf-8"
    )


def build_system_prompt(program_type: str, state: str) -> str:
    """Construct synthesis system instructions with program context.

    Args:
        program_type: Housing program label.
        state: Jurisdiction code.

    Returns:
        Claude system prompt text including rules from INSTRUCTIONS.md.
    """
    rules = _read_instructions()
    return """
You consolidate parallel compliance findings into a ranked checklist. Reply ONLY with JSON.
Program type: {program_type}
State: {state}

Rules loaded from INSTRUCTIONS.md:
{rules}

JSON schema (RankedChecklist):
{{
  "items": [
    {{
      "title": "string",
      "action": "string",
      "consequence": "string",
      "severity": "HIGH|MEDIUM|LOW",
      "source_agents": ["income|deadline|violation|reporting"],
      "confidence": 0.0,
      "needs_human_review": false
    }}
  ],
  "overall_risk_score": 0,
  "human_review_flags": ["string"],
  "synthesis_notes": "string with bullet lines explaining scoring math"
}}
""".strip().format(program_type=program_type, state=state, rules=rules)


def _safe_income(blob: dict[str, Any] | None) -> IncomeFindings:
    """Parse `IncomeFindings` defensively for partially filled state.

    Args:
        blob: Serialized income findings or None.

    Returns:
        Validated IncomeFindings or empty low-confidence placeholder.
    """
    if not blob:
        return IncomeFindings(
            rules=[],
            ami_thresholds=[],
            exceptions=[],
            confidence=0.0,
            source_citations=[],
        )
    try:
        return IncomeFindings.model_validate(blob)
    except ValueError:
        return IncomeFindings(
            rules=[],
            ami_thresholds=[],
            exceptions=["Invalid income findings payload"],
            confidence=0.0,
            source_citations=[],
        )


def _safe_deadline(blob: dict[str, Any] | None) -> DeadlineFindings:
    """Parse deadline findings with fallback empty model.

    Args:
        blob: Serialized DeadlineFindings or None.

    Returns:
        Validated model or placeholder.
    """
    if not blob:
        return DeadlineFindings(
            deadlines=[],
            recert_windows=[],
            notice_requirements=[],
            confidence=0.0,
        )
    try:
        return DeadlineFindings.model_validate(blob)
    except ValueError:
        return DeadlineFindings(
            deadlines=[],
            recert_windows=[],
            notice_requirements=[],
            confidence=0.0,
        )


def _safe_violation(blob: dict[str, Any] | None) -> ViolationFindings:
    """Parse violation findings with fallback empty model.

    Args:
        blob: Serialized ViolationFindings or None.

    Returns:
        Validated model or placeholder.
    """
    if not blob:
        return ViolationFindings(
            flags=[],
            severity_scores={},
            remediation_hints=[],
            confidence=0.0,
        )
    try:
        return ViolationFindings.model_validate(blob)
    except ValueError:
        return ViolationFindings(
            flags=[],
            severity_scores={},
            remediation_hints=["Invalid violation findings payload"],
            confidence=0.0,
        )


def _safe_reporting(blob: dict[str, Any] | None) -> ReportingFindings:
    """Parse reporting findings with fallback empty model.

    Args:
        blob: Serialized ReportingFindings or None.

    Returns:
        Validated model or placeholder.
    """
    if not blob:
        return ReportingFindings(
            required_forms=[],
            submission_schedules=[],
            data_format_requirements=[],
            confidence=0.0,
        )
    try:
        return ReportingFindings.model_validate(blob)
    except ValueError:
        return ReportingFindings(
            required_forms=[],
            submission_schedules=[],
            data_format_requirements=[],
            confidence=0.0,
        )


def _preflight_human_flags(state: PipelineState) -> list[str]:
    """Derive deterministic human-review flags before LLM synthesis.

    Args:
        state: Pipeline state after parallel agents.

    Returns:
        Human-readable review reasons based on confidence thresholds.
    """
    flags: list[str] = []
    income = _safe_income(state.get("income_findings"))
    deadline = _safe_deadline(state.get("deadline_findings"))
    violation = _safe_violation(state.get("violation_findings"))
    reporting = _safe_reporting(state.get("reporting_findings"))
    if income.confidence < HUMAN_REVIEW_CONFIDENCE_THRESHOLD:
        flags.append("Income findings below confidence threshold.")
    if deadline.confidence < HUMAN_REVIEW_CONFIDENCE_THRESHOLD:
        flags.append("Deadline findings below confidence threshold.")
    if violation.confidence < HUMAN_REVIEW_CONFIDENCE_THRESHOLD:
        flags.append("Violation findings below confidence threshold.")
    if reporting.confidence < HUMAN_REVIEW_CONFIDENCE_THRESHOLD:
        flags.append("Reporting findings below confidence threshold.")
    return flags


def synthesizer_node(state: PipelineState) -> dict[str, Any]:
    """Merge parallel findings and compute a RankedChecklist via Claude.

    Args:
        state: Pipeline checkpointed state with all four findings dicts.

    Returns:
        Partial update with ranked_checklist and audit log row.
    """
    meta = state.get("document_metadata") or {}
    program_type = str(state.get("program_type") or meta.get("program_type") or "HUD")
    us_state = str(meta.get("state") or state.get("us_state") or "")
    system = build_system_prompt(program_type, us_state)
    income = _safe_income(state.get("income_findings"))
    deadline = _safe_deadline(state.get("deadline_findings"))
    violation = _safe_violation(state.get("violation_findings"))
    reporting = _safe_reporting(state.get("reporting_findings"))
    pre_flags = _preflight_human_flags(state)
    user = """
Combine the findings into RankedChecklist JSON. Source payload:
INCOME_FINDINGS:
{income}
DEADLINE_FINDINGS:
{deadline}
VIOLATION_FINDINGS:
{violation}
REPORTING_FINDINGS:
{reporting}
PRECOMPUTED_REVIEW_FLAGS:
{flags}
""".strip().format(
        income=json.dumps(income.model_dump(), indent=2),
        deadline=json.dumps(deadline.model_dump(), indent=2),
        violation=json.dumps(violation.model_dump(), indent=2),
        reporting=json.dumps(reporting.model_dump(), indent=2),
        flags=json.dumps(pre_flags, indent=2),
    )
    try:
        parsed = call_claude_json(system, user)
        checklist = RankedChecklist.model_validate(parsed)
        if not checklist.human_review_flags:
            checklist = checklist.model_copy(
                update={"human_review_flags": pre_flags}
            )
        else:
            merged: list[str] = list(dict.fromkeys(checklist.human_review_flags + pre_flags))
            checklist = checklist.model_copy(update={"human_review_flags": merged})
        conf = max(
            float(income.confidence),
            float(deadline.confidence),
            float(violation.confidence),
            float(reporting.confidence),
        )
    except (
        anthropic.APIError,
        json.JSONDecodeError,
        ValueError,
        RuntimeError,
    ) as exc:
        checklist = RankedChecklist(
            items=[],
            overall_risk_score=0,
            human_review_flags=pre_flags + [f"Synthesis failed: {exc}"],
            synthesis_notes="Synthesis could not complete; human review required.",
        )
        conf = 0.0
    audit = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "agent": "synthesizer",
        "confidence": conf,
        "note": "Completed synthesizer",
    }
    return {
        "ranked_checklist": checklist.model_dump(),
        "audit_log": [audit],
    }


def run(state: PipelineState) -> dict[str, Any]:
    """Alias hook mirroring other agents.

    Args:
        state: Pipeline state.

    Returns:
        Partial update dict.
    """
    return synthesizer_node(state)
