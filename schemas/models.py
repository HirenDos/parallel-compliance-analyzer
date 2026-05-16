"""Pydantic v2 models and LangGraph `PipelineState` for typed agent boundaries."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class DocumentMetadata(BaseModel):
    """Structured metadata for a regulatory document."""

    model_config = ConfigDict(strict=True)

    program_type: str = Field(
        ...,
        description="HUD | LIHTC | HOME | USDA | STATE",
    )
    state: str = Field(..., description="US state or jurisdiction code (e.g. CA).")
    effective_date: str = Field(
        ...,
        description="Effective date as stated on the document (ISO or verbatim).",
    )


class SectionPayload(BaseModel):
    """Text slice routed to a specialized agent."""

    model_config = ConfigDict(strict=True)

    target: str = Field(
        ...,
        description="Agent target key: income | deadlines | violations | reporting",
    )
    section_text: str
    program_type: str
    state: str


class Rule(BaseModel):
    model_config = ConfigDict(strict=True)

    rule_id: str
    text: str
    citation: str


class Threshold(BaseModel):
    model_config = ConfigDict(strict=True)

    ami_percent: int | None = None
    household_size: int | None = None
    limit_amount: str | None = None
    citation: str


class IncomeFindings(BaseModel):
    model_config = ConfigDict(strict=True)

    rules: list[Rule] = Field(default_factory=list)
    ami_thresholds: list[Threshold] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    confidence: float
    source_citations: list[str] = Field(default_factory=list)


class Deadline(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str
    description: str
    due_text: str
    citation: str


class RecertWindow(BaseModel):
    model_config = ConfigDict(strict=True)

    description: str
    window_text: str
    citation: str


class NoticeReq(BaseModel):
    model_config = ConfigDict(strict=True)

    description: str
    notice_text: str
    citation: str


class DeadlineFindings(BaseModel):
    model_config = ConfigDict(strict=True)

    deadlines: list[Deadline] = Field(default_factory=list)
    recert_windows: list[RecertWindow] = Field(default_factory=list)
    notice_requirements: list[NoticeReq] = Field(default_factory=list)
    confidence: float


class ViolationFlag(BaseModel):
    model_config = ConfigDict(strict=True)

    code: str
    description: str
    severity: str = Field(..., description="HIGH | MEDIUM | LOW")
    citation: str


class ViolationFindings(BaseModel):
    model_config = ConfigDict(strict=True)

    flags: list[ViolationFlag] = Field(default_factory=list)
    severity_scores: dict[str, int] = Field(default_factory=dict)
    remediation_hints: list[str] = Field(default_factory=list)
    confidence: float


class Form(BaseModel):
    model_config = ConfigDict(strict=True)

    form_id: str
    title: str
    purpose: str
    citation: str


class Schedule(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str
    frequency: str
    details: str
    citation: str


class ReportingFindings(BaseModel):
    model_config = ConfigDict(strict=True)

    required_forms: list[Form] = Field(default_factory=list)
    submission_schedules: list[Schedule] = Field(default_factory=list)
    data_format_requirements: list[str] = Field(default_factory=list)
    confidence: float


class ChecklistItem(BaseModel):
    model_config = ConfigDict(strict=True)

    title: str
    action: str
    consequence: str
    severity: str
    source_agents: list[str] = Field(default_factory=list)
    confidence: float
    needs_human_review: bool = False


class RankedChecklist(BaseModel):
    model_config = ConfigDict(strict=True)

    items: list[ChecklistItem] = Field(default_factory=list)
    overall_risk_score: int = Field(..., ge=0, le=100)
    human_review_flags: list[str] = Field(default_factory=list)
    synthesis_notes: str


class PipelineState(TypedDict, total=False):
    """LangGraph state with reducers for append-only audit and routing logs."""

    raw_text: str
    document_metadata: dict[str, Any]
    sections: dict[str, str]
    run_id: str
    routing_log: Annotated[list[str], operator.add]
    audit_log: Annotated[list[dict[str, Any]], operator.add]
    program_type: str
    confidence_in_routing: float
    income_section_text: str
    deadline_section_text: str
    violation_section_text: str
    reporting_section_text: str
    us_state: str
    income_findings: dict[str, Any]
    deadline_findings: dict[str, Any]
    violation_findings: dict[str, Any]
    reporting_findings: dict[str, Any]
    ranked_checklist: dict[str, Any]
