import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from mcp_gateway.policy import (
    PolicyDecision,
    PolicyEngine,
    PolicyRequest,
    PolicyRule,
)
from mcp_gateway.storage import GatewayStorage


def test_policy_engine_allows_matching_rule(tmp_path) -> None:
    storage = GatewayStorage(db_path=str(tmp_path / "gw.db"))
    engine = PolicyEngine(storage=storage)
    engine.add_rule(
        PolicyRule(
            name="allow-plan",
            effect=PolicyDecision.ALLOW,
            actions={"plan"},
            resources={"gateway.server.s1"},
            tenants={"t1"},
        )
    )

    evaluation = engine.evaluate(
        PolicyRequest(action="plan", resource="gateway.server.s1", tenant_id="t1")
    )
    assert evaluation.decision == PolicyDecision.ALLOW
    assert evaluation.matched_rule == "allow-plan"
