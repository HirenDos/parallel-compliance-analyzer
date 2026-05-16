# SKILL: Regulatory Section Splitter

## What I can do
Split a large regulatory document text into thematic sections
using header detection and semantic chunking. Returns a dict
keyed by theme (income, deadlines, violations, reporting).

## How to use me
from skills.section_splitter import split_sections
sections: dict[str, str] = split_sections(text: str, program_type: str)

## Failure modes
- No clear headers found: returns full text under "general" key
- Section too large for context window: splits at paragraph boundaries
