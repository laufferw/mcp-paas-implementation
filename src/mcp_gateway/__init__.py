"""MCP Gateway domain scaffolding.

This package contains incremental building blocks for evolving MCP PaaS into
an MCP Gateway + Control Plane architecture.
"""

from .policy import (
    PolicyDecision,
    PolicyEngine,
    PolicyEvaluation,
    PolicyRequest,
    PolicyRule,
)
from .registry import GatewayRegistry, RegisteredServer
from .storage import GatewayStorage
from .authz import AccessToken, AuthzStore

__all__ = [
    "PolicyDecision",
    "PolicyEngine",
    "PolicyEvaluation",
    "PolicyRequest",
    "PolicyRule",
    "GatewayRegistry",
    "RegisteredServer",
    "GatewayStorage",
    "AccessToken",
    "AuthzStore",
]
