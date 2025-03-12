from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, EmailStr, validator, root_validator

from .base import BaseSchema, ResourceQuota, PaginatedResponse


class TenantStatus(str, Enum):
    """Enum for tenant status values."""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING = "pending"
    DELETED = "deleted"


class TenantType(str, Enum):
    """Enum for tenant type values."""
    FREE = "free"
    BASIC = "basic"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"


class TenantBase(BaseSchema):
    """Base schema for tenant data (common fields)."""
    
    name: str = Field(
        ..., 
        min_length=3, 
        max_length=100, 
        description="Name of the tenant"
    )
    description: Optional[str] = Field(
        None, 
        max_length=500, 
        description="Optional description of the tenant"
    )


class TenantCreate(TenantBase):
    """Schema for tenant creation requests."""
    
    tenant_type: TenantType = Field(
        TenantType.BASIC, 
        description="Type of tenant subscription"
    )
    admin_email: EmailStr = Field(
        ..., 
        description="Email address of the tenant administrator"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Acme Corporation",
                "description": "Technology solutions provider",
                "tenant_type": "basic",
                "admin_email": "admin@acmecorp.com"
            }
        }


class TenantUpdate(BaseSchema):
    """Schema for tenant update requests."""
    
    name: Optional[str] = Field(
        None, 
        min_length=3, 
        max_length=100, 
        description="Name of the tenant"
    )
    description: Optional[str] = Field(
        None, 
        max_length=500, 
        description="Description of the tenant"
    )
    tenant_type: Optional[TenantType] = Field(
        None, 
        description="Type of tenant subscription"
    )
    status: Optional[TenantStatus] = Field(
        None, 
        description="Status of the tenant"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Acme Corporation Updated",
                "description": "Global technology solutions provider",
                "tenant_type": "premium"
            }
        }


class Tenant(TenantBase):
    """Schema for tenant responses."""
    
    id: UUID = Field(
        ..., 
        description="Unique identifier for the tenant"
    )
    tenant_type: TenantType = Field(
        ..., 
        description="Type of tenant subscription"
    )
    status: TenantStatus = Field(
        ..., 
        description="Current status of the tenant"
    )
    created_at: datetime = Field(
        ..., 
        description="When the tenant was created"
    )
    updated_at: datetime = Field(
        ..., 
        description="When the tenant was last updated"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "Acme Corporation",
                "description": "Technology solutions provider",
                "tenant_type": "basic",
                "status": "active",
                "created_at": "2023-01-01T12:00:00Z",
                "updated_at": "2023-01-01T12:00:00Z"
            }
        }


class TenantQuotas(BaseSchema):
    """Schema for tenant quota information."""
    
    tenant_id: UUID = Field(
        ..., 
        description="ID of the tenant"
    )
    quotas: List[ResourceQuota] = Field(
        ..., 
        description="List of resource quotas for the tenant"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                "quotas": [
                    {
                        "resource_type": "contexts",
                        "limit": 10,
                        "used": 3
                    },
                    {
                        "resource_type": "tokens",
                        "limit": 1000000,
                        "used": 250000
                    },
                    {
                        "resource_type": "requests_per_minute",
                        "limit": 60,
                        "used": 12
                    }
                ]
            }
        }


class QuotaUpdate(BaseSchema):
    """Schema for updating a specific quota."""
    
    limit: int = Field(
        ..., 
        ge=0, 
        description="New limit for the resource"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "limit": 20
            }
        }


class TenantsList(PaginatedResponse):
    """Schema for paginated list of tenants."""
    
    items: List[Tenant] = Field(
        ..., 
        description="List of tenants"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "total": 15,
                "page": 1,
                "per_page": 10,
                "pages": 2,
                "items": [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "name": "Acme Corporation",
                        "description": "Technology solutions provider",
                        "tenant_type": "basic",
                        "status": "active",
                        "created_at": "2023-01-01T12:00:00Z",
                        "updated_at": "2023-01-01T12:00:00Z"
                    }
                ]
            }
        }

