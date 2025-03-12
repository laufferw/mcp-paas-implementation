import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

# Import your FastAPI application
from mcp_paas.server import app


@pytest.fixture
def test_client():
    """
    Create a FastAPI TestClient instance for testing HTTP endpoints.
    """
    return TestClient(app)


@pytest.fixture
def mock_model_context():
    """
    Create a mock for the MCP model context.
    """
    context = MagicMock()
    context.id = "test-context-id"
    context.model = "test-model"
    context.create_prompt.return_value = {"id": "prompt-1", "text": "test prompt"}
    context.run_inference.return_value = {"id": "completion-1", "text": "test completion"}
    return context


@pytest.fixture
def mcp_context_manager():
    """
    Create a mock for the MCP context manager with patching.
    """
    with patch("mcp_paas.server.MCPContextManager") as mock_manager:
        manager_instance = MagicMock()
        manager_instance.create_context.return_value = "test-context-id"
        manager_instance.get_context.return_value = MagicMock(
            id="test-context-id",
            model="test-model"
        )
        mock_manager.return_value = manager_instance
        yield manager_instance


@pytest.fixture
def auth_headers():
    """
    Create authentication headers for testing authenticated endpoints.
    """
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def tenant_id():
    """
    Provide a test tenant ID for multi-tenant testing.
    """
    return "test-tenant-123"


@pytest.fixture
def model_request_payload():
    """
    Create a sample model inference request payload.
    """
    return {
        "model": "test-model",
        "prompt": "Hello, how are you?",
        "parameters": {
            "temperature": 0.7,
            "max_tokens": 100
        }
    }


@pytest.fixture
def context_creation_payload():
    """
    Create a sample context creation request payload.
    """
    return {
        "model": "test-model",
        "parameters": {
            "temperature": 0.7,
            "max_tokens": 100
        },
        "metadata": {
            "user_id": "test-user",
            "session_id": "test-session"
        }
    }

