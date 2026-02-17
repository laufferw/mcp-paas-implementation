# Memory Tiers and Retrieval Modes

AgentGate uses two memory tiers and two retrieval modes to balance speed, precision, and synthesis.

## Memory tiers

### Tier A — Working Memory (Core)
- Purpose: fast operational state for active runs
- Data examples: current plan, selected route strategy, active policy context, run-local notes
- Properties: low-latency, explicit structure, deterministic updates

### Tier B — Archival Memory (Semantic)
- Purpose: long-horizon recall across historical artifacts
- Data examples: prior decisions, runbooks, pilot outcomes, incident/debug history
- Properties: concept-level retrieval, broader context, slower but richer recall

## Retrieval modes

### 1) Exact Lookup (Deterministic)
Use for:
- policy/rule checks
- endpoint or schema verification
- explicit IDs, paths, and known terms

Expected output:
- precise hit(s), minimal ambiguity

### 2) Semantic Synthesis (Conceptual)
Use for:
- pattern discovery across prior work
- architecture tradeoff comparisons
- finding related incidents/lessons with different wording

Expected output:
- ranked related context + synthesized summary

## Mode selection guidance
- Start with **exact lookup** when correctness is strict.
- Escalate to **semantic synthesis** when the question is exploratory or cross-cutting.
- For critical decisions, combine both: deterministic facts + conceptual context.

## Operator note
Do not present semantic synthesis as authoritative without citing concrete artifacts when available.
