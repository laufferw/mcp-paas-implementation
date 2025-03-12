import os
import asyncio
import pytest
import pytest_asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any, Optional
from unittest.mock import patch, MagicMock
import concurrent.futures

# Import the services and utilities created
from services.context_manager import MCPContextManager
from services.auth import AuthService, PermissionDeniedError, UserNotFoundError
from utils.rate_limiter import RateLimiter

# Assuming these are available in our implementation
from scripts.init_db import init_database, seed_initial_data, Base, engine, SessionLocal
from prometheus_client import REGISTRY, Counter, Gauge, Histogram

# Setup pytest marks and configurations
pytestmark = pytest.mark.asyncio

# Test constants
TEST_ADMIN_EMAIL = "admin@test.com"
TEST_ADMIN_PASSWORD = "Admin123!"
TEST_TENANT_NAME = "TestTenant"
TEST_USER_EMAIL = "user@test.com"
TEST_USER_PASSWORD = "User123!"


# Database Fixtures
@pytest.fixture(scope="session")
def setup_database():
    """Set up a test database and seed it with initial data."""
    # Create test database tables
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    
    # Seed initial data
    seed_initial_data()
    
    yield
    
    # Teardown - clean up database
    Base.metadata.drop_all(bind=engine)
    print("Test database cleaned up")


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# Authentication Fixtures
@pytest_asyncio.fixture
async def auth_service(setup_database):
    """Create and initialize the authentication service."""
    auth = AuthService()
    await auth.initialize()
    return auth


@pytest_asyncio.fixture
async def admin_token(auth_service):
    """Get an admin authentication token."""
    token = await auth_service.login(TEST_ADMIN_EMAIL, TEST_ADMIN_PASSWORD)
    return token


@pytest_asyncio.fixture
async def test_tenant(auth_service, admin_token):
    """Create a test tenant for isolation."""
    tenant = await auth_service.register_tenant(
        name=TEST_TENANT_NAME,
        admin_email=TEST_USER_EMAIL,
        admin_password=TEST_USER_PASSWORD,
        plan="standard",
        token=admin_token
    )
    return tenant


@pytest_asyncio.fixture
async def user_token(auth_service):
    """Get a regular user authentication token."""
    token = await auth_service.login(TEST_USER_EMAIL, TEST_USER_PASSWORD)
    return token


# Context Manager Fixtures
@pytest_asyncio.fixture
async def context_manager():
    """Create and initialize the context manager."""
    manager = MCPContextManager()
    await manager.initialize()
    
    # Clean up method to be called after tests
    async def cleanup():
        contexts = getattr(manager, "_contexts", {})
        for tenant_id, tenant_contexts in contexts.items():
            for context_id in list(tenant_contexts.keys()):
                try:
                    await manager.delete_context(tenant_id, context_id)
                except Exception as e:
                    print(f"Failed to clean up context {context_id}: {e}")
        await manager._cleanup_resources()
    
    # Add cleanup to the fixture
    yield manager
    
    # Run cleanup
    loop = asyncio.get_event_loop()
    loop.run_until_complete(cleanup())
    print("Context manager resources cleaned up")


# Rate Limiter Fixtures
@pytest_asyncio.fixture
async def rate_limiter():
    """Create and initialize the rate limiter."""
    limiter = RateLimiter()
    await limiter.initialize()
    
    yield limiter
    
    # Cleanup rate limiter resources
    await limiter._cleanup_resources()
    print("Rate limiter resources cleaned up")


@pytest.mark.usefixtures("setup_database")
class TestMCPIntegration:
    """Integration tests for the MCP PaaS implementation."""

    # Authentication and Authorization Tests
    async def test_tenant_registration(self, auth_service, admin_token):
        """Test tenant registration process."""
        # Register a new tenant
        tenant_name = f"TestTenant-{int(time.time())}"
        tenant = await auth_service.register_tenant(
            name=tenant_name,
            admin_email=f"admin@{tenant_name.lower()}.com",
            admin_password="SecurePass123!",
            plan="basic",
            token=admin_token
        )
        
        assert tenant is not None
        assert tenant["name"] == tenant_name
        assert tenant["status"] == "active"
        
        # Verify the tenant exists in the system
        tenants = await auth_service.list_tenants(admin_token)
        assert any(t["name"] == tenant_name for t in tenants)

    async def test_user_authentication(self, auth_service, test_tenant):
        """Test user authentication flow."""
        # Test successful login
        token = await auth_service.login(TEST_USER_EMAIL, TEST_USER_PASSWORD)
        assert token is not None
        
        # Validate the token
        user_data = await auth_service.validate_token(token)
        assert user_data["email"] == TEST_USER_EMAIL
        assert user_data["tenant_id"] == test_tenant["id"]
        
        # Test failed login
        with pytest.raises(UserNotFoundError):
            await auth_service.login("nonexistent@example.com", "wrongpass")
        
        # Test password reset functionality
        reset_token = await auth_service.create_password_reset_token(TEST_USER_EMAIL)
        assert reset_token is not None
        
        # Complete password reset
        new_password = "NewPass456!"
        success = await auth_service.reset_password(reset_token, new_password)
        assert success is True
        
        # Login with new password should work
        token = await auth_service.login(TEST_USER_EMAIL, new_password)
        assert token is not None
        
        # Reset back to original password for other tests
        await auth_service.update_user_password(
            user_id=user_data["id"], 
            new_password=TEST_USER_PASSWORD,
            token=token
        )

    async def test_authorization_rbac(self, auth_service, admin_token, user_token, test_tenant):
        """Test role-based access control functionality."""
        # Create a new role with limited permissions
        viewer_role = await auth_service.create_role(
            name="viewer",
            permissions=["read:contexts"],
            tenant_id=test_tenant["id"],
            token=admin_token
        )
        
        # Create a new user with the viewer role
        viewer_email = f"viewer-{int(time.time())}@example.com"
        viewer = await auth_service.register_user(
            email=viewer_email,
            password="Viewer123!",
            tenant_id=test_tenant["id"],
            roles=[viewer_role["id"]],
            token=admin_token
        )
        
        # Login as viewer
        viewer_token = await auth_service.login(viewer_email, "Viewer123!")
        
        # Viewer should be able to access read operations
        assert await auth_service.check_permission(viewer_token, "read:contexts") is True
        
        # Viewer should not be able to access write operations
        assert await auth_service.check_permission(viewer_token, "write:contexts") is False
        
        # Admin user should have all permissions
        assert await auth_service.check_permission(admin_token, "write:contexts") is True
        assert await auth_service.check_permission(admin_token, "delete:tenants") is True
        
        # Regular tenant user should have tenant-specific permissions
        assert await auth_service.check_permission(user_token, "write:contexts") is True
        assert await auth_service.check_permission(user_token, "delete:tenants") is False

    # Context Manager Tests
    async def test_context_creation_lifecycle(self, context_manager, auth_service, user_token):
        """Test the entire lifecycle of a model context."""
        # Get user and tenant info
        user_data = await auth_service.validate_token(user_token)
        tenant_id = user_data["tenant_id"]
        
        # Create a new context
        context_params = {
            "model_name": "gpt-4",
            "parameters": {"temperature": 0.7, "max_tokens": 1000},
            "metadata": {"purpose": "testing"}
        }
        
        context_id = await context_manager.create_context(
            tenant_id=tenant_id,
            user_id=user_data["id"],
            params=context_params
        )
        
        assert context_id is not None
        
        # Get the context and verify its properties
        context = await context_manager.get_context(tenant_id, context_id)
        assert context is not None
        assert context["id"] == context_id
        assert context["model_name"] == "gpt-4"
        assert context["status"] == "ready"
        
        # Run inference on the context
        inference_result = await context_manager.run_inference(
            tenant_id=tenant_id,
            context_id=context_id,
            input_data={"prompt": "Hello, world!"}
        )
        
        assert inference_result is not None
        assert "output" in inference_result
        
        # List all contexts for the tenant
        contexts = await context_manager.list_contexts(tenant_id)
        assert len(contexts) >= 1
        assert any(c["id"] == context_id for c in contexts)
        
        # Delete the context
        deleted = await context_manager.delete_context(tenant_id, context_id)
        assert deleted is True
        
        # Verify the context is gone
        with pytest.raises(Exception):  # Assuming some exception type for not found
            await context_manager.get_context(tenant_id, context_id)

    async def test_context_resource_isolation(self, context_manager, auth_service, admin_token, user_token):
        """Test tenant isolation for contexts."""
        # Create contexts for two different tenants
        admin_data = await auth_service.validate_token(admin_token)
        user_data = await auth_service.validate_token(user_token)
        
        admin_tenant_id = admin_data["tenant_id"]
        user_tenant_id = user_data["tenant_id"]
        
        # Create context for admin tenant
        admin_context_id = await context_manager.create_context(
            tenant_id=admin_tenant_id,
            user_id=admin_data["id"],
            params={"model_name": "gpt-3.5-turbo", "parameters": {}}
        )
        
        # Create context for user tenant
        user_context_id = await context_manager.create_context(
            tenant_id=user_tenant_id,
            user_id=user_data["id"],
            params={"model_name": "gpt-3.5-turbo", "parameters": {}}
        )
        
        # Verify admin can access their context
        admin_context = await context_manager.get_context(admin_tenant_id, admin_context_id)
        assert admin_context["id"] == admin_context_id
        
        # Verify user can access their context
        user_context = await context_manager.get_context(user_tenant_id, user_context_id)
        assert user_context["id"] == user_context_id
        
        # Verify cross-tenant isolation - user cannot access admin context
        with pytest.raises(Exception):  # Assuming some exception type for unauthorized
            await context_manager.get_context(user_tenant_id, admin_context_id)
        
        # Verify cross-tenant isolation - admin cannot access user context
        with pytest.raises(Exception):  # Assuming some exception type for unauthorized
            await context_manager.get_context(admin_tenant_id, user_context_id)
        
        # Clean up
        await context_manager.delete_context(admin_tenant_id, admin_context_id)
        await context_manager.delete_context(user_tenant_id, user_context_id)

    # Database Tests
    async def test_database_operations(self, db_session, auth_service, admin_token):
        """Test database operations and persistence."""
        # Create a test entity via the Auth service
        tenant_name = f"DBTestTenant-{int(time.time())}"
        tenant = await auth_service.register_tenant(
            name=tenant_name,
            admin_email=f"admin@{tenant_name.lower()}.com",
            admin_password="SecurePass123!",
            plan="premium",
            token=admin_token
        )
        
        # Verify the entity exists in the database directly
        db_tenant = db_session.query(Tenant).filter_by(id=tenant["id"]).first()
        assert db_tenant is not None
        assert db_tenant.name == tenant_name
        assert db_tenant.plan == "premium"
        
        # Update the entity via the Auth service
        updated = await auth_service.update_tenant(
            tenant_id=tenant["id"],
            data={"plan": "enterprise"},
            token=admin_token
        )
        assert updated is True
        
        # Verify the update is reflected in the database
        db_session.refresh(db_tenant)
        assert db_tenant.plan == "enterprise"
        
        # Delete the entity
        deleted = await auth_service.delete_tenant(tenant["id"], admin_token)
        assert deleted is True
        
        # Verify it's gone from the database
        db_tenant = db_session.query(Tenant).filter_by(id=tenant["id"]).first()
        assert db_tenant is None or db_tenant.status == "deleted"

    # Rate Limiter Tests
    async def test_rate_limiting(self, rate_limiter, auth_service, user_token):
        """Test rate limiting functionality."""
        user_data = await auth_service.validate_token(user_token)
        tenant_id = user_data["tenant_id"]
        user_id = user_data["id"]
        
        # Configure a strict rate limit for testing
        rate_key = f"test_operation:{tenant_id}:{user_id}"
        limit = 5
        window = 60  # seconds
        
        # Should succeed under the limit
        for i in range(limit):
            allowed, current, reset_time = await rate_limiter.check_rate_limit(
                key=rate_key,
                limit=limit,
                window=window
            )
            assert allowed is True
            assert current == i + 1
        
        # Should be denied after reaching the limit
        allowed, current, reset_time = await rate_limiter.check_rate_limit(
            key=rate_key,
            limit=limit,
            window=window
        )
        assert allowed is False
        assert current > limit
        assert reset_time > time.time()
        
        # Test tenant-wide rate limiting
        tenant_key = f"tenant_operation:{tenant_id}"
        tenant_limit = 10
        
        # Should succeed under the tenant limit
        for i in range(tenant_limit):
            allowed, current, reset_time = await rate_limiter.check_rate_limit(
                key=tenant_key,
                limit=tenant_limit,
                window=window
            )
            assert allowed is True
        
        # Should be denied after reaching the tenant limit
        allowed, current, reset_time = await rate_limiter.check_rate_limit(
            key=tenant_key,
            limit=tenant_limit,
            window=window
        )
        assert allowed is False

    async def test_resource_quota_enforcement(self, context_manager, auth_service, user_token):
        """Test enforcement of resource quotas."""
        user_data = await auth_service.validate_token(user_token)
        tenant_id = user_data["tenant_id"]
        user_id = user_data["id"]
        
        # Get current tenant quota info
        tenant_info = await auth_service.get_tenant(tenant_id)
        max_contexts = tenant_info["quotas"]["max_contexts"]
        
        # Create contexts up to the limit
        context_ids = []
        for i in range(max_contexts):
            context_id = await context_manager.create_context(
                tenant_id=tenant_id,
                user_id=user_id,
                params={"model_name": "gpt-3.5-turbo", "parameters": {"purpose": f"test-{i}"}}
            )
            context_ids.append(context_id)
            
        # Verify we've reached the limit
        assert len(context_ids) == max_contexts
        
        # Attempt to create one more context beyond the limit
        with pytest.raises(Exception) as excinfo:  # Should raise a quota exceeded error
            await context_manager.create_context(
                tenant_id=tenant_id,
                user_id=user_id,
                params={"model_name": "gpt-3.5-turbo", "parameters": {"purpose": "over-limit"}}
            )
        
        # Verify the error message indicates quota exceeded
        assert "quota" in str(excinfo.value).lower() or "limit" in str(excinfo.value).lower()
        
        # Test other quota limits if available (tokens, requests, etc.)
        if "max_tokens_per_minute" in tenant_info["quotas"]:
            max_tokens = tenant_info["quotas"]["max_tokens_per_minute"]
            
            # Create a context for token testing
            test_context_id = context_ids[0]  # Use first context created above
            
            # Run inference requests until we approach the token limit
            tokens_used = 0
            requests_made = 0
            max_test_requests = 10  # Safeguard to prevent infinite loop
            
            while tokens_used < max_tokens and requests_made < max_test_requests:
                inference_result = await context_manager.run_inference(
                    tenant_id=tenant_id,
                    context_id=test_context_id,
                    input_data={"prompt": "Generate a response using exactly 50 tokens."}
                )
                
                tokens_used += inference_result.get("usage", {}).get("total_tokens", 50)
                requests_made += 1
            
            # If we've used most of our tokens, the next request should be rejected
            if tokens_used >= max_tokens * 0.9:  # If we're at 90% of the limit
                with pytest.raises(Exception) as excinfo:
                    await context_manager.run_inference(
                        tenant_id=tenant_id,
                        context_id=test_context_id,
                        input_data={"prompt": "This request should exceed the token quota."}
                    )
                assert "quota" in str(excinfo.value).lower() or "limit" in str(excinfo.value).lower()
        
        # Clean up created contexts
        for context_id in context_ids:
            await context_manager.delete_context(tenant_id, context_id)

    async def test_monitoring_metrics(self, context_manager, auth_service, user_token, rate_limiter):
        """Test monitoring and metrics collection."""
        user_data = await auth_service.validate_token(user_token)
        tenant_id = user_data["tenant_id"]
        user_id = user_data["id"]
        
        # Create a test context for metrics testing
        context_id = await context_manager.create_context(
            tenant_id=tenant_id,
            user_id=user_id,
            params={"model_name": "gpt-3.5-turbo", "parameters": {"purpose": "metrics-test"}}
        )
        
        # Execute operations that should generate metrics
        await context_manager.run_inference(
            tenant_id=tenant_id,
            context_id=context_id,
            input_data={"prompt": "Hello, generate some metrics!"}
        )
        
        # Check if metrics are being captured
        # Method 1: Direct registry check
        metrics = []
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                if 'tenant_id' in sample.labels and sample.labels['tenant_id'] == str(tenant_id):
                    metrics.append((sample.name, sample.value, sample.labels))
        
        # Verify we have tenant-specific metrics
        assert len(metrics) > 0, "No tenant-specific metrics found"
        
        # Find specific metrics we expect
        found_request_count = False
        found_latency_metric = False
        found_token_usage = False
        
        for name, value, labels in metrics:
            if 'request_count' in name and labels.get('operation') == 'run_inference':
                found_request_count = True
                assert value >= 1, "Request count metric should be at least 1"
            
            if 'latency_seconds' in name and labels.get('operation') == 'run_inference':
                found_latency_metric = True
                assert value > 0, "Latency metric should be greater than 0"
            
            if 'token_usage' in name:
                found_token_usage = True
                assert value > 0, "Token usage metric should be greater than 0"
        
        # Assert that we found the expected metrics
        assert found_request_count, "Request count metric not found"
        assert found_latency_metric, "Latency metric not found"
        assert found_token_usage, "Token usage metric not found"
        
        # Test rate limiter metrics
        rate_key = f"metrics_test:{tenant_id}:{user_id}"
        for i in range(5):
            await rate_limiter.check_rate_limit(key=rate_key, limit=10, window=60)
        
        # Check rate limiter metrics
        rate_limit_metrics = []
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                if 'rate_limit' in sample.name:
                    rate_limit_metrics.append((sample.name, sample.value, sample.labels))
        
        assert len(rate_limit_metrics) > 0, "No rate limit metrics found"
        
        # Clean up
        await context_manager.delete_context(tenant_id, context_id)

    async def test_system_performance_under_load(self, context_manager, auth_service, user_token):
        """Test system performance under load conditions."""
        user_data = await auth_service.validate_token(user_token)
        tenant_id = user_data["tenant_id"]
        user_id = user_data["id"]
        
        # Create a test context for performance testing
        context_id = await context_manager.create_context(
            tenant_id=tenant_id,
            user_id=user_id,
            params={"model_name": "gpt-3.5-turbo", "parameters": {"purpose": "performance-test"}}
        )
        
        # Number of concurrent requests to simulate load
        num_concurrent_requests = 10
        
        # Function to execute for each request
        async def run_inference_request(request_id):
            try:
                start_time = time.time()
                result = await context_manager.run_inference(
                    tenant_id=tenant_id,
                    context_id=context_id,
                    input_data={"prompt": f"This is concurrent request {request_id}"}
                )
                end_time = time.time()
                return {
                    "request_id": request_id,
                    "success": True,
                    "latency": end_time - start_time,
                    "result": result
                }
            except Exception as e:
                return {
                    "request_id": request_id,
                    "success": False,
                    "error": str(e)
                }
        
        # Create tasks for concurrent execution
        tasks = [run_inference_request(i) for i in range(num_concurrent_requests)]
        results = await asyncio.gather(*tasks)
        
        # Analyze results
        successful_requests = [r for r in results if r["success"]]
        failed_requests = [r for r in results if not r["success"]]
        
        # Calculate statistics
        success_rate = len(successful_requests) / num_concurrent_requests
        avg_latency = sum(r["latency"] for r in successful_requests) / len(successful_requests) if successful_requests else 0
        
        # Calculate additional statistics
        if successful_requests:
            latencies = [r["latency"] for r in successful_requests]
            min_latency = min(latencies)
            max_latency = max(latencies)
            p95_latency = sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) >= 20 else max_latency
        else:
            min_latency = max_latency = p95_latency = 0
        
        # Performance assertions
        assert success_rate >= 0.9, f"Success rate {success_rate} is below acceptable threshold of 0.9"
        assert avg_latency < 2.0, f"Average latency {avg_latency}s exceeds acceptable threshold of 2.0s"
        assert max_latency < 5.0, f"Maximum latency {max_latency}s exceeds acceptable threshold of 5.0s"
        
        # Log performance statistics
        print(f"Performance test results:")
        print(f"  Success rate: {success_rate:.2f}")
        print(f"  Average latency: {avg_latency:.3f}s")
        print(f"  Min/Max latency: {min_latency:.3f}s / {max_latency:.3f}s")
        print(f"  P95 latency: {p95_latency:.3f}s")
        print(f"  Failed requests: {len(failed_requests)}")
        
        # Clean up
        await context_manager.delete_context(tenant_id, context_id)

    async def test_error_handling_and_recovery(self, context_manager, auth_service, user_token):
        """Test system error handling and recovery mechanisms."""
        user_data = await auth_service.validate_token(user_token)
        tenant_id = user_data["tenant_id"]
        user_id = user_data["id"]
        
        # Create a test context
        context_id = await context_manager.create_context(
            tenant_id=tenant_id,
            user_id=user_id,
            params={"model_name": "gpt-3.5-turbo", "parameters": {"purpose": "error-test"}}
        )
        
        # Test case 1: Invalid input parameter handling
        try:
            await context_manager.run_inference(
                tenant_id=tenant_id,
                context_id=context_id,
                input_data={"invalid_key": "This should cause a validation error"}
            )
            assert False, "Expected exception was not raised for invalid input"
        except Exception as e:
            # Verify the error is properly handled and contains useful information
            error_str = str(e).lower()
            assert "input" in error_str or "validation" in error_str or "parameter" in error_str
        
        # Test case 2: Invalid context ID handling
        non_existent_id = "context-" + str(uuid.uuid4())
        try:
            await context_manager.get_context(tenant_id, non_existent_id)
            assert False, "Expected exception was not raised for non-existent context"
        except Exception as e:
            # Verify the error is properly handled
            error_str = str(e).lower()
            assert "not found" in error_str or "does not exist" in error_str or "invalid" in error_str
        
        # Test case 3: Simulate model error and recovery
        with patch.object(context_manager, '_execute_model_call', side_effect=Exception("Simulated model failure")):
            # First attempt should fail
            try:
                await context_manager.run_inference(
                    tenant_id=tenant_id,
                    context_id=context_id,
                    input_data={"prompt": "Test prompt that will fail"}
                )
                assert False, "Expected exception was not raised during simulated failure"
            except Exception:
                pass  # Expected to fail
            
            # Check context health - should show error state
            context = await context_manager.get_context(tenant_id, context_id)
            assert context["status"] in ["error", "failed", "unhealthy"]
            
            # Trigger recovery mechanism (this would normally happen automatically)
            await context_manager._repair_context(tenant_id, context_id)
            
            # Verify context is restored to healthy state
            context = await context_manager.get_context(tenant_id, context_id)
            assert context["status"] in ["ready", "healthy", "available"]
        
        # Test case 4: Verify request retry works
        with patch.object(context_manager, '_execute_model_call') as mock_call:
            # Configure the mock to fail twice then succeed
            mock_call.side_effect = [
                Exception("First failure"),
                Exception("Second failure"),
                {"output": "Success after retry", "usage": {"total_tokens": 5}}
            ]
            
            # Run inference with retry logic
            result = await context_manager.run_inference(
                tenant_id=tenant_id,
                context_id=context_id,
                input_data={"prompt": "Test prompt with retry"},
                retry_count=3  # Allow up to 3 retries
            )
            
            # Verify we got a successful result after retries
            assert result is not None
            assert "output" in result
            assert "Success after retry" in result["output"]
            
            # Verify the method was called the expected number of times
            assert mock_call.call_count == 3
        
        # Clean up
        await context_manager.delete_context(tenant_id, context_id)

    async def test_concurrent_resource_access(self, context_manager, auth_service, user_token):
        """Test concurrent access to shared resources."""
        user_data = await auth_service.validate_token(user_token)
        tenant_id = user_data["tenant_id"]
        user_id = user_data["id"]
        
        # Create a shared context that multiple "users" will access
        shared_context_id = await context_manager.create_context(
            tenant_id=tenant_id,
            user_id=user_id,
            params={"model_name": "gpt-3.5-turbo", "parameters": {"purpose": "concurrency-test"}}
        )
        
        # Number of concurrent operations
        num_concurrent = 20
        
        # Define different operations to perform concurrently
        async def read_context(op_id):
            try:
                return await context_manager.get_context(tenant_id, shared_context_id)
            except Exception as e:
                return {"error": str(e), "op_id": op_id}
        
        async def update_context(op_id):
            try:
                # Simulate a context update operation
                updated = await context_manager._update_context_metadata(
                    tenant_id=tenant_id,
                    context_id=shared_context_id,
                    metadata={"updated_by": f"concurrent-op-{op_id}", "timestamp": time.time()}
                )
                return {"updated": updated, "op_id": op_id}
            except Exception as e:
                return {"error": str(e), "op_id": op_id}
        
        async def run_inference(op_id):
            try:
                result = await context_manager.run_inference(
                    tenant_id=tenant_id,
                    context_id=shared_context_id,
                    input_data={"prompt": f"Concurrent inference request {op_id}"}
                )
                return {"result": result, "op_id": op_id}
            except Exception as e:
                return {"error": str(e), "op_id": op_id}
        
        # Create a mix of operations
        operations = []
        for i in range(num_concurrent):
            if i % 3 == 0:
                operations.append(read_context(i))
            elif i % 3 == 1:
                operations.append(update_context(i))
            else:
                operations.append(run_inference(i))
        
        # Execute all operations concurrently
        start_time = time.time()
        results = await asyncio.gather(*operations, return_exceptions=True)
        end_time = time.time()
        
        # Analyze results
        successful_ops = [r for r in results if not isinstance(r, Exception) and "error" not in r]
        failed_ops = [r for r in results if isinstance(r, Exception) or "error" in r]
        
        # Assertions
        assert len(successful_ops) >= num_concurrent * 0.8, "Too many operations failed under concurrent load"
        
        # Check if the context is still in a valid state after concurrent access
        final_context = await context_manager.get_context(tenant_id, shared_context_id)
        assert final_context["status"] in ["ready", "healthy", "available"], "Context is in an invalid state after concurrent access"
        
        # Verify we can still use the context after concurrent operations
        final_inference = await context_manager.run_inference(
            tenant_id=tenant_id,
            context_id=shared_context_id,
            input_data={"prompt": "Final verification after concurrent operations"}
        )
        assert "output" in final_inference, "Context is unusable after concurrent operations"
        
        # Log results
        print(f"Concurrent resource access test:")
        print(f"  Total operations: {num_concurrent}")
        print(f"  Successful: {len(successful_ops)}")
        print(f"  Failed: {len(failed_ops)}")
        print(f"  Total execution time: {end_time - start_time:.3f}s")
        
        # Clean up
        await context_manager.delete_context(tenant_id, shared_context_id)

    async def test_system_health_monitoring(self, context_manager, auth_service, user_token, rate_limiter):
        """Test system health monitoring and alerts."""
        user_data = await auth_service.validate_token(user_token)
        tenant_id = user_data["tenant_id"]
        user_id = user_data["id"]
        
        # Setup test logging handler to capture alert logs
        test_log_handler = MagicMock()
        root_logger = logging.getLogger()
        root_logger.addHandler(test_log_handler)
        
        try:
            # 1. Test health check functionality
            health_status = await context_manager.check_health()
            assert health_status["status"] in ["healthy", "ok", "operational"]
            assert "components" in health_status
            assert "version" in health_status
            
            # Component health checks should be included
            components = health_status["components"]
            assert "database" in components
            assert "authentication" in components
            assert "model_service" in components
            
            for component, status in components.items():
                assert status["status"] in ["healthy", "ok", "degraded", "error"]
                if status["status"] != "healthy" and status["status"] != "ok":
                    print(f"Warning: Component {component} is in {status['status']} state")
            
            # 2. Test resource usage monitoring
            # Create a context for testing
            context_id = await context_manager.create_context(
                tenant_id=tenant_id,
                user_id=user_id,
                params={"model_name": "gpt-3.5-turbo", "parameters": {"purpose": "health-monitor-test"}}
            )
            
            # Get initial resource usage
            initial_usage = await context_manager.get_resource_usage(tenant_id)
            assert "contexts" in initial_usage
            assert "tokens" in initial_usage
            assert "requests" in initial_usage
            
            # Run some operations to generate resource usage
            for i in range(3):
                await context_manager.run_inference(
                    tenant_id=tenant_id,
                    context_id=context_id,
                    input_data={"prompt": f"Health monitoring test {i}"}
                )
            
            # Get updated resource usage
            updated_usage = await context_manager.get_resource_usage(tenant_id)
            
            # Verify usage has increased
            assert updated_usage["contexts"] >= initial_usage["contexts"]
            assert updated_usage["tokens"] > initial_usage["tokens"]
            assert updated_usage["requests"] > initial_usage["requests"]
            
            # 3. Test resource threshold alerts
            # Simulate approaching a resource limit
            with patch.object(context_manager, '_check_resource_limits') as mock_check:
                # Configure the mock to indicate near-limit usage
                mock_check.return_value = {
                    "allowed": True,
                    "usage_percent": 85,  # 85% of limit
                    "resource_type": "tokens",
                    "current": 85000,
                    "limit": 100000
                }
                
                # Run an operation that should trigger a warning
                await context_manager.run_inference(
                    tenant_id=tenant_id,
                    context_id=context_id,
                    input_data={"prompt": "This should trigger a resource warning"}
                )
                
                # Verify a warning log was generated
                warning_logged = False
                for call in test_log_handler.handle.call_args_list:
                    log_record = call[0][0]
                    if log_record.levelno == logging.WARNING and "resource" in log_record.message.lower():
                        warning_logged = True
                        break
                
                assert warning_logged, "Resource warning was not logged when approaching limits"
            
            # 4. Test system metrics collection
            # Get current metrics
            metrics = []
            for metric in REGISTRY.collect():
                for sample in metric.samples:
                    if sample.name.startswith('mcp_'):
                        metrics.append((sample.name, sample.value, sample.labels))
            
            # Verify essential health metrics exist
            health_metrics = [m for m in metrics if 'health' in m[0] or 'status' in m[0]]
            assert len(health_metrics) > 0, "No health metrics found"
            
            # 5. Test cleanup verification
            # Delete the context
            deleted = await context_manager.delete_context(tenant_id, context_id)
            assert deleted is True
            
            # Verify resources were properly cleaned up
            try:
                await context_manager.get_context(tenant_id, context_id)
                assert False, "Context was not properly deleted"
            except Exception:
                pass  # Expected exception for deleted context
            
            # Check resource usage after deletion
            final_usage = await context_manager.get_resource_usage(tenant_id)
            assert final_usage["contexts"] < updated_usage["contexts"], "Context count didn't decrease after deletion"
            
        finally:
            # Remove the test log handler
            root_logger.removeHandler(test_log_handler)
