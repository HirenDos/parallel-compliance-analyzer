"""Extract plain text and metadata from regulatory PDFs using pdfplumber."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pdfplumber


class ScannedPDFError(RuntimeError):
    """Raised when a PDF appears to be image-only (no extractable text)."""


class ProtectedPDFError(RuntimeError):
    """Raised when a PDF is password-protected and cannot be opened."""


class ExtractionError(RuntimeError):
    """Raised when the PDF cannot be read or parsed."""


def _estimate_program_type(text_sample: str) -> str:
    """Infer a coarse program label from header cues for portfolio metadata.

    Args:
        text_sample: Beginning of extracted document text.

    Returns:
        One of HUD, LIHTC, HOME, USDA, STATE — defaults to HUD if unknown.
    """
    upper = text_sample.upper()
    if "LIHTC" in upper or "LOW-INCOME HOUSING TAX CREDIT" in upper:
        return "LIHTC"
    if "HOME " in upper or "HOME INVESTMENT" in upper:
        return "HOME"
    if "USDA" in upper or "RD " in upper or "RURAL DEVELOPMENT" in upper:
        return "USDA"
    if "SECTION 8" in upper or "HOUSING CHOICE VOUCHER" in upper or "HCV" in upper:
        return "HUD"
    if any(x in upper for x in ("STATE HOUSING", "LOCAL PREFERENCE", "QAP")):
        return "STATE"
    return "HUD"


def extract_pdf_text(file_path: str) -> tuple[str, dict[str, Any]]:
    """Extract text from a PDF with page-aware structure and document metadata.

    Args:
        file_path: Filesystem path to the PDF file.

    Returns:
        A tuple of full_text and metadata dict (page_count, has_tables,
        detected_headers, estimated_program_type).

    Raises:
        ScannedPDFError: If extractable text is negligible across pages.
        ProtectedPDFError: If the file requires a password.
        ExtractionError: If the file is missing, corrupt, or unreadable.
    """
    path = Path(file_path)
    if not path.is_file():
        raise ExtractionError(
            f"PDF not found or not a file: '{file_path}'. Provide a valid path."
        )

    try:
        with pdfplumber.open(path) as pdf_doc:  # type: ignore[arg-type]
            if getattr(pdf_doc, "is_encrypted", False):
                raise ProtectedPDFError(
                    "This PDF is password-protected. Remove the password or supply "
                    "credentials, then retry extraction."
                )
            pages_text: list[str] = []
            has_tables = False
            page_count = len(pdf_doc.pages)
            for idx, page in enumerate(pdf_doc.pages, start=1):
                try:
                    tables = page.extract_tables() or []
                except Exception as exc:  # noqa: BLE001 — pdfplumber surface varies
                    raise ExtractionError(
                        f"Failed reading tables on page {idx}: {exc}"
                    ) from exc
                if tables:
                    has_tables = True
                try:
                    page_text = page.extract_text() or ""
                except Exception as exc:  # noqa: BLE001
                    raise ExtractionError(
                        f"Failed extracting text on page {idx}: {exc}"
                    ) from exc
                pages_text.append(f"\n--- Page {idx} ---\n{page_text}")

            full_text = "\n".join(pages_text).strip()
    except ProtectedPDFError:
        raise
    except ScannedPDFError:
        raise
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError(f"Could not open or parse PDF: {exc}") from exc

    if page_count > 0:
        alpha = sum(c.isalnum() for c in full_text)
        if alpha < max(40, page_count * 20):
            raise ScannedPDFError(
                "Extracted almost no text; this may be a scanned PDF. Use OCR, then "
                "retry with a text layer."
            )

    header_lines = [
        line.strip()
        for line in full_text.splitlines()
        if line.strip() and len(line.strip()) < 120
    ]
    detected_headers = [
        h
        for h in header_lines[:80]
        if re.match(r"^(\d+(\.\d+)*|[A-Z][A-Z0-9 \-/]{6,})", h)
    ]
    sample = full_text[:4000]
    metadata: dict[str, Any] = {
        "page_count": page_count,
        "has_tables": has_tables,
        "detected_headers": detected_headers[:50],
        "estimated_program_type": _estimate_program_type(sample),
    }
    return full_text, metadata
