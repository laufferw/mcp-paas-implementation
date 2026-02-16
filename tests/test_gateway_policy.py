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


def test_policy_engine_default_deny(tmp_path) -> None:
    storage = GatewayStorage(db_path=str(tmp_path / "gw.db"))
    engine = PolicyEngine(storage=storage)
    evaluation = engine.evaluate(
        PolicyRequest(action="plan", resource="gateway.server.s2", tenant_id="t2")
    )
    assert evaluation.decision == PolicyDecision.DENY


def test_policy_engine_honors_rule_order_first_match(tmp_path) -> None:
    storage = GatewayStorage(db_path=str(tmp_path / "gw.db"))
    engine = PolicyEngine(storage=storage)
    engine.add_rule(
        PolicyRule(
            name="deny-all",
            effect=PolicyDecision.DENY,
            actions={"*"},
            resources={"gateway.server.s1"},
        )
    )
    engine.add_rule(
        PolicyRule(
            name="allow-specific",
            effect=PolicyDecision.ALLOW,
            actions={"plan"},
            resources={"gateway.server.s1"},
            tenants={"t1"},
        )
    )

    evaluation = engine.evaluate(
        PolicyRequest(action="plan", resource="gateway.server.s1", tenant_id="t1")
    )
    assert evaluation.decision == PolicyDecision.DENY
    assert evaluation.matched_rule == "deny-all"
