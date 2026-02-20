"""Tests for Code Mode: sandbox safety, policy integration, approval flow, audit."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from src.mcp_gateway.audit import AuditLogger
from src.mcp_gateway.codemode import ApiClient, CodeModeExecutor, CodeResult
from src.mcp_gateway.codemode_tools import CodeModeToolHandler
from src.mcp_gateway.policy import PolicyDecision, PolicyEngine, PolicyRule
from src.mcp_gateway.storage import GatewayStorage

SAMPLE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Pet Store", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {"summary": "List pets", "operationId": "listPets"},
            "post": {"summary": "Create a pet", "operationId": "createPet"},
        },
        "/pets/{petId}": {
            "get": {"summary": "Get pet by ID", "operationId": "getPet"},
        },
    },
}


@pytest.fixture
def executor() -> CodeModeExecutor:
    return CodeModeExecutor()


@pytest.fixture
def storage(tmp_path) -> GatewayStorage:
    return GatewayStorage(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def audit(storage) -> AuditLogger:
    return AuditLogger(storage=storage)


@pytest.fixture
def policy_engine(storage) -> PolicyEngine:
    return PolicyEngine(storage=storage, default_decision=PolicyDecision.DENY)


@pytest.fixture
def handler(executor, policy_engine, audit) -> CodeModeToolHandler:
    return CodeModeToolHandler(executor=executor, policy=policy_engine, audit=audit)


# --- Sandbox safety ---

class TestSandboxSafety:
    def test_blocks_import(self, executor: CodeModeExecutor):
        result = executor.search("import os", {})
        assert not result.success
        assert "not allowed" in result.error.lower()

    def test_blocks_from_import(self, executor: CodeModeExecutor):
        result = executor.search("from pathlib import Path", {})
        assert not result.success

    def test_blocks_open(self, executor: CodeModeExecutor):
        result = executor.search("open('/etc/passwd')", {})
        assert not result.success

    def test_blocks_os_access(self, executor: CodeModeExecutor):
        result = executor.search("os.system('ls')", {})
        assert not result.success

    def test_blocks_dunder_subclasses(self, executor: CodeModeExecutor):
        result = executor.search("result = ''.__class__.__subclasses__()", {})
        assert not result.success

    def test_blocks_eval(self, executor: CodeModeExecutor):
        result = executor.search("eval('1+1')", {})
        assert not result.success

    def test_blocks_exec_builtin(self, executor: CodeModeExecutor):
        result = executor.search("exec('x=1')", {})
        assert not result.success

    def test_allows_safe_code(self, executor: CodeModeExecutor):
        result = executor.search("result = [1, 2, 3]", {})
        assert result.success
        assert result.output == [1, 2, 3]

    def test_allows_print(self, executor: CodeModeExecutor):
        result = executor.search("print('hello')", {})
        assert result.success
        assert result.output == "hello"


# --- Search against OpenAPI spec ---

class TestSearch:
    def test_list_paths(self, executor: CodeModeExecutor):
        result = executor.search("result = list(spec['paths'].keys())", SAMPLE_SPEC)
        assert result.success
        assert "/pets" in result.output

    def test_get_operation(self, executor: CodeModeExecutor):
        result = executor.search(
            "result = spec['paths']['/pets']['get']['operationId']",
            SAMPLE_SPEC,
        )
        assert result.success
        assert result.output == "listPets"

    def test_spec_discovery(self, executor: CodeModeExecutor):
        code = """
endpoints = []
for path, methods in spec['paths'].items():
    for method in methods:
        endpoints.append(f"{method.upper()} {path}")
result = sorted(endpoints)
"""
        result = executor.search(code, SAMPLE_SPEC)
        assert result.success
        assert "GET /pets" in result.output


# --- Policy integration ---

class TestPolicyIntegration:
    def test_deny_by_default(self, handler: CodeModeToolHandler):
        result = handler.handle_execute(
            code="result = 'hello'",
            api_client=ApiClient("http://localhost", "t1"),
            tenant_id="t1",
            subject_id="user1",
            server_id="srv1",
        )
        assert not result["success"]
        assert "denied" in result["error"].lower()

    def test_allow_with_policy(self, handler: CodeModeToolHandler, policy_engine: PolicyEngine):
        policy_engine.add_rule(PolicyRule(
            name="allow-codemode",
            effect=PolicyDecision.ALLOW,
            actions={"codemode:execute"},
            resources={"*"},
        ))
        result = handler.handle_execute(
            code="result = 42",
            api_client=ApiClient("http://localhost", "t1"),
            tenant_id="t1",
            subject_id="user1",
            server_id="srv1",
        )
        assert result["success"]
        assert result["output"] == 42


# --- Approval flow ---

class TestApprovalFlow:
    def test_pending_approval(self, handler: CodeModeToolHandler, policy_engine: PolicyEngine):
        policy_engine.add_rule(PolicyRule(
            name="require-approval-codemode",
            effect=PolicyDecision.ALLOW,
            actions={"codemode:execute"},
            resources={"*"},
        ))
        result = handler.handle_execute(
            code="result = 'should wait'",
            api_client=ApiClient("http://localhost", "t1"),
            tenant_id="t1",
            subject_id="user1",
            server_id="srv1",
        )
        assert result.get("pending_approval") is True
        assert "event_id" in result

    def test_approve_and_execute(self, handler: CodeModeToolHandler, policy_engine: PolicyEngine, audit: AuditLogger):
        policy_engine.add_rule(PolicyRule(
            name="require-approval-codemode",
            effect=PolicyDecision.ALLOW,
            actions={"codemode:execute"},
            resources={"*"},
        ))
        pending = handler.handle_execute(
            code="result = 99",
            api_client=ApiClient("http://localhost", "t1"),
            tenant_id="t1",
            subject_id="user1",
            server_id="srv1",
        )
        event_id = pending["event_id"]

        approved = handler.approve_and_execute(
            event_id=event_id,
            api_client=ApiClient("http://localhost", "t1"),
        )
        assert approved["success"]
        assert approved["output"] == 99

        # Check audit updated
        event = audit.get_event(event_id)
        assert event.status == "completed"


# --- Audit logging ---

class TestAuditLogging:
    def test_search_is_logged(self, handler: CodeModeToolHandler, audit: AuditLogger):
        handler.handle_search(
            code="result = list(spec.keys())",
            spec=SAMPLE_SPEC,
            tenant_id="t1",
            subject_id="user1",
        )
        events = audit.list_events("t1")
        assert len(events) == 1
        assert events[0].action == "search"

    def test_denied_execute_is_logged(self, handler: CodeModeToolHandler, audit: AuditLogger):
        handler.handle_execute(
            code="result = 1",
            api_client=ApiClient("http://localhost", "t1"),
            tenant_id="t1",
            subject_id="user1",
            server_id="srv1",
        )
        events = audit.list_events("t1")
        assert len(events) == 1
        assert events[0].status == "denied"
        assert events[0].policy_decision == "deny"

    def test_execution_ms_recorded(self, handler: CodeModeToolHandler, audit: AuditLogger):
        handler.handle_search(code="result = 1", spec={}, tenant_id="t1", subject_id="u1")
        events = audit.list_events("t1")
        assert events[0].execution_ms >= 0
