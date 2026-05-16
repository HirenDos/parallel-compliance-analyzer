"""CLI entry point for the parallel compliance document analyzer."""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from config.settings import PROJECT_ROOT
from graph.pipeline import compile_pipeline
from schemas.models import RankedChecklist
from skills.pdf_extractor import (
    ExtractionError,
    ProtectedPDFError,
    ScannedPDFError,
    extract_pdf_text,
)

load_dotenv()
console = Console()


def _read_input_text(path: Path) -> str:
    """Read UTF-8 text from an input path.

    Args:
        path: Path to a regulation text or extracted PDF transcript file.

    Returns:
        Document body as a string.

    Raises:
        OSError: If the file cannot be read.
    """
    return path.read_text(encoding="utf-8")


def _load_document_text(path: Path) -> tuple[str, dict[str, Any] | None]:
    """Load document body from plain text or a PDF.

    PDFs are converted with ``pdfplumber`` via ``extract_pdf_text``.

    Args:
        path: Path to a ``.txt``/``.md``/``.pdf`` (or other text you choose to read as UTF-8).

    Returns:
        Tuple of ``(full_text, pdf_metadata)``. For non-PDF files, ``pdf_metadata`` is ``None``.

    Raises:
        OSError: If a text file cannot be read.
        ScannedPDFError: If the PDF appears image-only.
        ProtectedPDFError: If the PDF is password-protected.
        ExtractionError: If PDF parsing fails.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text, metadata = extract_pdf_text(str(path))
        return text, metadata
    return _read_input_text(path), None


def _render_markdown_report(checklist: RankedChecklist, run_id: str) -> str:
    """Turn a ranked checklist into a hiring-manager friendly Markdown report.

    Args:
        checklist: Final synthesis output.
        run_id: Correlation id for this pipeline execution.

    Returns:
        A Markdown document string suitable for writing to disk.
    """
    lines: list[str] = [
        "# Compliance checklist",
        "",
        f"**Run ID:** `{run_id}`",
        "",
        f"**Overall risk score:** {checklist.overall_risk_score}/100",
        "",
        "## Ranked items",
        "",
    ]
    for idx, item in enumerate(checklist.items, start=1):
        lines.extend(
            [
                f"### {idx}. {item.title}",
                "",
                f"- **Severity:** {item.severity}",
                f"- **Action:** {item.action}",
                f"- **If ignored:** {item.consequence}",
                f"- **Sources:** {', '.join(item.source_agents)}",
                f"- **Confidence:** {item.confidence:.2f}",
                f"- **Human review:** {item.needs_human_review}",
                "",
            ]
        )
    lines.extend(
        [
            "## Human review flags",
            "",
        ]
    )
    if checklist.human_review_flags:
        for flag in checklist.human_review_flags:
            lines.append(f"- {flag}")
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Synthesis notes", "", checklist.synthesis_notes, ""])
    return "\n".join(lines)


def _write_outputs(
    run_id: str,
    checklist: RankedChecklist,
    markdown_path: Path,
    json_path: Path,
) -> None:
    """Persist Markdown + JSON artifacts for downstream review.

    Args:
        run_id: Run correlation id.
        checklist: Ranked checklist model.
        markdown_path: Destination for Markdown report.
        json_path: Destination for JSON payload.

    Raises:
        OSError: If parent directories are missing and cannot be created.
    """
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(
        _render_markdown_report(checklist, run_id),
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps(checklist.model_dump(), indent=2),
        encoding="utf-8",
    )


def _log_stream_update(agent_status: dict[str, str], update: dict[str, Any]) -> None:
    """Update and print compact agent status lines from a streamed graph update.

    Args:
        agent_status: Mutable map of last-known status lines per agent.
        update: A single LangGraph stream payload for the ``updates`` channel.
    """
    for node, payload in update.items():
        if not isinstance(payload, dict):
            continue
        if node.endswith("agent") or node in {"orchestrator", "synthesizer"}:
            audit = payload.get("audit_log")
            conf_hint: str | None = None
            if isinstance(audit, list) and audit:
                last = audit[-1]
                if isinstance(last, dict) and "confidence" in last:
                    conf_hint = str(last["confidence"])
            if conf_hint is not None:
                agent_status[node] = f"[green]{node}[/green] confidence={conf_hint}"
            else:
                agent_status[node] = f"[green]{node}[/green] updated"


def main() -> None:
    """Parse CLI flags, run the LangGraph pipeline, and write reports."""
    parser = argparse.ArgumentParser(
        description="Parallel HUD/LIHTC compliance analyzer (LangGraph fan-out).",
    )
    parser.add_argument(
        "--input",
        type=str,
        default="sample_inputs/sample_hud_regulation.txt",
        help="Path to regulation text (.txt/.md) or a .pdf (extracted via pdfplumber).",
    )
    parser.add_argument(
        "--program",
        type=str,
        default="HUD",
        help="Program label (HUD, LIHTC, HOME, USDA, STATE).",
    )
    parser.add_argument(
        "--state",
        dest="us_state",
        type=str,
        default="CA",
        help="US state or jurisdiction code.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="outputs/report.md",
        help="Primary Markdown output path (run_id will also be mirrored under outputs/).",
    )
    parser.add_argument(
        "--resume",
        type=str,
        default="",
        help="Existing run_id / thread_id to resume after a synthesizer interrupt.",
    )
    args = parser.parse_args()

    run_id = args.resume.strip() or str(uuid.uuid4())
    checkpoint_db = PROJECT_ROOT / "state" / f"{run_id}.db"
    checkpoint_db.parent.mkdir(parents=True, exist_ok=True)

    input_path = Path(args.input)
    if not args.resume.strip() and not input_path.is_file():
        console.print(
            Panel.fit(
                f"Input file not found: [red]{escape(str(input_path))}[/red]",
                title="fatal",
            )
        )
        raise SystemExit(2)

    markdown_out = Path(args.output)
    json_out = markdown_out.with_suffix(".json")

    if not args.resume.strip():
        try:
            raw_text, pdf_meta = _load_document_text(input_path)
        except OSError as exc:
            console.print(
                Panel.fit(
                    f"Could not read input: [red]{escape(str(exc))}[/red]",
                    title="fatal",
                )
            )
            raise SystemExit(2) from exc
        except (ScannedPDFError, ProtectedPDFError, ExtractionError) as exc:
            console.print(
                Panel.fit(
                    f"PDF input failed: [red]{escape(str(exc))}[/red]",
                    title="fatal",
                )
            )
            raise SystemExit(2) from exc
        if pdf_meta is not None:
            pages = pdf_meta.get("page_count", "?")
            console.print(
                Panel.fit(
                    f"Extracted text from PDF ([cyan]{pages}[/cyan] pages).",
                    title="input",
                )
            )
        document_metadata: dict[str, Any] = {
            "program_type": args.program,
            "state": args.us_state,
            "effective_date": "unspecified-in-cli-demo",
            "source_path": str(input_path.resolve()),
        }
        if pdf_meta is not None:
            document_metadata["pdf_page_count"] = pdf_meta.get("page_count")
            document_metadata["pdf_has_tables"] = pdf_meta.get("has_tables")
            document_metadata["pdf_estimated_program_type"] = pdf_meta.get(
                "estimated_program_type"
            )
        initial_state = {
            "raw_text": raw_text,
            "document_metadata": document_metadata,
            "routing_log": [],
            "audit_log": [],
            "run_id": run_id,
        }
    else:
        initial_state = {}

    config: dict[str, Any] = {"configurable": {"thread_id": run_id}}

    with SqliteSaver.from_conn_string(str(checkpoint_db)) as checkpointer:
        app = compile_pipeline(checkpointer=checkpointer)
        agent_status: dict[str, str] = {}

        if args.resume.strip():
            out: dict[str, Any] = app.invoke(None, config)
        else:
            for update in app.stream(initial_state, config, stream_mode="updates"):
                if isinstance(update, dict):
                    _log_stream_update(agent_status, update)
                    table = Table(title="Agent activity")
                    table.add_column("Agent")
                    table.add_column("Status")
                    for name, status in sorted(agent_status.items()):
                        table.add_row(name, status)
                    console.print(table)
            out = app.invoke(None, config)

        guard = 0
        while not out.get("ranked_checklist") and guard < 4:
            snap = app.get_state(config)
            values = getattr(snap, "values", {}) or {}
            if isinstance(values, dict) and values.get("ranked_checklist"):
                out = values
                break
            out = app.invoke(None, config)
            guard += 1

    checklist_raw = out.get("ranked_checklist")
    if not checklist_raw:
        console.print(
            Panel.fit(
                "Pipeline finished without a ranked checklist. Check API keys, logs, and checkpoints.",
                title="fatal",
            )
        )
        raise SystemExit(3)

    checklist = RankedChecklist.model_validate(checklist_raw)
    run_slug = str(out.get("run_id") or run_id)
    md_named = PROJECT_ROOT / "outputs" / f"{run_slug}_report.md"
    json_named = PROJECT_ROOT / "outputs" / f"{run_slug}_report.json"
    _write_outputs(run_slug, checklist, md_named, json_named)
    _write_outputs(run_slug, checklist, markdown_out, json_out)

    console.print(
        Panel.fit(
            f"Wrote [cyan]{escape(str(md_named))}[/cyan] "
            f"and [cyan]{escape(str(json_named))}[/cyan].",
            title="done",
        )
    )


if __name__ == "__main__":
    main()
