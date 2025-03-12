import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update

from mcp.models.models import User, Tenant, Context, InferenceRequest
from mcp.services.auth import AuthService
from mcp.db.session import get_db_session
from mcp.exceptions import (
    ContextNotFoundError,
    ResourceExhaustedError,
    InferenceError,
    UnauthorizedError,
    TenantNotFoundError
)

logger = logging.getLogger(__name__)

class ContextState:
    """Enum-like class for context states"""
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    ERROR = "error"
    TERMINATED = "terminated"


class MCPContextManager:
    """
    Model Context Platform Context Manager
    
    Responsible for managing model contexts across multiple tenants, including:
    - Creating, retrieving, updating, and deleting contexts
    - Managing context state
    - Running inference with proper resource isolation
    - Tracking resource usage and enforcing limits
    - Ensuring tenant isolation
    """
    
    def __init__(self, auth_service: AuthService = None, cleanup_interval: int = 3600):
        """
        Initialize the context manager
        
        Args:
            auth_service: Authentication service for checking permissions
            cleanup_interval: Interval in seconds for periodic cleanup of expired contexts
        """
        self.auth_service = auth_service or AuthService()
        self.cleanup_interval = cleanup_interval
        self.contexts: Dict[str, Dict[str, Any]] = {}  # In-memory context cache
        self.tenant_resources: Dict[str, Dict[str, Any]] = {}  # Tenant resource tracking
        self._cleanup_task = None
        self._lock = asyncio.Lock()
        
        # Start periodic cleanup
        self._start_periodic_cleanup()
        
        logger.info("Context Manager initialized")
    
    async def initialize(self):
        """Initialize the context manager and load existing contexts from database"""
        try:
            async with get_db_session() as session:
                # Load existing contexts from database
                result = await session.execute(select(Context).where(Context.state != ContextState.TERMINATED))
                db_contexts = result.scalars().all()
                
                for context in db_contexts:
                    self.contexts[context.id] = {
                        "id": context.id,
                        "tenant_id": context.tenant_id,
                        "model_id": context.model_id,
                        "state": context.state,
                        "config": context.config,
                        "created_at": context.created_at,
                        "last_used": context.updated_at,
                        "resource_usage": context.resource_usage
                    }
                    
                # Initialize tenant resource tracking
                result = await session.execute(select(Tenant))
                tenants = result.scalars().all()
                
                for tenant in tenants:
                    self.tenant_resources[tenant.id] = {
                        "active_contexts": await self._count_tenant_contexts(session, tenant.id),
                        "total_tokens": 0,
                        "inference_calls": 0,
                        "last_updated": datetime.utcnow()
                    }
            
            logger.info(f"Context Manager initialized with {len(self.contexts)} contexts")
        except Exception as e:
            logger.error(f"Failed to initialize context manager: {str(e)}")
            raise
    
    async def create_context(
        self,
        tenant_id: str,
        model_id: str,
        config: Dict[str, Any],
        user_id: str
    ) -> str:
        """
        Create a new model context
        
        Args:
            tenant_id: Tenant ID
            model_id: Model ID to load
            config: Configuration for the context
            user_id: User ID creating the context
            
        Returns:
            Context ID of the newly created context
            
        Raises:
            UnauthorizedError: If the user doesn't have permission
            ResourceExhaustedError: If tenant has reached context limit
            ValueError: If invalid parameters are provided
        """
        # Check authorization
        if not await self.auth_service.check_permission(user_id, "context:create", tenant_id):
            logger.warning(f"User {user_id} attempted to create context without permission for tenant {tenant_id}")
            raise UnauthorizedError("User does not have permission to create context")
        
        # Check resource limits
        await self._check_resource_limits(tenant_id, "contexts")
        
        context_id = str(uuid.uuid4())
        created_at = datetime.utcnow()
        
        # Create context record in database
        async with get_db_session() as session:
            # Check if tenant exists
            tenant_exists = await session.execute(
                select(Tenant).where(Tenant.id == tenant_id)
            )
            if not tenant_exists.scalar_one_or_none():
                logger.error(f"Tenant {tenant_id} not found")
                raise TenantNotFoundError(f"Tenant {tenant_id} not found")
                
            # Create context in database
            db_context = Context(
                id=context_id,
                tenant_id=tenant_id,
                model_id=model_id,
                state=ContextState.INITIALIZING,
                config=config,
                created_by=user_id,
                created_at=created_at,
                updated_at=created_at,
                resource_usage={"tokens": 0, "compute_time": 0}
            )
            session.add(db_context)
            await session.commit()
        
        # Add to in-memory cache
        async with self._lock:
            self.contexts[context_id] = {
                "id": context_id,
                "tenant_id": tenant_id,
                "model_id": model_id,
                "state": ContextState.INITIALIZING,
                "config": config,
                "created_at": created_at,
                "last_used": created_at,
                "resource_usage": {"tokens": 0, "compute_time": 0}
            }
            
            # Update tenant resource tracking
            await self._update_tenant_resources(tenant_id, "contexts", 1)
        
        # Async initialization of the context
        asyncio.create_task(self._initialize_context(context_id, model_id, config))
        
        logger.info(f"Created context {context_id} for tenant {tenant_id}, model {model_id}")
        return context_id
    
    async def _initialize_context(self, context_id: str, model_id: str, config: Dict[str, Any]):
        """Initialize the context asynchronously"""
        try:
            # Simulate model loading - in a real implementation this would load the model
            await asyncio.sleep(2)
            
            # Update context state
            async with self._lock:
                if context_id in self.contexts:
                    self.contexts[context_id]["state"] = ContextState.READY
            
            async with get_db_session() as session:
                await session.execute(
                    update(Context)
                    .where(Context.id == context_id)
                    .values(state=ContextState.READY, updated_at=datetime.utcnow())
                )
                await session.commit()
                
            logger.info(f"Context {context_id} for model {model_id} initialized and ready")
        except Exception as e:
            # Update state to error
            async with self._lock:
                if context_id in self.contexts:
                    self.contexts[context_id]["state"] = ContextState.ERROR
            
            async with get_db_session() as session:
                await session.execute(
                    update(Context)
                    .where(Context.id == context_id)
                    .values(state=ContextState.ERROR, updated_at=datetime.utcnow())
                )
                await session.commit()
                
            logger.error(f"Failed to initialize context {context_id}: {str(e)}")
    
    async def get_context(self, context_id: str, user_id: str) -> Dict[str, Any]:
        """
        Get context details by ID
        
        Args:
            context_id: Context ID to retrieve
            user_id: User ID making the request
            
        Returns:
            Context details
            
        Raises:
            ContextNotFoundError: If context doesn't exist
            UnauthorizedError: If user doesn't have permission
        """
        # Check in-memory cache first
        context = None
        async with self._lock:
            if context_id in self.contexts:
                context = self.contexts[context_id]
                tenant_id = context["tenant_id"]
        
        # If not in cache, try database
        if not context:
            async with get_db_session() as session:
                result = await session.execute(
                    select(Context).where(Context.id == context_id)
                )
                db_context = result.scalar_one_or_none()
                
                if not db_context:
                    logger.warning(f"Context {context_id} not found")
                    raise ContextNotFoundError(f"Context {context_id} not found")
                
                tenant_id = db_context.tenant_id
                context = {
                    "id": db_context.id,
                    "tenant_id": db_context.tenant_id,
                    "model_id": db_context.model_id,
                    "state": db_context.state,
                    "config": db_context.config,
                    "created_at": db_context.created_at,
                    "updated_at": db_context.updated_at,
                    "resource_usage": db_context.resource_usage
                }
                
                # Add to cache
                async with self._lock:
                    self.contexts[context_id] = context
        
        # Check authorization
        if not await self.auth_service.check_permission(user_id, "context:read", tenant_id):
            logger.warning(f"User {user_id} attempted to access context {context_id} without permission")
            raise UnauthorizedError("User does not have permission to access this context")
        
        # Update last accessed time
        context["last_used"] = datetime.utcnow()
        
        return context
    
    async def update_context(
        self,
        context_id: str,
        updates: Dict[str, Any],
        user_id: str
    ) -> Dict[str, Any]:
        """
        Update context details
        
        Args:
            context_id: Context ID to update
            updates: Dictionary of updates to apply
            user_id: User ID making the request
            
        Returns:
            Updated context details
            
        Raises:
            ContextNotFoundError: If context doesn't exist
            UnauthorizedError: If user doesn't have permission
            ValueError: If invalid updates are provided
        """
        # Get current context to check tenant
        try:
            current_context = await self.get_context(context_id, user_id)
            tenant_id = current_context["tenant_id"]
        except ContextNotFoundError:
            logger.warning(f"Attempted to update non-existent context {context_id}")
            raise
        
        # Check authorization
        if not await self.auth_service.check_permission(user_id, "context:update", tenant_id):
            logger.warning(f"User {user_id} attempted to update context {context_id} without permission")
            raise UnauthorizedError("User does not have permission to update this context")
        
        # Validate updates
        allowed_updates = ["config"]
        invalid_updates = set(updates.keys()) - set(allowed_updates)
        if invalid_updates:
            raise ValueError(f"Invalid updates: {invalid_updates}. Allowed fields: {allowed_updates}")
        
        # Apply updates
        update_dict = {"updated_at": datetime.utcnow()}
        if "config" in updates:
            update_dict["config"] = updates["config"]
        
        # Update in database
        async with get_db_session() as session:
            await session.execute(
                update(Context)
                .where(Context.id == context_id)
                .values(**update_dict)
            )
            await session.commit()
        
        # Update in-memory cache
        async with self._lock:
            if context_id in self.contexts:
                if "config" in updates:
                    self.contexts[context_id]["config"] = updates["config"]
                self.contexts[context_id]["last_used"] = datetime.utcnow()
        
        logger.info(f"Updated context {context_id}")
        return await self.get_context(context_id, user_id)
    
    async def delete_context(self, context_id: str, user_id: str) -> bool:
        """
        Delete a context
        
        Args:
            context_id: Context ID to delete
            user_id: User ID making the request
            
        Returns:
            True if successful
            
        Raises:
            ContextNotFoundError: If context doesn't exist
            UnauthorizedError: If user doesn't have permission
        """
        # Get current context to check tenant
        try:
            current_context = await self.get_context(context_id, user_id)
            tenant_id = current_context["tenant_id"]
        except ContextNotFoundError:
            logger.warning(f"Attempted to delete non-existent context {context_id}")
            raise
        
        # Check authorization
        if not await self.auth_service.check_permission(user_id, "context:delete", tenant_id):
            logger.warning(f"User {user_id} attempted to delete context {context_id} without permission")
            raise UnauthorizedError("User does not have permission to delete this context")
        
        # Update state to terminated
        async with get_db_session() as session:
            await session.execute(
                update(Context)
                .where(Context.id == context_id)
                .values(state=ContextState.TERMINATED, updated_at=datetime.utcnow())
            )
            await session.commit()
        
        # Clean up resources and remove from cache
        await self._cleanup_context_resources(context_id, tenant_id)
        
        logger.info(f"Deleted context {context_id}")
        return True
    
    async def run_inference(
        self,
        context_id: str,
        inputs: Dict[str, Any],
        user_id: str
    ) -> Dict[str, Any]:
        """
        Run inference on a context
        
        Args:
            context_id: Context ID to use
            inputs: Input data for inference
            user_id: User ID making the request
            
        Returns:
            Inference results
            
        Raises:
            ContextNotFoundError: If context doesn't exist
            UnauthorizedError: If user doesn't have permission
            ResourceExhaustedError: If tenant has reached resource limits
            InferenceError: If inference fails
        """
        start_time = time.time()
        
        # Get current context to check tenant and state
        try:
            current_context = await self.get_context(context_id, user_id)
            tenant_id = current_context["tenant_id"]
            model_id = current_context["model_id"]
            state = current_context["state"]
        except ContextNotFoundError:
            logger

