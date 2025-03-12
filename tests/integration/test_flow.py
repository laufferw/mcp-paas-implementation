import os
import pytest
import requests
import time
import uuid
from typing import Dict, Any

# API Configuration
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
API_VERSION = "v1"
API_URL = f"{API_BASE_URL}/api/{API_VERSION}"


class TestMCPFlow:
    """Integration test for the complete MCP workflow."""

    @pytest.fixture(scope="class")
    def tenant_info(self) -> Dict[str, Any]:
        """Create and register a test tenant."""
        tenant_name = f"test-tenant-{uuid.uuid4()}"
        tenant_data = {
            "name": tenant_name,
            "display_name": "Test Tenant",
            "plan": "basic",
            "email": f"{tenant_name}@example.com",
        }
        
        # Register tenant
        response = requests.post(f"{API_URL}/tenants/", json=tenant_data)
        assert response.status_code == 201, f"Failed to create tenant: {response.text}"
        
        tenant_info = response.json()
        print(f"Created tenant: {tenant_info['id']}")

        # Save tenant info for cleanup
        result = {
            "tenant_id": tenant_info["id"],
            "tenant_name": tenant_name,
            "api_key": tenant_info["api_key"],
        }
        
        yield result
        
        # Cleanup: Delete tenant
        headers = {"Authorization": f"Bearer {result['api_key']}"}
        requests.delete(f"{API_URL}/tenants/{result['tenant_id']}", headers=headers)
        print(f"Cleaned up tenant: {result['tenant_id']}")

    @pytest.fixture(scope="class")
    def user_info(self, tenant_info: Dict[str, Any]) -> Dict[str, Any]:
        """Create a test user within the tenant."""
        username = f"testuser-{uuid.uuid4()}"
        user_data = {
            "username": username,
            "email": f"{username}@example.com",
            "password": "TestPassword123!",
            "full_name": "Test User",
            "role": "user",
        }
        
        headers = {"Authorization": f"Bearer {tenant_info['api_key']}"}
        
        # Create user
        response = requests.post(
            f"{API_URL}/users/", 
            json=user_data,
            headers=headers
        )
        assert response.status_code == 201, f"Failed to create user: {response.text}"
        
        user_info = response.json()
        print(f"Created user: {user_info['id']}")
        
        # Login to get user token
        login_data = {
            "username": username,
            "password": "TestPassword123!",
        }
        response = requests.post(f"{API_URL}/auth/login", json=login_data)
        assert response.status_code == 200, f"Failed to login: {response.text}"
        
        token = response.json()["access_token"]
        
        result = {
            "user_id": user_info["id"],
            "username": username,
            "token": token,
        }
        
        yield result
        
        # Cleanup: Delete user
        requests.delete(
            f"{API_URL}/users/{result['user_id']}", 
            headers=headers
        )
        print(f"Cleaned up user: {result['user_id']}")

    @pytest.fixture(scope="class")
    def context_info(self, tenant_info: Dict[str, Any], user_info: Dict[str, Any]) -> Dict[str, Any]:
        """Create a test model context."""
        context_data = {
            "name": f"test-context-{uuid.uuid4()}",
            "model_id": "gpt-3.5-turbo",
            "parameters": {
                "temperature": 0.7,
                "max_tokens": 1000
            },
            "description": "Test context for integration tests",
        }
        
        headers = {
            "Authorization": f"Bearer {user_info['token']}",
            "X-Tenant-ID": tenant_info["tenant_id"]
        }
        
        # Create context
        response = requests.post(
            f"{API_URL}/contexts/", 
            json=context_data,
            headers=headers
        )
        assert response.status_code == 201, f"Failed to create context: {response.text}"
        
        context_info = response.json()
        print(f"Created context: {context_info['id']}")
        
        # Wait for context initialization
        for _ in range(10):
            response = requests.get(
                f"{API_URL}/contexts/{context_info['id']}/status",
                headers=headers
            )
            status = response.json()["status"]
            if status == "ready":
                break
            time.sleep(2)
            print(f"Context status: {status}")
        
        assert status == "ready", f"Context did not become ready: {status}"
        
        result = {
            "context_id": context_info["id"],
            "model_id": context_data["model_id"],
        }
        
        yield result
        
        # Cleanup: Delete context
        requests.delete(
            f"{API_URL}/contexts/{result['context_id']}",
            headers=headers
        )
        print(f"Cleaned up context: {result['context_id']}")

    def test_registration_flow(self, tenant_info: Dict[str, Any]):
        """Test successful tenant registration."""
        assert tenant_info["tenant_id"], "Tenant ID should be present"
        assert tenant_info["api_key"], "API key should be present"
        
        # Verify tenant details
        headers = {"Authorization": f"Bearer {tenant_info['api_key']}"}
        response = requests.get(
            f"{API_URL}/tenants/{tenant_info['tenant_id']}",
            headers=headers
        )
        assert response.status_code == 200, f"Failed to get tenant: {response.text}"
        
        tenant_data = response.json()
        assert tenant_data["name"] == tenant_info["tenant_name"], "Tenant name should match"

    def test_user_creation_flow(self, tenant_info: Dict[str, Any], user_info: Dict[str, Any]):
        """Test successful user creation and authentication."""
        assert user_info["user_id"], "User ID should be present"
        assert user_info["token"], "User token should be present"
        
        # Verify user can access resources
        headers = {"Authorization": f"Bearer {user_info['token']}"}
        response = requests.get(f"{API_URL}/users/me", headers=headers)
        assert response.status_code == 200, f"Failed to get current user: {response.text}"
        
        user_data = response.json()
        assert user_data["username"] == user_info["username"], "Username should match"

    def test_context_creation_flow(self, tenant_info: Dict[str, Any], user_info: Dict[str, Any], context_info: Dict[str, Any]):
        """Test successful context creation."""
        assert context_info["context_id"], "Context ID should be present"
        
        headers = {
            "Authorization": f"Bearer {user_info['token']}",
            "X-Tenant-ID": tenant_info["tenant_id"]
        }
        
        # Verify context details
        response = requests.get(
            f"{API_URL}/contexts/{context_info['context_id']}",
            headers=headers
        )
        assert response.status_code == 200, f"Failed to get context: {response.text}"
        
        context_data = response.json()
        assert context_data["model_id"] == context_info["model_id"], "Model ID should match"
        assert context_data["status"] == "ready", "Context should be ready"

    def test_inference_flow(self, tenant_info: Dict[str, Any], user_info: Dict[str, Any], context_info: Dict[str, Any]):
        """Test inference execution on created context."""
        headers = {
            "Authorization": f"Bearer {user_info['token']}",
            "X-Tenant-ID": tenant_info["tenant_id"]
        }
        
        inference_data = {
            "prompt": "What is the capital of France?",
            "parameters": {
                "temperature": 0.5,
                "max_tokens": 100
            },
            "stream": False
        }
        
        # Run inference
        response = requests.post(
            f"{API_URL}/contexts/{context_info['context_id']}/inference",
            json=inference_data,
            headers=headers
        )
        assert response.status_code == 200, f"Failed to run inference: {response.text}"
        
        inference_result = response.json()
        assert "output" in inference_result, "Output should be present in inference result"
        assert "usage" in inference_result, "Usage statistics should be present"
        
        # Verify response contains relevant information about France/Paris
        assert "Paris" in inference_result["output"], "Inference output should contain Paris"
        
        print("Inference output:", inference_result["output"])
        print("Token usage:", inference_result["usage"])

    def test_error_handling(self, tenant_info: Dict[str, Any], user_info: Dict[str, Any]):
        """Test error handling for invalid requests."""
        headers = {
            "Authorization": f"Bearer {user_info['token']}",
            "X-Tenant-ID": tenant_info["tenant_id"]
        }
        
        # Test non-existent context
        response = requests.get(
            f"{API_URL}/contexts/non-existent-id",
            headers=headers
        )
        assert response.status_code == 404, "Should return 404 for non-existent context"
        
        # Test invalid parameters
        invalid_context_data = {
            "name": "test-invalid-context",
            "model_id": "non-existent-model",
            "parameters": {
                "temperature": 99.9  # Invalid temperature
            }
        }
        
        response = requests.post(
            f"{API_URL}/contexts/",
            json=invalid_context_data,
            headers=headers
        )
        assert response.status_code == 400, "Should return 400 for invalid parameters"
        
        # Test unauthorized access
        response = requests.get(
            f"{API_URL}/tenants/{tenant_info['tenant_id']}",
            headers={"Authorization": "Bearer invalid-token"}
        )
        assert response.status_code == 401, "Should return 401 for unauthorized access"

