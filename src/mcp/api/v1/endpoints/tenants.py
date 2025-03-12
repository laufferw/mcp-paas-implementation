from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.mcp.api.deps import (
    get_current_active_user,
    get_current_admin_user,
    get_db
)
from src.mcp.models.models import User, Tenant, ResourceQuota, ResourceUsage
from src.mcp.schemas.tenant import (
    TenantCreate,
    TenantUpdate,
    TenantResponse,
    TenantListResponse,
    ResourceQuotaCreate,
    ResourceQuotaResponse,
    ResourceQuotaListResponse,
    ResourceUsageResponse
)
from src.mcp.services.tenant import TenantService
from src.mcp.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)

@router.post(
    "",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new tenant",
    description="Create a new tenant with basic information. Requires admin privileges."
)
async def create_tenant(
    tenant_in: TenantCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
) -> TenantResponse:
    """
    Create a new tenant with the provided information.
    
    Requires admin privileges.
    """
    try:
        tenant_service = TenantService(db)
        tenant = await tenant_service.create_tenant(tenant_data=tenant_in)
        return tenant
    except Exception as e:
        logger.error(f"Error creating tenant: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not create tenant: {str(e)}"
        )

@router.get(
    "/{tenant_id}",
    response_model=TenantResponse,
    summary="Get tenant by ID",
    description="Retrieve a tenant by its ID. Requires appropriate permissions."
)
async def get_tenant(
    tenant_id: str = Path(..., description="The ID of the tenant to retrieve"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> TenantResponse:
    """
    Get tenant by ID.
    
    Users can only access their own tenant unless they have admin privileges.
    """
    try:
        tenant_service = TenantService(db)
        
        # Check if user has access to this tenant
        if not current_user.is_admin and current_user.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this tenant"
            )
            
        tenant = await tenant_service.get_tenant(tenant_id=tenant_id)
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found"
            )
        return tenant
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving tenant: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving tenant: {str(e)}"
        )

@router.get(
    "",
    response_model=TenantListResponse,
    summary="List tenants",
    description="List all tenants with pagination. Regular users can only see their own tenant."
)
async def list_tenants(
    skip: int = Query(0, ge=0, description="Number of tenants to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of tenants to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> TenantListResponse:
    """
    List tenants with pagination.
    
    Admin users can see all tenants, while regular users can only see their own tenant.
    """
    try:
        tenant_service = TenantService(db)
        
        # If not admin, only return the user's tenant
        if not current_user.is_admin:
            tenant = await tenant_service.get_tenant(tenant_id=current_user.tenant_id)
            total = 1
            tenants = [tenant] if tenant else []
        else:
            tenants, total = await tenant_service.list_tenants(skip=skip, limit=limit)
            
        return TenantListResponse(
            items=tenants,
            total=total,
            skip=skip,
            limit=limit
        )
    except Exception as e:
        logger.error(f"Error listing tenants: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing tenants: {str(e)}"
        )

@router.put(
    "/{tenant_id}",
    response_model=TenantResponse,
    summary="Update tenant",
    description="Update a tenant's information. Requires admin privileges or tenant ownership."
)
async def update_tenant(
    tenant_update: TenantUpdate,
    tenant_id: str = Path(..., description="The ID of the tenant to update"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> TenantResponse:
    """
    Update tenant information.
    
    Users can only update their own tenant unless they have admin privileges.
    """
    try:
        tenant_service = TenantService(db)
        
        # Check if tenant exists
        existing_tenant = await tenant_service.get_tenant(tenant_id=tenant_id)
        if not existing_tenant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found"
            )
            
        # Check permissions
        if not current_user.is_admin and current_user.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to update this tenant"
            )
            
        # Update tenant
        updated_tenant = await tenant_service.update_tenant(
            tenant_id=tenant_id,
            tenant_data=tenant_update
        )
        return updated_tenant
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating tenant: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating tenant: {str(e)}"
        )

@router.delete(
    "/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete tenant",
    description="Delete a tenant. This is a destructive operation. Requires admin privileges."
)
async def delete_tenant(
    tenant_id: str = Path(..., description="The ID of the tenant to delete"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
) -> None:
    """
    Delete a tenant.
    
    This is a destructive operation that will delete all tenant data.
    Requires admin privileges.
    """
    try:
        tenant_service = TenantService(db)
        
        # Check if tenant exists
        existing_tenant = await tenant_service.get_tenant(tenant_id=tenant_id)
        if not existing_tenant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found"
            )
            
        # Delete tenant
        await tenant_service.delete_tenant(tenant_id=tenant_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting tenant: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting tenant: {str(e)}"
        )

@router.put(
    "/{tenant_id}/quotas/{resource_type}",
    response_model=ResourceQuotaResponse,
    summary="Set tenant resource quota",
    description="Set or update a quota for a specific resource type. Requires admin privileges."
)
async def set_resource_quota(
    quota: ResourceQuotaCreate,
    tenant_id: str = Path(..., description="The ID of the tenant"),
    resource_type: str = Path(..., description="The type of resource (e.g., 'contexts', 'inference_requests', 'storage')"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
) -> ResourceQuotaResponse:
    """
    Set or update a resource quota for a tenant.
    
    Requires admin privileges.
    """
    try:
        tenant_service = TenantService(db)
        
        # Check if tenant exists
        existing_tenant = await tenant_service.get_tenant(tenant_id=tenant_id)
        if not existing_tenant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found"
            )
            
        # Set quota
        quota_result = await tenant_service.set_resource_quota(
            tenant_id=tenant_id,
            resource_type=resource_type,
            limit=quota.limit,
            unit=quota.unit
        )
        return quota_result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting resource quota: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error setting resource quota: {str(e)}"
        )

@router.get(
    "/{tenant_id}/quotas",
    response_model=ResourceQuotaListResponse,
    summary="Get tenant resource quotas",
    description="Get all resource quotas for a tenant."
)
async def get_resource_quotas(
    tenant_id: str = Path(..., description="The ID of the tenant"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> ResourceQuotaListResponse:
    """
    Get all resource quotas for a tenant.
    
    Users can only access their own tenant quotas unless they have admin privileges.
    """
    try:
        tenant_service = TenantService(db)
        
        # Check if user has access to this tenant
        if not current_user.is_admin and current_user.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this tenant's quotas"
            )
            
        # Check if tenant exists
        existing_tenant = await tenant_service.get_tenant(tenant_id=tenant_id)
        if not existing_tenant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found"
            )
            
        # Get quotas
        quotas = await tenant_service.get_resource_quotas(tenant_id=tenant_id)
        return ResourceQuotaListResponse(items=quotas)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting resource quotas: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting resource quotas: {str(e)}"
        )

@router.get(
    "/{tenant_id}/usage",
    response_model=ResourceUsageResponse,
    summary="Get tenant resource usage",
    description="Get current resource usage for a tenant."
)
async def get_resource_usage(
    tenant_id: str = Path(..., description="The ID of the tenant"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> ResourceUsageResponse:
    """
    Get current resource usage for a tenant.
    
    Users can only access their own tenant usage unless they have admin privileges.
    """
    try:
        tenant_service = TenantService(db)
        
        # Check if user has access to this tenant
        if not current_user.is_admin and current_user.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this tenant's usage data"
            )
            
        # Check if tenant exists
        existing_tenant = await tenant_service.get_tenant(tenant_id=tenant_id)
        if not existing_tenant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found"
            )
            
        # Get usage
        usage = await tenant_service.get_resource_usage(tenant_id=tenant_id)
        
        # Get quotas for comparison
        quotas = await tenant_service.get_resource_quotas(tenant_id=tenant_id)
        
        # Format response with usage and limits
        quota_dict = {q.resource_type: q for q in quotas}
        usage_data = {
            "tenant_id": tenant_id,
            "resources": []
        }
        
        for u in usage:
            resource_data = {
                "resource_type": u.resource_type,
                "current_usage": u.current_value,
                "unit": u.unit,
                "last_updated": u.last_updated
            }
            
            # Add limit if quota exists
            if u.resource_type in quota_dict:
                resource_data["limit"] = quota_dict[u.resource_type].limit
            
            usage_data["resources"].append(resource_data)
            
        return ResourceUsageResponse(**usage_data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting resource usage: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting resource usage: {str(e)}"
        )

