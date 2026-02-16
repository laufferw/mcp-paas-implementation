from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, Optional, Set

from .storage import GatewayStorage


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyRequest:
    action: str
    resource: str
    tenant_id: Optional[str] = None
    subject_id: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyRule:
    name: str
    effect: PolicyDecision
    actions: Set[str]
    resources: Set[str]
    tenants: Optional[Set[str]] = None

    def matches(self, request: PolicyRequest) -> bool:
        action_match = request.action in self.actions or "*" in self.actions
        resource_match = request.resource in self.resources or "*" in self.resources
        tenant_match = self.tenants is None or request.tenant_id in self.tenants
        return action_match and resource_match and tenant_match


@dataclass(frozen=True)
class PolicyEvaluation:
    decision: PolicyDecision
    reason: str
    matched_rule: str | None = None


class PolicyEngine:
    """SQLite-backed typed policy evaluator for gateway operations."""

    def __init__(
        self,
        storage: GatewayStorage,
        rules: Optional[Iterable[PolicyRule]] = None,
        default_decision: PolicyDecision = PolicyDecision.DENY,
    ) -> None:
        self.storage = storage
        self.default_decision = default_decision
        if rules:
            for r in rules:
                self.add_rule(r)

    def add_rule(self, rule: PolicyRule) -> None:
        self.storage.execute(
            """
            INSERT INTO gateway_policy_rules(name, effect, actions_json, resources_json, tenants_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                effect=excluded.effect,
                actions_json=excluded.actions_json,
                resources_json=excluded.resources_json,
                tenants_json=excluded.tenants_json
            """,
            (
                rule.name,
                rule.effect.value,
                json.dumps(sorted(rule.actions)),
                json.dumps(sorted(rule.resources)),
                json.dumps(sorted(rule.tenants)) if rule.tenants is not None else None,
            ),
        )

    def remove_rule(self, name: str) -> None:
        self.storage.execute("DELETE FROM gateway_policy_rules WHERE name = ?", (name,))

    def list_rules(self) -> list[PolicyRule]:
        rows = self.storage.query_all("SELECT * FROM gateway_policy_rules ORDER BY rowid")
        rules: list[PolicyRule] = []
        for row in rows:
            tenants_raw = row["tenants_json"]
            rules.append(
                PolicyRule(
                    name=row["name"],
                    effect=PolicyDecision(row["effect"]),
                    actions=set(json.loads(row["actions_json"] or "[]")),
                    resources=set(json.loads(row["resources_json"] or "[]")),
                    tenants=set(json.loads(tenants_raw)) if tenants_raw else None,
                )
            )
        return rules

    def evaluate(self, request: PolicyRequest) -> PolicyEvaluation:
        for rule in self.list_rules():
            if rule.matches(request):
                reason = f"{rule.effect.value} by rule '{rule.name}'"
                return PolicyEvaluation(decision=rule.effect, reason=reason, matched_rule=rule.name)

        return PolicyEvaluation(
            decision=self.default_decision,
            reason=f"{self.default_decision.value} by default policy",
        )

    def is_allowed(self, request: PolicyRequest) -> bool:
        return self.evaluate(request).decision == PolicyDecision.ALLOW
