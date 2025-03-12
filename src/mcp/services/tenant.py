import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import Session

from src.mcp.db.session import get_db
from src.mcp.exceptions import (
    QuotaExceededError,
    ResourceNotFoundError,
    TenantAlreadyExistsError,
    TenantNotFoundError,
    UnauthorizedError,
)
from src.mcp.models.models import Tenant, User, ResourceUsage, ResourceQuota

logger = logging.getLogger(__name__)


class TenantService:
    """
    Service for managing tenants, their configurations, and resource quotas.
    Provides functionality for tenant isolation and resource management.
    """

    def __init__(self, db_session: Optional[Union[Session, AsyncSession]] = None):
        """
        Initialize the tenant service with a database session.
        
        Args:
            db_session: Database session to use for operations. If None, a new session will be 
                        created for each operation.
        """
        self.db_session = db_session
        
    async def create_tenant(
        self, 
        name: str, 
        description: str = "", 
        tier: str = "standard",
        is_active: bool = True,
        owner_id: Optional[UUID] = None,
        **custom_config
    ) -> Tenant:
        """
        Create a new tenant with the given configuration.
        
        Args:
            name: Unique name for the tenant
            description: Description of the tenant
            tier: Service tier ("free", "standard", "premium", "enterprise")
            is_active: Whether the tenant is active
            owner_id: UUID of the user who owns this tenant
            custom_config: Additional tenant-specific configuration
            
        Returns:
            The created tenant object
            
        Raises:
            TenantAlreadyExistsError: If a tenant with the given name already exists
            SQLAlchemyError: For database errors
        """
        async_session = self.db_session is None
        session = self.db_session or get_db()
        
        # Set default quotas based on tier
        quota_defaults = self._get_quota_defaults(tier)
        
        try:
            # Create new tenant
            new_tenant = Tenant(
                name=name,
                description=description,
                tier=tier,
                is_active=is_active,
                owner_id=owner_id,
                configuration=custom_config,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            if async_session:
                session.add(new_tenant)
                await session.commit()
                await session.refresh(new_tenant)
            else:
                session.add(new_tenant)
                session.commit()
                session.refresh(new_tenant)
                
            # Set up default resource quotas
            await self._setup_default_quotas(new_tenant.id, quota_defaults, session)
            
            logger.info(f"Created new tenant: {name} (ID: {new_tenant.id})")
            return new_tenant
            
        except IntegrityError:
            if async_session:
                await session.rollback()
            else:
                session.rollback()
            logger.error(f"Tenant with name '{name}' already exists")
            raise TenantAlreadyExistsError(f"Tenant with name '{name}' already exists")
        except SQLAlchemyError as e:
            if async_session:
                await session.rollback()
            else:
                session.rollback()
            logger.error(f"Database error creating tenant: {str(e)}")
            raise
        finally:
            if async_session:
                await session.close()
                
    async def get_tenant(self, tenant_id: UUID) -> Tenant:
        """
        Get a tenant by ID.
        
        Args:
            tenant_id: UUID of the tenant to retrieve
            
        Returns:
            The tenant object
            
        Raises:
            TenantNotFoundError: If the tenant doesn't exist
            SQLAlchemyError: For database errors
        """
        async_session = self.db_session is None
        session = self.db_session or get_db()
        
        try:
            if async_session:
                result = await session.execute(
                    select(Tenant).where(Tenant.id == tenant_id)
                )
                tenant = result.scalars().first()
            else:
                tenant = session.query(Tenant).filter(Tenant.id == tenant_id).first()
                
            if not tenant:
                raise TenantNotFoundError(f"Tenant with ID {tenant_id} not found")
                
            return tenant
        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving tenant {tenant_id}: {str(e)}")
            raise
        finally:
            if async_session:
                await session.close()
                
    async def update_tenant(
        self, 
        tenant_id: UUID, 
        name: Optional[str] = None,
        description: Optional[str] = None,
        tier: Optional[str] = None,
        is_active: Optional[bool] = None,
        owner_id: Optional[UUID] = None,
        **custom_config
    ) -> Tenant:
        """
        Update a tenant's configuration.
        
        Args:
            tenant_id: UUID of the tenant to update
            name: New name for the tenant
            description: New description
            tier: New service tier
            is_active: New active status
            owner_id: New owner ID
            custom_config: Updated tenant-specific configuration
            
        Returns:
            The updated tenant object
            
        Raises:
            TenantNotFoundError: If the tenant doesn't exist
            TenantAlreadyExistsError: If a tenant with the new name already exists
            SQLAlchemyError: For database errors
        """
        async_session = self.db_session is None
        session = self.db_session or get_db()
        
        try:
            # Get existing tenant
            if async_session:
                result = await session.execute(
                    select(Tenant).where(Tenant.id == tenant_id)
                )
                tenant = result.scalars().first()
            else:
                tenant = session.query(Tenant).filter(Tenant.id == tenant_id).first()
                
            if not tenant:
                raise TenantNotFoundError(f"Tenant with ID {tenant_id} not found")
            
            # Update tenant fields
            if name is not None:
                tenant.name = name
            if description is not None:
                tenant.description = description
            if tier is not None:
                tenant.tier = tier
                # Update quotas if tier changed
                await self._update_quotas_for_tier(tenant.id, tier, session)
            if is_active is not None:
                tenant.is_active = is_active
            if owner_id is not None:
                tenant.owner_id = owner_id
                
            # Update custom config
            if custom_config:
                if tenant.configuration:
                    tenant.configuration.update(custom_config)
                else:
                    tenant.configuration = custom_config
                    
            tenant.updated_at = datetime.utcnow()
            
            if async_session:
                await session.commit()
                await session.refresh(tenant)
            else:
                session.commit()
                session.refresh(tenant)
                
            logger.info(f"Updated tenant: {tenant.name} (ID: {tenant.id})")
            return tenant
            
        except IntegrityError:
            if async_session:
                await session.rollback()
            else:
                session.rollback()
            logger.error(f"Tenant with name '{name}' already exists")
            raise TenantAlreadyExistsError(f"Tenant with name '{name}' already exists")
        except SQLAlchemyError as e:
            if async_session:
                await session.rollback()
            else:
                session.rollback()
            logger.error(f"Database error updating tenant {tenant_id}: {str(e)}")
            raise
        finally:
            if async_session:
                await session.close()
                
    async def delete_tenant(self, tenant_id: UUID) -> bool:
        """
        Delete a tenant and all associated resources.
        
        Args:
            tenant_id: UUID of the tenant to delete
            
        Returns:
            True if deletion was successful
            
        Raises:
            TenantNotFoundError: If the tenant doesn't exist
            SQLAlchemyError: For database errors
        """
        async_session = self.db_session is None
        session = self.db_session or get_db()
        
        try:
            # Get existing tenant
            if async_session:
                result = await session.execute(
                    select(Tenant).where(Tenant.id == tenant_id)
                )
                tenant = result.scalars().first()
            else:
                tenant = session.query(Tenant).filter(Tenant.id == tenant_id).first()
                
            if not tenant:
                raise TenantNotFoundError(f"Tenant with ID {tenant_id} not found")
            
            # Delete the tenant (cascading delete should handle related resources)
            if async_session:
                await session.delete(tenant)
                await session.commit()
            else:
                session.delete(tenant)
                session.commit()
                
            logger.info(f"Deleted tenant: {tenant.name} (ID: {tenant_id})")
            return True
            
        except SQLAlchemyError as e:
            if async_session:
                await session.rollback()
            else:
                session.rollback()
            logger.error(f"Database error deleting tenant {tenant_id}: {str(e)}")
            raise
        finally:
            if async_session:
                await session.close()
                
    async def list_tenants(self, 
                           skip: int = 0, 
                           limit: int = 100, 
                           filter_active: Optional[bool] = None
                           ) -> List[Tenant]:
        """
        List tenants with optional filtering and pagination.
        
        Args:
            skip: Number of records to skip (for pagination)
            limit: Maximum number of records to return
            filter_active: If set, filter by active status
            
        Returns:
            List of tenant objects
            
        Raises:
            SQLAlchemyError: For database errors
        """
        async_session = self.db_session is None
        session = self.db_session or get_db()
        
        try:
            query = select(Tenant)
            
            if filter_active is not None:
                query = query.where(Tenant.is_active == filter_active)
                
            query = query.offset(skip).limit(limit)
            
            if async_session:
                result = await session.execute(query)
                tenants = result.scalars().all()
            else:
                tenants = session.execute(query).scalars().all()
                
            return list(tenants)
            
        except SQLAlchemyError as e:
            logger.error(f"Database error listing tenants: {str(e)}")
            raise
        finally:
            if async_session:
                await session.close()
    
    # Resource quota management methods
    
    async def set_resource_quota(
        self, 
        tenant_id: UUID, 
        resource_type: str, 
        limit: int
    ) -> ResourceQuota:
        """
        Set or update a resource quota for a tenant.
        
        Args:
            tenant_id: Tenant UUID
            resource_type: Type of resource (e.g., 'context_count', 'memory_mb', 'cpu_cores')
            limit: Maximum allowed value
            
        Returns:
            Created or updated ResourceQuota object
            
        Raises:
            TenantNotFoundError: If the tenant doesn't exist
            SQLAlchemyError: For database errors
        """
        async_session = self.db_session is None
        session = self.db_session or get_db()
        
        try:
            # Verify tenant exists
            if async_session:
                tenant_result = await session.execute(
                    select(Tenant).where(Tenant.id == tenant_id)
                )
                tenant = tenant_result.scalars().first()
            else:
                tenant = session.query(Tenant).filter(Tenant.id == tenant_id).first()
                
            if not tenant:
                raise TenantNotFoundError(f"Tenant with ID {tenant_id} not found")
            
            # Check if quota already exists
            if async_session:
                quota_result = await session.execute(
                    select(ResourceQuota).where(
                        ResourceQuota.tenant_id == tenant_id,
                        ResourceQuota.resource_type == resource_type
                    )
                )
                quota = quota_result.scalars().first()
            else:
                quota = session.query(ResourceQuota).filter(
                    ResourceQuota.tenant_id == tenant_id,
                    ResourceQuota.resource_type == resource_type
                ).first()
            
            if quota:
                # Update existing quota
                quota.limit = limit
                quota.updated_at = datetime.utcnow()
            else:
                # Create new quota
                quota = ResourceQuota(
                    tenant_id=tenant_id,
                    resource_type=resource_type,
                    limit=limit,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                if async_session:
                    session.add(quota)
                else:
                    session.add(quota)
            
            if async_session:
                await session.commit()
                await session.refresh(quota)
            else:
                session.commit()
                session.refresh(quota)
                
            logger.info(f"Set quota for tenant {tenant_id}: {resource_type}={limit}")
            return quota
            
        except SQLAlchemyError as e:
            if async_session:
                await session.rollback()
            else:
                session.rollback()
            logger.error(f"Database error setting quota for tenant {tenant_id}: {str(e)}")
            raise
        finally:
            if async_session:
                await session.close()
    
    async def get_resource_quota(
        self, 
        tenant_id: UUID, 
        resource_type: str
    ) -> Optional[ResourceQuota]:
        """
        Get a specific resource quota for a tenant.
        
        Args:
            tenant_id: Tenant UUID
            resource_type: Type of resource
            
        Returns:
            ResourceQuota object or None if not found
            
        Raises:
            TenantNotFoundError: If the tenant doesn't exist
            SQLAlchemyError: For database errors
        """
        async_session = self.db_session is None
        session = self.db_session or get_db()
        
        try:
            # Verify tenant exists
            if async_session:
                tenant_result = await session.execute(
                    select(Tenant).where(Tenant.id == tenant_id)
                )
                tenant = tenant_result.scalars

