"""Model configuration, thresholds, and allowed program types."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

CLAUDE_MODEL: str = os.environ.get(
    "CLAUDE_MODEL",
    "claude-sonnet-4-6",
)

ALLOWED_PROGRAM_TYPES: frozenset[str] = frozenset(
    {"HUD", "LIHTC", "HOME", "USDA", "STATE"}
)

ORCHESTRATOR_MAX_SECTION_CHARS: int = int(
    os.environ.get("ORCHESTRATOR_MAX_SECTION_CHARS", "32000"),
)

HUMAN_REVIEW_CONFIDENCE_THRESHOLD: float = float(
    os.environ.get("HUMAN_REVIEW_CONFIDENCE_THRESHOLD", "0.7"),
)

ANTHROPIC_API_KEY: str | None = os.environ.get("ANTHROPIC_API_KEY")

MAX_LLM_RETRIES: int = 2
LLM_RETRY_BASE_SECONDS: float = 1.5
