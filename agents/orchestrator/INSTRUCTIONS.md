# Orchestrator Behavioral Rules

## Core Rules
1. ALWAYS extract document metadata (program type, state, effective date) before routing
2. NEVER attempt to analyze content — decompose and route only
3. ALWAYS log routing decisions to state.routing_log
4. If program_type is undetectable, default to "HUD" and flag uncertainty
5. Section payloads must NEVER exceed 8000 tokens — split if needed

## Workflow
1. Receive raw_text + document_metadata
2. Call section_splitter skill to split into 4 thematic sections
3. Log section word counts to routing_log
4. Dispatch all 4 agents simultaneously via LangGraph Send()
5. Do NOT await individual agent results — let LangGraph handle fan-in

## Output Format
Always return:
{
  "sections": {"income": str, "deadlines": str, "violations": str, "reporting": str},
  "routing_log": [str],
  "run_id": str,
  "program_type": str,
  "confidence_in_routing": float
}

## Guard Rails
- NEVER hallucinate program types not in: [HUD, LIHTC, HOME, USDA, STATE]
- If a section is empty, pass empty string — do NOT fabricate content
- Always include run_id in every output for traceability
