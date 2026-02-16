from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict

from prometheus_client import Counter as PromCounter

ROUTE_DRY_RUNS = PromCounter(
    "gateway_route_dry_runs_total",
    "Total gateway dry-run route evaluations",
    ["decision"],
)


@dataclass
class GatewayMetrics:
    """Small metrics helper for gateway route planning flows."""

    counters: Counter

    @classmethod
    def create(cls) -> "GatewayMetrics":
        return cls(counters=Counter())

    def increment(self, metric: str) -> None:
        self.counters[metric] += 1

    def observe_dry_run(self, decision: str) -> None:
        self.increment("gateway_routes_dry_run")
        ROUTE_DRY_RUNS.labels(decision=decision).inc()

    def snapshot(self) -> Dict[str, int]:
        return dict(self.counters)
