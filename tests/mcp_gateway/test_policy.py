import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from mcp_gateway.policy import (
    PolicyDecision,
    PolicyEngine,
    PolicyRequest,
    PolicyRule,
)
from mcp_gateway.storage import GatewayStorage


def test_policy_engine_allows_matching_rule(tmp_path):
    storage = GatewayStorage(db_path=str(tmp_path / "gw.db"))
    engine = PolicyEngine(storage=storage)
    engine.add_rule(
        PolicyRule(
            name="allow_route_plan",
            effect=PolicyDecision.ALLOW,
            actions={"plan"},
            resources={"gateway.routes"},
            tenants={"tenant-a"},
        )
    )

    request = PolicyRequest(
        action="plan",
        resource="gateway.routes",
        tenant_id="tenant-a",
    )

    assert engine.evaluate(request).decision == PolicyDecision.ALLOW
    assert engine.is_allowed(request) is True


def test_policy_engine_denies_non_matching_tenant(tmp_path):
    storage = GatewayStorage(db_path=str(tmp_path / "gw.db"))
    engine = PolicyEngine(storage=storage)
    engine.add_rule(
        PolicyRule(
            name="allow_route_plan",
            effect=PolicyDecision.ALLOW,
            actions={"plan"},
            resources={"gateway.routes"},
            tenants={"tenant-a"},
        )
    )

    request = PolicyRequest(
        action="plan",
        resource="gateway.routes",
        tenant_id="tenant-b",
    )

    assert engine.evaluate(request).decision == PolicyDecision.DENY
    assert engine.is_allowed(request) is False
