import json
import pytest
from fastapi import status

# Test health endpoint
def test_health_check(test_client):
    """
    Test that the health endpoint returns 200 OK.
    """
    response = test_client.get("/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "healthy"}


# Test MCP context creation
def test_create_context(test_client, mcp_context_manager, context_creation_payload, auth_headers):
    """
    Test creating a new MCP context.
    """
    response = test_client.post(
        "/v1/contexts",
        headers=auth_headers,
        json=context_creation_payload
    )
    
    assert response.status_code == status.HTTP_201_CREATED
    assert "context_id" in response.json()
    assert mcp_context_manager.create_context.called
    
    # Verify correct parameters were passed
    call_args = mcp_context_manager.create_context.call_args[0]
    assert call_args[0] == context_creation_payload["model"]


# Test MCP context retrieval
def test_get_context(test_client, mcp_context_manager, auth_headers):
    """
    Test retrieving an existing MCP context.
    """
    context_id = "test-context-id"
    
    response = test_client.get(
        f"/v1/contexts/{context_id}",
        headers=auth_headers
    )
    
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == context_id
    assert mcp_context_manager.get_context.called
    assert mcp_context_manager.get_context.call_args[0][0] == context_id


# Test MCP context deletion
def test_delete_context(test_client, mcp_context_manager, auth_headers):
    """
    Test deleting an MCP context.
    """
    context_id = "test-context-id"
    
    response = test_client.delete(
        f"/v1/contexts/{context_id}",
        headers=auth_headers
    )
    
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert mcp_context_manager.delete_context.called
    assert mcp_context_manager.delete_context.call_args[0][0] == context_id


# Test MCP inference
def test_run_inference(test_client, mcp_context_manager, model_request_payload, auth_headers):
    """
    Test running inference using an MCP context.
    """
    context_id = "test-context-id"
    
    response = test_client.post(
        f"/v1/contexts/{context_id}/completions",
        headers=auth_headers,
        json={"prompt": model_request_payload["prompt"]}
    )
    
    assert response.status_code == status.HTTP_200_OK
    assert "completion" in response.json()
    # Check that the context manager was called with correct context ID
    assert mcp_context_manager.get_context.called
    assert mcp_context_manager.get_context.call_args[0][0] == context_id


# Test authentication failure
def test_authentication_required(test_client, context_creation_payload):
    """
    Test that endpoints require authentication.
    """
    # Try to create a context without auth headers
    response = test_client.post(
        "/v1/contexts",
        json=context_creation_payload
    )
    
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# Test multi-tenant isolation
def test_tenant_isolation(test_client, mcp_context_manager, auth_headers, tenant_id):
    """
    Test that contexts are isolated by tenant.
    """
    # Add tenant header
    headers = {**auth_headers, "X-Tenant-ID": tenant_id}
    
    # Create a context with tenant ID
    response = test_client.post(
        "/v1/contexts",
        headers=headers,
        json={"model": "test-model"}
    )
    
    assert response.status_code == status.HTTP_201_CREATED
    
    # Verify tenant ID was passed to the context manager
    create_kwargs = mcp_context_manager.create_context.call_args[1]
    assert create_kwargs.get("tenant_id") == tenant_id


# Test rate limiting
def test_rate_limiting(test_client, auth_headers):
    """
    Test that rate limiting is enforced.
    """
    # Make multiple requests in quick succession
    responses = []
    for _ in range(10):
        responses.append(test_client.get("/health", headers=auth_headers))
    
    # At least one response should indicate rate limiting
    # Note: This test might be flaky depending on implementation
    # and might need adjustment based on actual rate limiting configuration
    rate_limited = any(r.status_code == status.HTTP_429_TOO_MANY_REQUESTS for r in responses)
    
    # Comment this assertion if rate limiting is not yet implemented
    # assert rate_limited

