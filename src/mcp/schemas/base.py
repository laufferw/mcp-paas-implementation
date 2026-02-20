from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BaseSchema(BaseModel):
    """Base schema with common fields and functionality."""
    
    model_config = ConfigDict(
        from_attributes=True,
        arbitrary_types_allowed=True,
    )


class ResponseStatus(BaseSchema):
    """Schema for API response status information."""
    
    success: bool = Field(
        ..., 
        description="Whether the operation was successful"
    )
    message: str = Field(
        ..., 
        description="Human-readable status message"
    )
    error_code: Optional[str] = Field(
        None, 
        description="Error code if applicable"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Operation completed successfully",
                "error_code": None
            }
        }


class PaginationParams(BaseSchema):
    """Schema for pagination request parameters."""
    
    page: int = Field(
        1, 
        ge=1, 
        description="Page number (1-indexed)"
    )
    per_page: int = Field(
        50, 
        ge=1, 
        le=100, 
        description="Number of items per page"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "page": 1,
                "per_page": 50
            }
        }


class PaginatedResponse(BaseSchema):
    """Base schema for paginated API responses."""
    
    total: int = Field(
        ..., 
        description="Total number of items across all pages"
    )
    page: int = Field(
        ..., 
        description="Current page number"
    )
    per_page: int = Field(
        ..., 
        description="Number of items per page"
    )
    pages: int = Field(
        ..., 
        description="Total number of pages"
    )
    
    @field_validator('pages')
    @classmethod
    def validate_pages(cls, v: int, info: Any) -> int:
        """Validate pages calculation."""
        data = info.data
        if 'total' in data and 'per_page' in data and data['per_page'] > 0:
            expected = (data['total'] + data['per_page'] - 1) // data['per_page']
            if v != expected:
                raise ValueError(f"Pages calculation incorrect: expected {expected}")
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "total": 120,
                "page": 1,
                "per_page": 50,
                "pages": 3
            }
        }


class ResourceQuota(BaseSchema):
    """Schema for resource quota information."""
    
    resource_type: str = Field(
        ..., 
        description="Type of resource (e.g., 'contexts', 'tokens', 'requests')"
    )
    limit: int = Field(
        ..., 
        description="Maximum allowed amount of the resource"
    )
    used: int = Field(
        ..., 
        description="Current amount of resource used"
    )
    
    @field_validator('used')
    @classmethod
    def validate_used(cls, v: int, info: Any) -> int:
        """Validate that used does not exceed limit."""
        data = info.data
        if 'limit' in data and v > data['limit']:
            raise ValueError(f"Used amount ({v}) exceeds limit ({data['limit']})")
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "resource_type": "contexts",
                "limit": 10,
                "used": 3
            }
        }

