from enum import Enum
from datetime import datetime
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, EmailStr, Field, field_validator
import uuid


class AuthProvider(str, Enum):
    """Authentication provider types supported by the system."""
    INTERNAL = "internal"  # Internal authentication system
    OAUTH = "oauth"        # OAuth-based authentication
    API_KEY = "api_key"    # API key-based authentication
    SSO = "sso"            # Single sign-on
    LDAP = "ldap"          # LDAP authentication
    NONE = "none"          # No authentication (for public resources)


class ResourceLimits(BaseModel):
    """Resource limits applied to a tenant."""
    max_concurrent_requests: int = Field(
        default=100,
        description="Maximum number of concurrent requests allowed"
    )
    max_contexts: int = Field(
        default=10,
        description="Maximum number of active model contexts allowed"
    )
    max_tokens_per_minute: int = Field(
        default=10000,
        description="Maximum number of tokens that can be processed per minute"
    )
    max_context_ttl_seconds: int = Field(
        default=3600,
        description="Maximum time to live for a context in seconds"
    )
    max_storage_mb: int = Field(
        default=1000,
        description="Maximum storage in MB allowed for tenant data"
    )
    max_compute_units: int = Field(
        default=100,
        description="Maximum compute units allocated to the tenant"
    )
    custom_limits: Dict[str, Union[int, float, str]] = Field(
        default_factory=dict,
        description="Custom limit parameters specific to the tenant"
    )

    @field_validator('max_concurrent_requests', 'max_contexts', 'max_tokens_per_minute', 'max_storage_mb', 'max_compute_units')
    @classmethod
    def validate_positive_values(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Resource limits must be positive values")
        return v


class UsageTracking(BaseModel):
    """Tracks resource usage for a tenant."""
    current_concurrent_requests: int = Field(
        default=0,
        description="Current number of concurrent requests being processed"
    )
    active_contexts: int = Field(
        default=0,
        description="Current number of active model contexts"
    )
    tokens_used_this_minute: int = Field(
        default=0,
        description="Number of tokens used in the current minute"
    )
    tokens_used_total: int = Field(
        default=0,
        description="Total number of tokens used by the tenant"
    )
    storage_used_mb: float = Field(
        default=0.0,
        description="Current storage usage in MB"
    )
    compute_units_used: float = Field(
        default=0.0,
        description="Current compute units in use"
    )
    last_request_timestamp: Optional[datetime] = Field(
        default=None,
        description="Timestamp of the last request made by the tenant"
    )
    request_history: List[Dict] = Field(
        default_factory=list,
        description="List of recent request metrics for analytics"
    )
    custom_metrics: Dict[str, Union[int, float, str]] = Field(
        default_factory=dict,
        description="Custom usage metrics specific to the tenant"
    )

    def reset_minute_counters(self):
        """Reset counters that track per-minute usage."""
        self.tokens_used_this_minute = 0

    def update_request_metrics(self, tokens_used: int, compute_units: float):
        """Update request metrics after processing a request."""
        self.tokens_used_this_minute += tokens_used
        self.tokens_used_total += tokens_used
        self.compute_units_used += compute_units
        self.last_request_timestamp = datetime.now()
        
        # Add to history with basic metrics
        self.request_history.append({
            "timestamp": self.last_request_timestamp,
            "tokens_used": tokens_used,
            "compute_units": compute_units
        })
        
        # Trim history if it's getting too large
        if len(self.request_history) > 1000:
            self.request_history = self.request_history[-1000:]


class Tenant(BaseModel):
    """Main tenant configuration and information."""
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for the tenant"
    )
    name: str = Field(..., description="Name of the tenant")
    description: Optional[str] = Field(None, description="Description of the tenant")
    contact_email: EmailStr = Field(..., description="Primary contact email for the tenant")
    created_at: datetime = Field(default_factory=datetime.now, description="Tenant creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.now, description="Last update timestamp")
    
    # Authentication and access control
    auth_provider: AuthProvider = Field(
        default=AuthProvider.API_KEY,
        description="Authentication provider used by this tenant"
    )
    api_keys: List[str] = Field(
        default_factory=list,
        description="List of active API keys for this tenant"
    )
    
    # Resource management
    resource_limits: ResourceLimits = Field(
        default_factory=ResourceLimits,
        description="Resource limits for this tenant"
    )
    usage_tracking: UsageTracking = Field(
        default_factory=UsageTracking,
        description="Resource usage tracking for this tenant"
    )
    
    # Tenant status
    is_active: bool = Field(
        default=True,
        description="Whether the tenant is active"
    )
    subscription_tier: str = Field(
        default="free",
        description="Subscription tier of the tenant (free, standard, premium, etc.)"
    )
    
    # Optional metadata
    metadata: Dict[str, Union[str, int, float, bool]] = Field(
        default_factory=dict,
        description="Additional metadata for the tenant"
    )

    @field_validator('api_keys')
    @classmethod
    def validate_api_keys(cls, v: list) -> list:
        """Ensure API keys are unique."""
        if len(v) != len(set(v)):
            raise ValueError("API keys must be unique")
        return v
    
    def check_resource_availability(self, 
                                    tokens_requested: Optional[int] = None,
                                    contexts_requested: Optional[int] = None,
                                    compute_units_requested: Optional[float] = None) -> bool:
        """
        Check if tenant has enough resources available for a requested operation.
        
        Returns True if resources are available, False otherwise.
        """
        usage = self.usage_tracking
        limits = self.resource_limits
        
        if tokens_requested is not None:
            if usage.tokens_used_this_minute + tokens_requested > limits.max_tokens_per_minute:
                return False
                
        if contexts_requested is not None:
            if usage.active_contexts + contexts_requested > limits.max_contexts:
                return False
                
        if compute_units_requested is not None:
            if usage.compute_units_used + compute_units_requested > limits.max_compute_units:
                return False
                
        return True
    
    def generate_api_key(self) -> str:
        """Generate a new API key for this tenant."""
        new_key = f"mcp_{str(uuid.uuid4()).replace('-', '')}_{str(uuid.uuid4())[-12:]}"
        self.api_keys.append(new_key)
        self.updated_at = datetime.now()
        return new_key


