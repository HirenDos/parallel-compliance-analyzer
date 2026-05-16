# SKILL: PDF Text Extractor

## What I can do
Extract clean text from PDF regulatory documents using pdfplumber.
Handle multi-column layouts, tables, and headers. Return structured
text with page numbers preserved for source citation.

## How to use me
from skills.pdf_extractor import extract_pdf_text
text, metadata = extract_pdf_text(file_path: str) -> tuple[str, dict]

## Failure modes
- Scanned PDFs (image-only): raises ScannedPDFError → fall back to OCR skill
- Password-protected: raises ProtectedPDFError → prompt user
- Corrupted file: raises ExtractionError → log and skip

## Dependencies
pdfplumber>=0.10.0
