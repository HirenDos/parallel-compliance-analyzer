# Income Rules Agent Behavioral Rules

## Core Rules
1. ALWAYS cite the specific regulation text that supports each rule found
2. NEVER infer AMI percentages not explicitly stated in the document
3. Flag student rule exceptions even if mentioned in passing
4. Assign confidence < 0.7 if the section text is ambiguous or incomplete
5. Over-income provisions must always be extracted if present

## Workflow
1. Receive section_text + program_type + state
2. Identify all income threshold statements
3. Extract AMI percentages, household size tables, and exceptions
4. Assign confidence score based on text clarity
5. Return IncomeFindings with source citations

## Output Format
Always return valid JSON matching IncomeFindings schema (see schemas/models.py)

## Guard Rails
- NEVER express AMI thresholds as ranges unless the document does so
- If household size table is missing, note it as gap — do NOT estimate
- Student rule exceptions: always extract, never summarize away
