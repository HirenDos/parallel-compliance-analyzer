"""LangGraph StateGraph wiring with parallel fan-out via Send()."""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Send

from agents.orchestrator.orchestrator import orchestrator_node
from agents.synthesizer.synthesizer import synthesizer_node
from config.settings import PROJECT_ROOT
from schemas.models import PipelineState


def _load_node_module(relative_module_file: str) -> Any:
    """Load a module by file path for hyphenated agent directories.

    Args:
        relative_module_file: Project-relative path using forward slashes.

    Returns:
        Imported module object.
    """
    path = (PROJECT_ROOT / relative_module_file).resolve()
    safe_name = (
        "ext_"
        + path.as_posix()
        .replace("/", "__")
        .replace("-", "_")
        .replace(".py", "")
    )
    spec = importlib.util.spec_from_file_location(safe_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load agent module at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_income_mod = _load_node_module("agents/income-rules/income_rules_agent.py")
_deadline_mod = _load_node_module("agents/deadline-tracker/deadline_agent.py")
_violation_mod = _load_node_module("agents/violation-flags/violation_agent.py")
_reporting_mod = _load_node_module("agents/reporting-reqs/reporting_agent.py")

income_rules_node = _income_mod.income_rules_node
deadline_node = _deadline_mod.deadline_node
violation_node = _violation_mod.violation_node
reporting_node = _reporting_mod.reporting_node


def route_to_agents(state: PipelineState) -> Sequence[Send]:
    """Fan out to all four specialist agents simultaneously.

    Args:
        state: Pipeline state after orchestration; must include routing metadata.

    Returns:
        A list of ``Send`` instructions for LangGraph parallel execution.
    """
    meta = state.get("document_metadata") or {}
    sections = state.get("sections") or {}
    program_type = str(state.get("program_type") or meta.get("program_type") or "HUD")
    us_state = str(meta.get("state") or "")
    run_id = str(state.get("run_id") or "")
    return [
        Send(
            "income_rules_agent",
            {
                "income_section_text": sections.get("income", ""),
                "program_type": program_type,
                "us_state": us_state,
                "run_id": run_id,
            },
        ),
        Send(
            "deadline_agent",
            {
                "deadline_section_text": sections.get("deadlines", ""),
                "program_type": program_type,
                "us_state": us_state,
                "run_id": run_id,
            },
        ),
        Send(
            "violation_agent",
            {
                "violation_section_text": sections.get("violations", ""),
                "program_type": program_type,
                "us_state": us_state,
                "run_id": run_id,
            },
        ),
        Send(
            "reporting_agent",
            {
                "reporting_section_text": sections.get("reporting", ""),
                "program_type": program_type,
                "us_state": us_state,
                "run_id": run_id,
            },
        ),
    ]


def build_graph() -> StateGraph:
    """Construct the uncompiled StateGraph for the compliance pipeline.

    Returns:
        LangGraph builder with nodes and edges configured (not yet compiled).
    """
    graph = StateGraph(PipelineState)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("income_rules_agent", income_rules_node)
    graph.add_node("deadline_agent", deadline_node)
    graph.add_node("violation_agent", violation_node)
    graph.add_node("reporting_agent", reporting_node)
    graph.add_node("synthesizer", synthesizer_node)

    graph.set_entry_point("orchestrator")
    graph.add_conditional_edges("orchestrator", route_to_agents)
    graph.add_edge("income_rules_agent", "synthesizer")
    graph.add_edge("deadline_agent", "synthesizer")
    graph.add_edge("violation_agent", "synthesizer")
    graph.add_edge("reporting_agent", "synthesizer")
    graph.add_edge("synthesizer", END)
    return graph


def compile_pipeline(
    *,
    checkpointer: Any,
    interrupt_before: list[str] | None = None,
):
    """Compile the graph with checkpointing (and optional HITL pauses).

    Args:
        checkpointer: LangGraph checkpointer instance (for example ``SqliteSaver``).
        interrupt_before: Optional node names to pause before (human review gate).

    Returns:
        Compiled LangGraph application callable.
    """
    graph = build_graph()
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before or ["synthesizer"],
    )


def open_sqlite_saver(checkpoint_path: str) -> Any:
    """Create a SQLite checkpointer for the pipeline run.

    Args:
        checkpoint_path: Connection string or path accepted by ``SqliteSaver``.

    Returns:
        Checkpointer object from ``SqliteSaver.from_conn_string``.
    """
    return SqliteSaver.from_conn_string(checkpoint_path)
