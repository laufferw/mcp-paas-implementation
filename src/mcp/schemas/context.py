from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from .base import BaseSchema, PaginatedResponse


class ContextStatus(str, Enum):
    """Enum for context status values."""
    INITIALIZING = "initializing"
    READY = "ready"
    ERROR = "error"
    PROCESSING = "processing"
    DELETED = "deleted"


class ContextType(str, Enum):
    """Enum for context type values."""
    STATELESS = "stateless"
    STATEFUL = "stateful"
    STREAMING = "streaming"


class ModelParameters(BaseSchema):
    """Schema for model parameters configuration."""
    
    temperature: Optional[float] = Field(
        None, 
        ge=0.0, 
        le=2.0, 
        description="Sampling temperature for model generation"
    )
    top_p: Optional[float] = Field(
        None, 
        ge=0.0, 
        le=1.0, 
        description="Nucleus sampling parameter"
    )
    top_k: Optional[int] = Field(
        None, 
        ge=0, 
        description="Top-k sampling parameter"
    )
    max_tokens: Optional[int] = Field(
        None, 
        ge=1, 
        le=4096, 
        description="Maximum number of tokens to generate"
    )
    presence_penalty: Optional[float] = Field(
        None, 
        ge=-2.0, 
        le=2.0, 
        description="Presence penalty for repeated tokens"
    )
    frequency_penalty: Optional[float] = Field(
        None, 
        ge=-2.0, 
        le=2.0, 
        description="Frequency penalty for repeated tokens"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "temperature": 0.7,
                "top_p": 0.95,
                "top_k": 40,
                "max_tokens": 1024,
                "presence_penalty": 0.0,
                "frequency_penalty": 0.0
            }
        }


class ContextBase(BaseSchema):
    """Base schema for context data (common fields)."""
    
    name: str = Field(
        ..., 
        min_length=1, 
        max_length=100, 
        description="Name of the context"
    )
    description: Optional[str] = Field(
        None, 
        max_length=500, 
        description="Optional description of the context"
    )
    model_id: str = Field(
        ..., 
        description="ID of the model to use for this context"
    )
    context_type: ContextType = Field(
        ContextType.STATEFUL, 
        description="Type of context to create"
    )


class ContextCreate(ContextBase):
    """Schema for context creation requests."""
    
    initial_prompt: Optional[str] = Field(
        None, 
        max_length=10000, 
        description="Initial prompt to set up the context"
    )
    parameters: Optional[ModelParameters] = Field(
        None, 
        description="Model parameters for this context"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None, 
        description="Optional metadata for the context"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Customer Support Assistant",
                "description": "Context for handling customer inquiries",
                "model_id": "llama3-70b",
                "context_type": "stateful",
                "initial_prompt": "You are a helpful customer support assistant...",
                "parameters": {
                    "temperature": 0.7,
                    "max_tokens": 1024
                },
                "metadata": {
                    "department": "support",
                    "product_line": "enterprise"
                }
            }
        }


class ContextUpdate(BaseSchema):
    """Schema for context update requests."""
    
    name: Optional[str] = Field(
        None, 
        min_length=1, 
        max_length=100, 
        description="Name of the context"
    )
    description: Optional[str] = Field(
        None, 
        max_length=500, 
        description="Description of the context"
    )
    parameters: Optional[ModelParameters] = Field(
        None, 
        description="Model parameters for this context"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None, 
        description="Metadata for the context"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Updated Support Assistant",
                "description": "Updated context for premium support",
                "parameters": {
                    "temperature": 0.5,
                }
            }
        }

