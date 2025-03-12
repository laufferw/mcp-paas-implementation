from enum import Enum
from typing import Dict, Any, Optional
from uuid import UUID, uuid4
from datetime import datetime
from pydantic import BaseModel, Field


class ContextStatus(str, Enum):
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


class ResourceUsage(BaseModel):
    cpu_seconds: float = Field(default=0.0, description="CPU seconds used")
    memory_mb: float = Field(default=0.0, description="Memory used in MB")
    tokens_input: int = Field(default=0, description="Number of input tokens processed")
    tokens_output: int = Field(default=0, description="Number of output tokens generated")
    last_updated: datetime = Field(default_factory=datetime.utcnow, description="Last time usage was updated")


class ModelContext(BaseModel):
    context_id: UUID = Field(default_factory=uuid4, description="Unique identifier for the context")
    tenant_id: UUID = Field(..., description="Tenant that owns this context")
    model_name: str = Field(..., description="Name of the model being used")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Model parameters")
    status: ContextStatus = Field(default=ContextStatus.INITIALIZING, description="Current status of the context")
    resource_usage: ResourceUsage = Field(default_factory=ResourceUsage, description="Resource usage metrics")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="When the context was created")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="When the context was last updated")
    expires_at: Optional[datetime] = Field(default=None, description="When the context will expire")
    
    class Config:
        use_enum_values = True

