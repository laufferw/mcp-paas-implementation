# Contributing to AgentGate

Thanks for your interest. AgentGate is an early-stage project — contributions that make the control plane more useful, more reliable, or easier to understand are welcome.

## What we're looking for

**Most useful right now:**
- Bug reports with reproduction steps
- Transport adapter improvements (WebSocket execution, better error handling in SSE/stdio)
- Policy engine edge cases and test coverage
- A2A protocol support (agent-to-agent task delegation)
- Docker and deployment improvements
- Documentation clarity and examples

**Not the focus right now:**
- New transport protocols that aren't MCP, A2A, or REST
- UI work (admin UI is on the roadmap but not the current priority)
- Speculative features without a concrete use case

## Getting started

```bash
git clone https://github.com/laufferw/mcp-paas-implementation
cd mcp-paas-implementation
pip install -r requirements.txt
python scripts/migrate.py
uvicorn server:app --reload
pytest -q gateway_tests/
```

All tests should pass before you start. If they don't, open an issue.

## How to contribute

1. Open an issue first for anything non-trivial — describe what you want to change and why
2. Fork the repo and create a branch (`fix/issue-description` or `feat/thing-you-are-adding`)
3. Write tests for any new behavior
4. Make sure `pytest -q gateway_tests/` passes
5. Open a PR with a clear description of what changed and why

## Code style

- Python 3.11+
- Type hints on all public functions
- No new dependencies without a clear reason — keep the surface small
- New endpoints follow the existing pattern in `server.py` and `services/`

## Policy engine changes

The policy engine is the most sensitive part of the codebase. If you're changing evaluation logic:
- Document the change in a comment with the reasoning
- Add a test case that would have caught the regression you're fixing
- Dry-run behavior must remain consistent with execute behavior

## Opening issues

For bugs: include the request that failed, the response you got, and the response you expected.
For features: describe the use case, not just the implementation. What are you trying to do that AgentGate doesn't support today?

## Questions

Open a GitHub Discussion or file an issue tagged `question`.
