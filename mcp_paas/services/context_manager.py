from typing import Dict, List, Optional, Any
from uuid import UUID
import asyncio
import logging
from datetime import datetime, timedelta

from mcp_paas.models.context import ModelContext, ContextStatus, ResourceUsage
from mcp_paas.models.tenant import Tenant

logger = logging.getLogger(__name__)


class MCPContextManager:
    """
    Manages the lifecycle of MCP contexts, including creation, retrieval,
    updating, and deletion. Also handles resource tracking and tenant isolation.
    """
    
    def __init__(self):
        # In-memory storage of contexts, indexed by context_id
        self._contexts: Dict[UUID, ModelContext] = {}
        # Map of tenant_id to list of context_ids
        self._tenant_contexts: Dict[UUID, List[UUID]] = {}
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()
        # Background tasks
        self._cleanup_task = None
        # Initialization flag
        self._initialized = False
    
    async def create_context(
        self, 
        tenant_id: UUID, 
        model_name: str, 
        parameters: Dict[str, Any] = None,
        ttl_minutes: Optional[int] = 60
    ) -> ModelContext:
        """
        Create a new model context for the specified tenant.
        
        Args:
            tenant_id: The ID of the tenant
            model_name: The name of the model to load
            parameters: Model-specific parameters
            ttl_minutes: Time-to-live in minutes (None for no expiry)
            
        Returns:
            The newly created ModelContext
        """
        async with self._lock:
            # Create the new context
            context = ModelContext(
                tenant_id=tenant_id,
                model_name=model_name,
                parameters=parameters or {},
                status=ContextStatus.INITIALIZING,
            )
            
            if ttl_minutes is not None:
                context.expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)
            
            # Store the context
            self._contexts[context.context_id] = context
            
            # Add to tenant's contexts
            if tenant_id not in self._tenant_contexts:
                self._tenant_contexts[tenant_id] = []
            self._tenant_contexts[tenant_id].append(context.context_id)
            
            logger.info(f"Created context {context.context_id} for tenant {tenant_id}")
            
            # Start initialization in background
            asyncio.create_task(self._initialize_context(context.context_id))
            
            return context
    
    async def _initialize_context(self, context_id: UUID) -> None:
        """
        Initialize the context by loading the model and preparing it for use.
        This is a background task that updates the context status.
        """
        context = self._contexts.get(context_id)
        if not context:
            return
        
        try:
            # Simulate model loading
            await asyncio.sleep(2)  # Placeholder for actual model loading
            
            async with self._lock:
                context.status = ContextStatus.RUNNING
                context.updated_at = datetime.utcnow()
                self._contexts[context_id] = context
                
            logger.info(f"Context {context_id} initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize context {context_id}: {str(e)}")
            async with self._lock:
                context.status = ContextStatus.ERROR
                context.updated_at = datetime.utcnow()
                self._contexts[context_id] = context
    
    async def get_context(self, context_id: UUID) -> Optional[ModelContext]:
        """
        Retrieve a context by its ID.
        
        Args:
            context_id: The ID of the context to retrieve
            
        Returns:
            The ModelContext if found, None otherwise
        """
        return self._contexts.get(context_id)
    
    async def get_tenant_contexts(self, tenant_id: UUID) -> List[ModelContext]:
        """
        Get all contexts for a specific tenant.
        
        Args:
            tenant_id: The ID of the tenant
            
        Returns:
            List of ModelContext objects for the tenant
        """
        context_ids = self._tenant_contexts.get(tenant_id, [])
        return [self._contexts[cid] for cid in context_ids if cid in self._contexts]
    
    async def delete_context(self, context_id: UUID) -> bool:
        """
        Delete a context by its ID.
        
        Args:
            context_id: The ID of the context to delete
            
        Returns:
            True if deleted, False if not found
        """
        async with self._lock:
            context = self._contexts.pop(context_id, None)
            if not context:
                return False
                
            # Remove from tenant contexts
            tenant_id = context.tenant_id
            if tenant_id in self._tenant_contexts:
                if context_id in self._tenant_contexts[tenant_id]:
                    self._tenant_contexts[tenant_id].remove(context_id)
            
            logger.info(f"Deleted context {context_id} for tenant {tenant_id}")
            return True
    
    async def update_resource_usage(
        self, 
        context_id: UUID, 
        cpu_seconds: float = 0, 
        memory_mb: float = 0,
        tokens_input: int = 0,
        tokens_output: int = 0
    ) -> bool:
        """
        Update resource usage for a context.
        
        Args:
            context_id: The ID of the context
            cpu_seconds: Additional CPU seconds used
            memory_mb: Additional memory MB used
            tokens_input: Additional input tokens processed
            tokens_output: Additional output tokens generated
            
        Returns:
            True if updated, False if context not found
        """
        async with self._lock:
            context = self._contexts.get(context_id)
            if not context:
                return False
                
            # Update usage
            context.resource_usage.cpu_seconds += cpu_seconds
            context.resource_usage.memory_mb += memory_mb
            context.resource_usage.tokens_input += tokens_input
            context.resource_usage.tokens_output += tokens_output
            context.resource_usage.last_updated = datetime.utcnow()
            context.updated_at = datetime.utcnow()
            
            self._contexts[context_id] = context
            return True
    
    async def cleanup_expired_contexts(self) -> int:
        """
        Remove expired contexts.
        
        Returns:
            Number of contexts cleaned up
        """
        now = datetime.utcnow()
        expired_contexts = []
        
        for context_id, context in self._contexts.items():
            if context.expires_at and context.expires_at < now:
                expired_contexts.append(context_id)
        
        count = 0
        for context_id in expired_contexts:
            if await self.delete_context(context_id):
                count += 1
                
        logger.info(f"Cleaned up {count} expired contexts")
        return count
    
    async def check_tenant_resources(self, tenant: Tenant) -> bool:
        """
        Check if a tenant has exceeded their resource limits.
        
        Args:
            tenant: The tenant to check
            
        Returns:
            True if within limits, False if exceeded
        """
        tenant_contexts = self._tenant_contexts.get(tenant.tenant_id, [])
        active_contexts = sum(1 for cid in tenant_contexts if cid in self._contexts and 
                             self._contexts[cid].status in [ContextStatus.RUNNING, ContextStatus.INITIALIZING])
        
        # Check concurrent contexts limit
        if active_contexts >= tenant.resource_limits.max_concurrent_contexts:
            logger.warning(f"Tenant {tenant.tenant_id} exceeded concurrent contexts limit")
            return False
            
        # In a real implementation, we would check other limits here
        return True
    async def initialize(self) -> None:
        """
        Initialize the context manager and start background tasks.
        This should be called during application startup.
        
        Raises:
            RuntimeError: If initialization fails
        """
        if self._initialized:
            logger.warning("MCPContextManager already initialized")
            return

        logger.info("Initializing MCPContextManager")
        try:
            # Start periodic cleanup of expired contexts
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            
            # Additional initialization steps could be added here:
            # - Connect to external model services
            # - Load model configurations
            # - Initialize metrics collectors
            # - Restore persisted contexts from database
            
            self._initialized = True
            logger.info("MCPContextManager initialization complete")
        except Exception as e:
            logger.error(f"Failed to initialize MCPContextManager: {str(e)}")
            # Cancel the cleanup task if it was started
            if self._cleanup_task:
                self._cleanup_task.cancel()
                self._cleanup_task = None
            raise RuntimeError(f"Context manager initialization failed: {str(e)}")

    async def shutdown(self) -> None:
        """
        Shutdown the context manager and cleanup resources.
        This should be called during application shutdown.
        
        Raises:
            RuntimeError: If shutdown fails
        """
        if not self._initialized:
            logger.warning("MCPContextManager not initialized, nothing to shut down")
            return

        logger.info("Shutting down MCPContextManager")
        try:
            # Cancel the cleanup task
            if self._cleanup_task:
                logger.debug("Canceling cleanup task")
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass
                self._cleanup_task = None
            
            # Clean up all contexts
            logger.info(f"Cleaning up {len(self._contexts)} active contexts")
            context_ids = list(self._contexts.keys())
            for context_id in context_ids:
                try:
                    await self.delete_context(context_id)
                except Exception as e:
                    logger.error(f"Error cleaning up context {context_id}: {str(e)}")
            
            # Additional cleanup steps could be added here:
            # - Close connections to external services
            # - Persist any necessary state
            # - Release resources
            
            self._initialized = False
            logger.info("MCPContextManager shutdown complete")
        except Exception as e:
            logger.error(f"Error during MCPContextManager shutdown: {str(e)}")
            raise RuntimeError(f"Context manager shutdown failed: {str(e)}")
    
    async def _periodic_cleanup(self) -> None:
        """
        Periodically clean up expired contexts.
        This runs as a background task.
        """
        logger.info("Starting periodic context cleanup task")
        try:
            while True:
                await asyncio.sleep(60)  # Check every minute
                try:
                    cleaned = await self.cleanup_expired_contexts()
                    if cleaned > 0:
                        logger.info(f"Periodic cleanup removed {cleaned} expired contexts")
                except Exception as e:
                    logger.error(f"Error in periodic context cleanup: {str(e)}")
        except asyncio.CancelledError:
            logger.info("Periodic context cleanup task cancelled")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in periodic cleanup task: {str(e)}")

