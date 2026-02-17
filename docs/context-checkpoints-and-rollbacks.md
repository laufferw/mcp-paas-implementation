# Context Checkpoints and Rollbacks

AgentGate execution uses lightweight context versioning to reduce drift in long runs.

## Why
Large implementation streams can degrade when a wrong assumption contaminates subsequent steps.

## Method
1. **Checkpoint before major step**
   - Record objective, assumptions, and success criteria.
2. **Name branches explicitly**
   - Example: `path-A strict schema`, `path-B compatibility-first`.
3. **Pin golden rules**
   - Keep 3-7 non-negotiables visible during execution.
4. **Rollback on degradation**
   - If evidence quality drops or contradictions appear, return to last known-good checkpoint.
5. **Reflog note**
   - Record why direction changed and what was preserved.

## Checkpoint template
- Checkpoint ID:
- Objective:
- Assumptions:
- Golden rules:
- First-value condition:
- Evidence path(s):

## Rollback trigger examples
- Tests regress after broad changes
- Contract ambiguity increases instead of decreases
- New changes break previously validated behavior
- Evidence confidence drops from HIGH to MEDIUM/LOW

## Rule
Prefer small, reversible moves over deep speculative chains.
