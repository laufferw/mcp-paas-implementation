import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union
from datetime import datetime, timedelta

import httpx
import psutil
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.mcp.models.models import Context, InferenceRequest, Tenant, User
from src.mcp.services.auth import AuthService

logger = logging.getLogger(__name__)

class MCPContextManager:
    """
    Model Context Platform (MCP) Context Manager Service
    
    Manages model contexts for multiple tenants, handles inference requests,
    and ensures resource isolation and monitoring.
    """

    def __init__(self, db_session: AsyncSession, auth_service: AuthService):
        """
        Initialize the context manager with database session and authentication service.
        
        Args:
            db_session: SQLAlchemy async database session
            auth_service: Authentication service for access control
        """
        self.db_session = db_session
        self.auth_service = auth_service
        self.contexts = {}  # tenant_id -> {context_id -> context_data}
        self.context_resources = {}  # context_id -> {memory, cpu, gpu}
        self.tenant_quotas = {}  # tenant_id -> {max_memory, max_contexts, etc.}
        self.cleanup_lock = asyncio.Lock()
        self.inference_locks = {}  # context_id -> asyncio.Lock()
        
        # Start periodic cleanup task
        self.cleanup_task = asyncio.create_task(self._periodic_cleanup())
        
    async def initialize(self):
        """Initialize the context manager by loading existing contexts from database."""
        logger.info("Initializing MCP Context Manager")
        try:
            # Load existing contexts from database
            contexts = await self._load_contexts_from_db()
            for context in contexts:
                await self._register_context(context)
                
            # Load tenant quotas
            tenants = await self._load_tenants_from_db()
            for tenant in tenants:
                self.tenant_quotas[tenant.id] = {
                    "max_contexts": tenant.max_contexts,
                    "max_memory": tenant.max_memory,
                    "max_cpu": tenant.max_cpu,
                    "max_gpu": tenant.max_gpu,
                    "max_requests_per_minute": tenant.max_requests_per_minute
                }
                
            logger.info(f"Initialized {len(contexts)} contexts for {len(tenants)} tenants")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize context manager: {e}")
            raise

    async def create_context(self, tenant_id: str, context_data: Dict[str, Any]) -> Context:
        """
        Create a new model context for a tenant.
        
        Args:
            tenant_id: ID of the tenant
            context_data: Data for the context including model, parameters, etc.
            
        Returns:
            Created context object
        """
        logger.info(f"Creating context for tenant {tenant_id}")
        try:
            # Check resource limits
            await self._check_resource_limits(tenant_id)
            
            # Create context in database
            context = Context(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                name=context_data.get("name", f"Context-{uuid.uuid4()}"),
                model=context_data.get("model", "default"),
                parameters=context_data.get("parameters", {}),
                status="initializing",
                metadata=context_data.get("metadata", {})
            )
            self.db_session.add(context)
            await self.db_session.commit()
            await self.db_session.refresh(context)
            
            # Register context in memory
            await self._register_context(context)
            
            # Initialize context resources
            self.context_resources[context.id] = {
                "memory": 0,
                "cpu": 0,
                "gpu": 0,
                "last_used": datetime.utcnow()
            }
            
            # Update context status to ready
            context.status = "ready"
            await self.db_session.commit()
            
            logger.info(f"Created context {context.id} for tenant {tenant_id}")
            return context
        except Exception as e:
            logger.error(f"Failed to create context for tenant {tenant_id}: {e}")
            await self.db_session.rollback()
            raise

    async def get_context(self, context_id: str, tenant_id: Optional[str] = None) -> Context:
        """
        Get a context by ID with optional tenant verification.
        
        Args:
            context_id: ID of the context
            tenant_id: Optional tenant ID for verification
            
        Returns:
            Context object if found
        """
        logger.debug(f"Getting context {context_id}")
        try:
            # Check if context exists in memory
            if tenant_id and tenant_id in self.contexts and context_id in self.contexts[tenant_id]:
                return self.contexts[tenant_id][context_id]
            
            # Get context from database
            context = await self.db_session.get(Context, context_id)
            if not context:
                logger.warning(f"Context {context_id} not found")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Context {context_id} not found"
                )
            
            # Verify tenant if specified
            if tenant_id and context.tenant_id != tenant_id:
                logger.warning(f"Context {context_id} does not belong to tenant {tenant_id}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to this context"
                )
                
            # Register context in memory if not already
            if context.tenant_id not in self.contexts or context_id not in self.contexts[context.tenant_id]:
                await self._register_context(context)
                
            return context
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get context {context_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get context: {str(e)}"
            )

    async def delete_context(self, context_id: str, tenant_id: Optional[str] = None) -> bool:
        """
        Delete a context by ID with optional tenant verification.
        
        Args:
            context_id: ID of the context
            tenant_id: Optional tenant ID for verification
            
        Returns:
            True if deleted successfully
        """
        logger.info(f"Deleting context {context_id}")
        try:
            # Get context (will verify tenant if specified)
            context = await self.get_context(context_id, tenant_id)
            
            # Clean up resources
            await self._cleanup_context_resources(context_id)
            
            # Delete from database
            await self.db_session.delete(context)
            await self.db_session.commit()
            
            # Remove from memory
            if context.tenant_id in self.contexts and context_id in self.contexts[context.tenant_id]:
                del self.contexts[context.tenant_id][context_id]
                
            if context_id in self.context_resources:
                del self.context_resources[context_id]
                
            if context_id in self.inference_locks:
                del self.inference_locks[context_id]
                
            logger.info(f"Deleted context {context_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete context {context_id}: {e}")
            await self.db_session.rollback()
            raise

    async def run_inference(
        self, 
        context_id: str, 
        input_data: Dict[str, Any], 
        user_id: str,
        tenant_id: Optional[str] = None,
        timeout: int = 60
    ) -> Dict[str, Any]:
        """
        Run inference on a model context.
        
        Args:
            context_id: ID of the context
            input_data: Input data for inference
            user_id: ID of the user making the request
            tenant_id: Optional tenant ID for verification
            timeout: Maximum time to wait for inference in seconds
            
        Returns:
            Inference results
        """
        start_time = time.time()
        logger.info(f"Running inference on context {context_id}")
        
        try:
            # Get context (will verify tenant if specified)
            context = await self.get_context(context_id, tenant_id)
            
            # Create inference lock if it doesn't exist
            if context_id not in self.inference_locks:
                self.inference_locks[context_id] = asyncio.Lock()
                
            # Track inference request in database
            inference_request = InferenceRequest(
                id=str(uuid.uuid4()),
                context_id=context_id,
                tenant_id=context.tenant_id,
                user_id=user_id,
                input_data=input_data,
                status="pending",
                created_at=datetime.utcnow()
            )
            self.db_session.add(inference_request)
            await self.db_session.commit()
            
            # Check if context is ready
            if context.status != "ready":
                logger.warning(f"Context {context_id} is not ready (status: {context.status})")
                inference_request.status = "failed"
                inference_request.error = f"Context not ready: {context.status}"
                await self.db_session.commit()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Context not ready: {context.status}"
                )
                
            # Update context and inference request status
            context.status = "running"
            inference_request.status = "running"
            await self.db_session.commit()
            
            # Set up monitoring
            resource_usage_before = self._get_current_resource_usage()
            
            # Acquire lock to ensure exclusive access to the context
            async with self.inference_locks[context_id]:
                try:
                    # Update last used timestamp
                    if context_id in self.context_resources:
                        self.context_resources[context_id]["last_used"] = datetime.utcnow()
                    
                    # Execute the inference (placeholder for actual inference)
                    # In a real implementation, this would call an ML model server or service
                    logger.debug(f"Executing inference with data: {input_data}")
                    
                    # Simulating inference execution with resource tracking
                    result = await self._execute_inference(context, input_data, timeout)
                    
                    # Measure resource usage
                    resource_usage_after = self._get_current_resource_usage()
                    memory_used = resource_usage_after["memory"] - resource_usage_before["memory"]
                    cpu_used = resource_usage_after["cpu"] - resource_usage_before["cpu"]
                    
                    # Update resource tracking
                    if context_id in self.context_resources:
                        self.context_resources[context_id]["memory"] += memory_used
                        self.context_resources[context_id]["cpu"] += cpu_used
                    
                    # Update tenant resource usage
                    await self._update_tenant_resources(context.tenant_id, {
                        "memory": memory_used,
                        "cpu": cpu_used,
                        "requests": 1
                    })
                    
                    # Update inference request with results
                    inference_request.status = "completed"
                    inference_request.completed_at = datetime.utcnow()
                    inference_request.result = result
                    inference_request.execution_time = time.time() - start_time
                    inference_request.memory_used = memory_used
                    inference_request.cpu_used = cpu_used
                    await self.db_session.commit()
                    
                    # Update context status back to ready
                    context.status = "ready"
                    await self.db_session.commit()
                    
                    logger.info(f"Completed inference on context {context_id} in {time.time() - start_time:.2f}s")
                    
                    # Add execution metadata to result
                    result["metadata"] = {
                        "execution_time": time.time() - start_time,
                        "request_id": inference_request.id,
                        "memory_used": memory_used,
                        "cpu_used": cpu_used
                    }
                    
                    return result
                    
                except asyncio.TimeoutError:
                    logger.error(f"Inference on context {context_id} timed out after {timeout}s")
                    inference_request.status = "failed"
                    inference_request.error = f"Inference timed out after {timeout}s"
                    inference_request.completed_at = datetime.utcnow()
                    context.status = "ready"  # Reset context status
                    await self.db_session.commit()
                    raise HTTPException(
                        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                        detail=f"Inference timed out after {timeout}s"
                    )
                except Exception as e:
                    logger.error(f"Inference on context {context_id} failed: {e}")
                    inference_request.status = "failed"
                    inference_request.error = str(e)
                    inference_request.completed_at = datetime.utcnow()
                    context.status = "error"  # Mark context as error
                    await self.db_session.commit()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Inference failed: {str(e)}"
                    )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to run inference on context {context_id}: {e}")
            await self.db_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to run inference: {str(e)}"
            )

    async def list_contexts(self, tenant_id: str, limit: int = 100, offset: int = 0) -> List[Context]:
        """
        List all contexts for a tenant.
        
        Args:
            tenant_id: ID of the tenant
            limit: Maximum number of contexts to return
            offset: Offset for pagination
            
        Returns:
            List of context objects
        """
        logger.debug(f"Listing contexts for tenant {tenant_id}")
        try:
            # Get contexts from database
            query = self.db_session.query(Context).filter(Context.tenant_id == tenant_id)
            count = await query.count()
            contexts = await query.offset(offset).limit(limit).all()
            
            logger.debug(f"Found {count} contexts for tenant {tenant_id}")
            return {
                "contexts": contexts,
                "total": count,
                "limit": limit,
                "offset": offset
            }
        except Exception as e:
            logger.error(f"Failed to list contexts for tenant {tenant_id}: {e}")
            raise

    async def _execute_inference(self, context: Context, input_data: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        """
        Execute inference

import asyncio
import logging
import time
import uuid
from typing import Dict, List, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MCPError(Exception):
    """Base exception class for MCP context manager errors."""
    pass


class ContextNotFoundError(MCPError):
    """Raised when a requested context is not found."""
    pass


class TenantNotFoundError(MCPError):
    """Raised when a requested tenant is not found."""
    pass


class InferenceError(MCPError):
    """Raised when an error occurs during inference."""
    pass


class ResourceExhaustedError(MCPError):
    """Raised when tenant has exhausted their resource allocation."""
    pass


@dataclass
class ContextMetadata:
    """Metadata for a context."""
    context_id: str
    tenant_id: str
    model_name: str
    created_at: datetime
    last_accessed: datetime
    parameters: Dict[str, Any]
    status: str  # 'initializing', 'ready', 'error', 'deleted'
    error_message: Optional[str] = None


class MCPContextManager:
    """
    Model Context Platform (MCP) Context Manager.
    
    This class handles model context management for multiple tenants, providing
    isolation, resource management, and lifecycle handling for ML model contexts.
    """
    
    def __init__(self):
        """Initialize the MCPContextManager."""
        # Main storage for contexts, organized by tenant_id -> context_id -> context_object
        self._contexts: Dict[str, Dict[str, Any]] = {}
        
        # Store metadata separately for quick access without loading full contexts
        self._metadata: Dict[str, Dict[str, ContextMetadata]] = {}
        
        # Locks for thread-safety (tenant-level locks)
        self._tenant_locks: Dict[str, asyncio.Lock] = {}
        
        # Thread pool for CPU-bound operations
        self._executor = ThreadPoolExecutor()
        
        # Resource tracking per tenant
        self._tenant_resources: Dict[str, Dict[str, Any]] = {}
        
        logger.info("MCPContextManager initialized")

    async def initialize(self) -> None:
        """
        Initialize the context manager system.
        
        This method should be called before using other methods to set up
        any necessary resources or connections.
        
        Returns:
            None
        
        Raises:
            MCPError: If initialization fails.
        """
        try:
            logger.info("Initializing MCPContextManager")
            # Initialize any required resources here
            # For example: database connections, caches, etc.
            
            # Set up an asyncio task for periodic cleanup of expired contexts
            asyncio.create_task(self._periodic_cleanup())
            
            logger.info("MCPContextManager initialized successfully")
        except Exception as e:
            error_msg = f"Failed to initialize MCPContextManager: {str(e)}"
            logger.error(error_msg)
            raise MCPError(error_msg) from e

    async def _get_tenant_lock(self, tenant_id: str) -> asyncio.Lock:
        """Get or create a lock for a specific tenant."""
        if tenant_id not in self._tenant_locks:
            self._tenant_locks[tenant_id] = asyncio.Lock()
        return self._tenant_locks[tenant_id]

    async def create_context(
        self, 
        tenant_id: str, 
        model_name: str, 
        parameters: Dict[str, Any] = None
    ) -> str:
        """
        Create a new model context for a specific tenant.
        
        Args:
            tenant_id: The ID of the tenant.
            model_name: The name of the model to create context for.
            parameters: Optional parameters for context creation.
            
        Returns:
            str: The ID of the newly created context.
            
        Raises:
            MCPError: If context creation fails.
            ResourceExhaustedError: If tenant has exhausted their resource allocation.
        """
        if parameters is None:
            parameters = {}
            
        context_id = str(uuid.uuid4())
        now = datetime.now()
        
        # Acquire tenant-specific lock to ensure thread safety
        lock = await self._get_tenant_lock(tenant_id)
        async with lock:
            try:
                logger.info(f"Creating context for tenant {tenant_id}, model {model_name}")
                
                # Check resource limits for tenant
                await self._check_resource_limits(tenant_id)
                
                # Initialize tenant storage if needed
                if tenant_id not in self._contexts:
                    self._contexts[tenant_id] = {}
                    self._metadata[tenant_id] = {}
                
                # Create context metadata
                metadata = ContextMetadata(
                    context_id=context_id,
                    tenant_id=tenant_id,
                    model_name=model_name,
                    created_at=now,
                    last_accessed=now,
                    parameters=parameters,
                    status="initializing"
                )
                
                # Store metadata
                self._metadata[tenant_id][context_id] = metadata
                
                # Create the actual context object (implementation details would depend on the ML framework)
                # This is a placeholder for the actual context creation
                context = {
                    "context_id": context_id,
                    "model_name": model_name,
                    "state": {},  # Internal model state
                    "parameters": parameters
                }
                
                # Store the context
                self._contexts[tenant_id][context_id] = context
                
                # Update metadata status
                metadata.status = "ready"
                
                # Update resource usage for tenant
                await self._update_tenant_resources(tenant_id, "add", context_id)
                
                logger.info(f"Context {context_id} created successfully for tenant {tenant_id}")
                return context_id
                
            except Exception as e:
                error_msg = f"Failed to create context for tenant {tenant_id}: {str(e)}"
                logger.error(error_msg)
                
                # If we've created metadata but failed later, update the status
                if tenant_id in self._metadata and context_id in self._metadata[tenant_id]:
                    self._metadata[tenant_id][context_id].status = "error"
                    self._metadata[tenant_id][context_id].error_message = str(e)
                
                if isinstance(e, ResourceExhaustedError):
                    raise
                raise MCPError(error_msg) from e

    async def get_context(self, tenant_id: str, context_id: str) -> Dict[str, Any]:
        """
        Retrieve a context by ID for a specific tenant.
        
        Args:
            tenant_id: The ID of the tenant.
            context_id: The ID of the context to retrieve.
            
        Returns:
            Dict[str, Any]: The context metadata and information.
            
        Raises:
            ContextNotFoundError: If the specified context does not exist.
            TenantNotFoundError: If the specified tenant does not exist.
        """
        try:
            logger.info(f"Retrieving context {context_id} for tenant {tenant_id}")
            
            # Check if tenant exists
            if tenant_id not in self._contexts:
                raise TenantNotFoundError(f"Tenant {tenant_id} not found")
            
            # Check if context exists
            if context_id not in self._contexts[tenant_id]:
                raise ContextNotFoundError(f"Context {context_id} not found for tenant {tenant_id}")
            
            # Update last accessed time
            if tenant_id in self._metadata and context_id in self._metadata[tenant_id]:
                self._metadata[tenant_id][context_id].last_accessed = datetime.now()
            
            # Return context metadata and relevant information (not the full internal state)
            metadata = self._metadata[tenant_id][context_id]
            context_info = {
                "context_id": context_id,
                "tenant_id": tenant_id,
                "model_name": metadata.model_name,
                "created_at": metadata.created_at.isoformat(),
                "last_accessed": metadata.last_accessed.isoformat(),
                "status": metadata.status,
                "parameters": metadata.parameters
            }
            
            logger.info(f"Successfully retrieved context {context_id} for tenant {tenant_id}")
            return context_info
            
        except (ContextNotFoundError, TenantNotFoundError) as e:
            logger.warning(str(e))
            raise
        except Exception as e:
            error_msg = f"Error retrieving context {context_id} for tenant {tenant_id}: {str(e)}"
            logger.error(error_msg)
            raise MCPError(error_msg) from e

    async def delete_context(self, tenant_id: str, context_id: str) -> bool:
        """
        Delete a context for a specific tenant.
        
        Args:
            tenant_id: The ID of the tenant.
            context_id: The ID of the context to delete.
            
        Returns:
            bool: True if the context was successfully deleted.
            
        Raises:
            ContextNotFoundError: If the specified context does not exist.
            TenantNotFoundError: If the specified tenant does not exist.
        """
        # Acquire tenant-specific lock to ensure thread safety
        lock = await self._get_tenant_lock(tenant_id)
        async with lock:
            try:
                logger.info(f"Deleting context {context_id} for tenant {tenant_id}")
                
                # Check if tenant exists
                if tenant_id not in self._contexts:
                    raise TenantNotFoundError(f"Tenant {tenant_id} not found")
                
                # Check if context exists
                if context_id not in self._contexts[tenant_id]:
                    raise ContextNotFoundError(f"Context {context_id} not found for tenant {tenant_id}")
                
                # Update metadata status before deletion
                if tenant_id in self._metadata and context_id in self._metadata[tenant_id]:
                    self._metadata[tenant_id][context_id].status = "deleted"
                
                # Perform cleanup of any resources associated with this context
                await self._cleanup_context_resources(tenant_id, context_id)
                
                # Remove the context
                del self._contexts[tenant_id][context_id]
                
                # Remove metadata
                if tenant_id in self._metadata and context_id in self._metadata[tenant_id]:
                    del self._metadata[tenant_id][context_id]
                
                # Update resource usage for tenant
                await self._update_tenant_resources(tenant_id, "remove", context_id)
                
                logger.info(f"Context {context_id} deleted successfully for tenant {tenant_id}")
                return True
                
            except (ContextNotFoundError, TenantNotFoundError) as e:
                logger.warning(str(e))
                raise
            except Exception as e:
                error_msg = f"Error deleting context {context_id} for tenant {tenant_id}: {str(e)}"
                logger.error(error_msg)
                raise MCPError(error_msg) from e

    async def run_inference(
        self, 
        tenant_id: str, 
        context_id: str, 
        input_data: Any,
        inference_parameters: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Run inference on a model context.
        
        Args:
            tenant_id: The ID of the tenant.
            context_id: The ID of the context to use.
            input_data: The input data for inference.
            inference_parameters: Optional parameters for the inference process.
            
        Returns:
            Dict[str, Any]: The inference results.
            
        Raises:
            ContextNotFoundError: If the specified context does not exist.
            TenantNotFoundError: If the specified tenant does not exist.
            InferenceError: If inference fails.
        """
        if inference_parameters is None:
            inference_parameters = {}
            
        try:
            logger.info(f"Running inference on context {context_id} for tenant {tenant_id}")
            
            # Check if tenant exists
            if tenant_id not in self._contexts:
                raise TenantNotFoundError(f"Tenant {tenant_id} not found")
            
            # Check if context exists
            if context_id not in self._contexts[tenant_id]:
                raise ContextNotFoundError(f"Context {context_id} not found for tenant {tenant_id}")
            
            # Update last accessed time
            if tenant_id in self._metadata and context_id in self._metadata[tenant_id]:
                self._metadata[tenant_id][context_id].last_accessed = datetime.now()
            
            # Get the context
            context = self._contexts[tenant_id][context_id]
            
            # Run inference in a thread pool to avoid blocking the event loop
            # This is important for CPU-intensive operations
            result = await asyncio.get_event_loop().run_in_executor(
                self._executor,
                self._run_inference_task,
                context,
                input_data,
                inference_parameters
            )
            
            logger.info(f"Inference completed successfully on context {context_id} for tenant {tenant_id}")
            return result
            
        except (ContextNotFoundError, TenantNotFoundError) as e:
            logger.warning(str(e))
            raise
        except Exception as e:
            error_msg = f"Inference failed on context {context_id} for tenant {tenant_id}: {str(e)}"
            logger.error(error_msg)
            raise InferenceError(error_msg) from e

    def _run_inference_task(
        self, 
        context: Dict[str, Any], 
        input_data: Any, 
        inference_parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Helper method to run inference in a separate thread.
        
        This is a synchronous method that will be executed in a thread pool.
        """
        # Implementation would depend on the actual ML framework being used
        # This is a placeholder implementation
        start_time = time.time()
        
        # Simulate inference process
        time.sleep(0.1)  # Simulate processing time
        
        # Placeholder for actual inference result
        result = {
            "context_id": context["context_id"],
            "model_name": context["model_name"],
            "input_shape": str(input_data),
            "output": "Simulated inference result",
            "processing_time_ms": int((time.time() - start_time) * 1000)
        }
        
        return result

    async def list_contexts(self, tenant_id: str) -> List[Dict[str, Any]]:
        """
        List all contexts for a specific tenant.
        
        Args:
            tenant_id: The ID of the tenant.
            
        Returns:
            List[Dict[str, Any]]: A list of context metadata.
            
        Raises:
            TenantNotFoundError: If the specified tenant does not exist.
        """
        try:
            logger.info(f"Listing contexts for tenant {tenant_id}")
            
            # Check if tenant exists
            if tenant_id not in self._metadata:
                raise TenantNotFoundError(f"Tenant {tenant_id} not found")
                
            # Collect contexts metadata
            contexts = []
            for context_id, metadata in self._metadata[tenant_id].items():
                contexts.append({
                    "context_id": context_id,
                    "tenant_id": tenant_id,
                    "model_name": metadata.model_name,
                    "created_at": metadata.created_at.isoformat(),
                    "last_accessed": metadata.last_accessed.isoformat(),
                    "status": metadata.status,
                    "parameters": metadata.parameters
                })
                
            logger.info(f"Found {len(contexts)} contexts for tenant {tenant_id}")
            return contexts
                
        except TenantNotFoundError as e:
            logger.warning(str(e))
            raise
        except Exception as e:
            error_msg = f"Error listing contexts for tenant {tenant_id}: {str(e)}"
            logger.error(error_msg)
            raise MCPError(error_msg) from e
            
    async def _check_resource_limits(self, tenant_id: str) -> None:
        """
        Check if a tenant has exceeded their resource limits.
        
        Args:
            tenant_id: The ID of the tenant.
            
        Raises:
            ResourceExhaustedError: If tenant has exhausted their resource allocation.
        """
        try:
            # Initialize tenant resources if not already done
            if tenant_id not in self._tenant_resources:
                self._tenant_resources[tenant_id] = {
                    "max_contexts": 10,  # Default limit, should be configurable per tenant
                    "current_contexts": 0,
                    "total_memory_mb": 0,
                    "max_memory_mb": 1000,  # Default limit, should be configurable per tenant
                    "last_updated": datetime.now()
                }
                
            # Check context count limit
            current_contexts = 0
            if tenant_id in self._contexts:
                current_contexts = len(self._contexts[tenant_id])
                
            max_contexts = self._tenant_resources[tenant_id]["max_contexts"]
            
            if current_contexts >= max_contexts:
                raise ResourceExhaustedError(
                    f"Tenant {tenant_id} has reached maximum allowed contexts ({max_contexts})"
                )
                
            # Check memory usage limit (simplified version)
            # In a real implementation, you'd track actual memory usage
            current_memory = self._tenant_resources[tenant_id]["total_memory_mb"]
            max_memory = self._tenant_resources[tenant_id]["max_memory_mb"]
            
            estimated_new_context_memory = 100  # Placeholder, would depend on model size
            
            if current_memory + estimated_new_context_memory > max_memory:
                raise ResourceExhaustedError(
                    f"Tenant {tenant_id} has exceeded maximum allowed memory ({max_memory} MB)"
                )
                
            logger.debug(f"Resource limits check passed for tenant {tenant_id}")
            
        except ResourceExhaustedError:
            # Re-raise resource errors
            raise
        except Exception as e:
            error_msg = f"Error checking resource limits for tenant {tenant_id}: {str(e)}"
            logger.error(error_msg)
            raise MCPError(error_msg) from e
            
    async def _update_tenant_resources(self, tenant_id: str, operation: str, context_id: str) -> None:
        """
        Update resource tracking for a tenant.
        
        Args:
            tenant_id: The ID of the tenant.
            operation: Either "add" or "remove" to indicate the operation.
            context_id: The ID of the context being added or removed.
            
        Raises:
            MCPError: If the update fails.
        """
        try:
            # Initialize tenant resources if not already done
            if tenant_id not in self._tenant_resources:
                self._tenant_resources[tenant_id] = {
                    "max_contexts": 10,
                    "current_contexts": 0,
                    "total_memory_mb": 0,
                    "max_memory_mb": 1000,
                    "last_updated": datetime.now()
                }
                
            # Estimated memory for this context (would depend on model size in real implementation)
            # This is a placeholder for demonstration
            estimated_context_memory = 100  # MB
            
            if operation == "add":
                self._tenant_resources[tenant_id]["current_contexts"] += 1
                self._tenant_resources[tenant_id]["total_memory_mb"] += estimated_context_memory
                logger.debug(f"Added resource usage for context {context_id} to tenant {tenant_id}")
                
            elif operation == "remove":
                self._tenant_resources[tenant_id]["current_contexts"] = max(
                    0, self._tenant_resources[tenant_id]["current_contexts"] - 1
                )
                self._tenant_resources[tenant_id]["total_memory_mb"] = max(
                    0, self._tenant_resources[tenant_id]["total_memory_mb"] - estimated_context_memory
                )
                logger.debug(f"Removed resource usage for context {context_id} from tenant {tenant_id}")
                
            # Update timestamp
            self._tenant_resources[tenant_id]["last_updated"] = datetime.now()
            
        except Exception as e:
            error_msg = f"Error updating resources for tenant {tenant_id}: {str(e)}"
            logger.error(error_msg)
            raise MCPError(error_msg) from e
            
    async def _cleanup_context_resources(self, tenant_id: str, context_id: str) -> None:
        """
        Clean up resources associated with a context.
        
        Args:
            tenant_id: The ID of the tenant.
            context_id: The ID of the context to clean up.
            
        Raises:
            MCPError: If cleanup fails.
        """
        try:
            logger.info(f"Cleaning up resources for context {context_id} (tenant {tenant_id})")
            
            # Get context (if it exists)
            context = None
            if (tenant_id in self._contexts and 
                context_id in self._contexts[tenant_id]):
                context = self._contexts[tenant_id][context_id]
            
            if context is None:
                logger.warning(f"Context {context_id} not found for cleanup")
                return
                
            # Perform actual cleanup operations based on the model framework
            # This is a placeholder for actual implementation
            # For example, release GPU memory, close file handles, etc.
            
            # For demonstration purposes, we'll just log that we're doing it
            logger.info(f"Released resources for context {context_id}")
            
        except Exception as e:
            error_msg = f"Error cleaning up resources for context {context_id}: {str(e)}"
            logger.error(error_msg)
            # We don't want to raise errors during cleanup as it might be called during error handling
            # Just log the error but don't propagate it
            
    async def _periodic_cleanup(self) -> None:
        """
        Periodically clean up expired contexts.
        This method runs as a background task.
        """
        try:
            # Default expiration time: 1 hour of inactivity
            EXPIRATION_TIME_SECONDS = 60 * 60
            
            while True:
                logger.debug("Running periodic context cleanup")
                now = datetime.now()
                contexts_to_cleanup = []
                
                # Find expired contexts across all tenants
                for tenant_id, contexts_metadata in self._metadata.items():
                    for context_id, metadata in contexts_metadata.items():
                        last_accessed = metadata.last_accessed
                        elapsed_seconds = (now - last_accessed).total_seconds()
                        
                        if elapsed_seconds > EXPIRATION_TIME_SECONDS:
                            contexts_to_cleanup.append((tenant_id, context_id))
                
                # Clean up expired contexts
                cleanup_count = 0
                for tenant_id, context_id in contexts_to_cleanup:
                    try:
                        # Get tenant lock
                        lock = await self._get_tenant_lock(tenant_id)
                        async with lock:
                            # Check if context still exists (might have been deleted already)
                            if (tenant_id in self._contexts and 
                                context_id in self._contexts[tenant_id]):
                                
                                logger.info(f"Auto-cleaning expired context {context_id} for tenant {tenant_id}")
                                
                                # Update metadata status
                                if tenant_id in self._metadata and context_id in self._metadata[tenant_id]:
                                    self._metadata[tenant_id][context_id].status = "deleted"
                                
                                # Clean up resources
                                await self._cleanup_context_resources(tenant_id, context_id)
                                
                                # Remove context
                                del self._contexts[tenant_id][context_id]
                                
                                # Remove metadata
                                if tenant_id in self._metadata and context_id in self._metadata[tenant_id]:
                                    del self._metadata[tenant_id][context_id]
                                
                                # Update resource tracking
                                await self._update_tenant_resources(tenant_id, "remove", context_id)
                                
                                cleanup_count += 1
                    
                    except Exception as e:
                        logger.error(f"Error during automatic cleanup of context {context_id}: {str(e)}")
                
                if cleanup_count > 0:
                    logger.info(f"Automatically cleaned up {cleanup_count} expired contexts")
                
                # Wait for next cleanup cycle (every 5 minutes)
                await asyncio.sleep(5 * 60)
                
        except asyncio.CancelledError:
            logger.info("Periodic cleanup task cancelled")
        except Exception as e:
            logger.error(f"Error in periodic cleanup task: {str(e)}")
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with cleanup."""
        await self.cleanup()
        
    async def cleanup(self):
        """
        Clean up all resources used by the context manager.
        This should be called before shutting down the application.
        """
        logger.info("Cleaning up MCPContextManager resources")
        
        try:
            # Clean up all contexts for all tenants
            for tenant_id in list(self._contexts.keys()):
                for context_id in list(self._contexts[tenant_id].keys()):
                    try:
                        logger.info(f"Cleaning up context {context_id} for tenant {tenant_id} during shutdown")
                        await self._cleanup_context_resources(tenant_id, context_id)
                    except Exception as e:
                        logger.error(f"Error cleaning up context {context_id}: {str(e)}")
            
            # Shutdown thread pool
            self._executor.shutdown(wait=True)
            
            logger.info("MCPContextManager cleanup completed")
        except Exception as e:
            logger.error(f"Error during MCPContextManager cleanup: {str(e)}")
            
    def __del__(self):
        """
        Destructor to ensure resources are cleaned up.
        This is a fallback if cleanup() isn't called explicitly.
        """
        # We can't use await in __del__, so we create a synchronous cleanup
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                logger.warning("MCPContextManager being destroyed without proper async cleanup")
                # Schedule cleanup task, but can't wait for it
                loop.create_task(self.cleanup())
            else:
                # If loop is not running, we're in trouble for async cleanup
                # Just do minimal synchronous cleanup
                logger.warning("MCPContextManager being destroyed without event loop running")
                self._executor.shutdown(wait=False)
        except Exception as e:
            logger.error(f"Error in MCPContextManager destructor: {str(e)}")
