from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, validator, root_validator


class BaseSchema(BaseModel):
    """Base schema with common fields and functionality."""
    
    class Config:
        """Pydantic configuration for BaseSchema."""
        orm_mode = True
        arbitrary_types_allowed = True
        json_encoders = {
            datetime: lambda dt: dt.isoformat(),
            UUID: lambda uuid: str(uuid)
        }


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
    
    @validator('pages')
    def validate_pages(cls, v, values):
        """Validate pages calculation."""
        if 'total' in values and 'per_page' in values and values['per_page'] > 0:
            expected = (values['total'] + values['per_page'] - 1) // values['per_page']
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
    
    @validator('used')
    def validate_used(cls, v, values):
        """Validate that used does not exceed limit."""
        if 'limit' in values and v > values['limit']:
            raise ValueError(f"Used amount ({v}) exceeds limit ({values['limit']})")
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "resource_type": "contexts",
                "limit": 10,
                "used": 3
            }
        }

