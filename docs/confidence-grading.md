# Confidence Grading for Findings

Use confidence levels to speed triage and reduce noisy decision-making.

## Levels

| Level | Meaning | Expected Action |
|---|---|---|
| HIGH | Strong evidence, reproducible, low ambiguity | Safe to prioritize immediately; can be auto-fixed when mechanical |
| MEDIUM | Likely valid but depends on context | Human review before acting |
| LOW | Weak signal or incomplete evidence | Treat as hypothesis; gather more proof first |

## Required evidence by level
- **HIGH**: reproducible command/output + clear artifact path
- **MEDIUM**: partial reproduction or strong static evidence + explicit caveat
- **LOW**: suspected pattern only, no direct proof yet

## Reporting format
Use this compact structure:

- **Finding**: <summary>
- **Confidence**: HIGH | MEDIUM | LOW
- **Evidence**: <command/log/artifact>
- **Next action**: <fix/verify/defer>

## Rule
Do not present LOW-confidence findings as blockers unless they are security-critical.
