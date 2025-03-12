import enum
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (Boolean, Column, DateTime, Enum, Float, ForeignKey, 
                      Integer, String, Table, Text, UniqueConstraint, Index)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from src.mcp.models.base import Base

# Association table for user-role many-to-many relationship
user_roles = Table(
    'user_roles',
    Base.metadata,
    Column('user_id', UUID(as_uuid=True), ForeignKey('user.id'), primary_key=True),
    Column('role_id', UUID(as_uuid=True), ForeignKey('role.id'), primary_key=True)
)

class UserStatus(enum.Enum):
    """Enum for user status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"

class User(Base):
    """User model for authentication and authorization."""
    
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    status = Column(Enum(UserStatus), default=UserStatus.ACTIVE, nullable=False)
    last_login = Column(DateTime)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenant.id'), nullable=False)
    
    # Relationships
    tenant = relationship("Tenant", back_populates="users")
    roles = relationship("Role", secondary=user_roles, back_populates="users")
    inference_requests = relationship("InferenceRequest", back_populates="user")
    
    # Indices
    __table_args__ = (
        Index('idx_user_tenant_id', tenant_id),
        Index('idx_user_email_tenant', email, tenant_id, unique=True),
    )

class Role(Base):
    """Role model for RBAC."""
    
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255))
    
    # Relationships
    users = relationship("User", secondary=user_roles, back_populates="roles")
    permissions = relationship("Permission", back_populates="role")

class Permission(Base):
    """Permission model for granular access control."""
    
    resource = Column(String(100), nullable=False)
    action = Column(String(50), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey('role.id'), nullable=False)
    
    # Relationships
    role = relationship("Role", back_populates="permissions")
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('resource', 'action', 'role_id', name='uq_permission_resource_action_role'),
    )

class TenantStatus(enum.Enum):
    """Enum for tenant status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    TRIAL = "trial"

class TenantPlan(enum.Enum):
    """Enum for tenant subscription plans."""
    FREE = "free"
    BASIC = "basic"
    STANDARD = "standard"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"

class Tenant(Base):
    """Tenant model for multi-tenancy support."""
    
    name = Column(String(100), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    status = Column(Enum(TenantStatus), default=TenantStatus.ACTIVE, nullable=False)
    plan = Column(Enum(TenantPlan), default=TenantPlan.FREE, nullable=False)
    quota_contexts = Column(Integer, default=3, nullable=False)
    quota_requests_per_minute = Column(Integer, default=60, nullable=False)
    quota_tokens_per_month = Column(Integer, default=100000, nullable=False)
    tokens_used_this_month = Column(Integer, default=0, nullable=False)
    billing_email = Column(String(255))
    config = Column(JSONB, default={})
    
    # Relationships
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    contexts = relationship("Context", back_populates="tenant", cascade="all, delete-orphan")
    
    # Indices
    __table_args__ = (
        Index('idx_tenant_status', status),
        Index('idx_tenant_plan', plan),
    )

class ContextStatus(enum.Enum):
    """Enum for context status."""
    CREATING = "creating"
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    DELETED = "deleted"

class Context(Base):
    """Context model for managing model contexts."""
    
    name = Column(String(100), nullable=False)
    description = Column(Text)
    model_id = Column(String(100), nullable=False)
    status = Column(Enum(ContextStatus), default=ContextStatus.CREATING, nullable=False)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenant.id'), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey('user.id'), nullable=False)
    last_used = Column(DateTime, default=datetime.utcnow)
    parameters = Column(JSONB, default={})
    context_data = Column(JSONB, default={})
    resource_usage = Column(JSONB, default={})
    
    # Relationships
    tenant = relationship("Tenant", back_populates="contexts")
    creator = relationship("User", foreign_keys=[created_by])
    inference_requests = relationship("InferenceRequest", back_populates="context")
    
    # Indices and constraints
    __table_args__ = (
        Index('idx_context_tenant_id', tenant_id),
        Index('idx_context_status', status),
        UniqueConstraint('name', 'tenant_id', name='uq_context_name_tenant'),
    )

class RequestStatus(enum.Enum):
    """Enum for inference request status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class InferenceRequest(Base):
    """InferenceRequest model for tracking inference requests."""
    
    prompt = Column(Text, nullable=False)
    status = Column(Enum(RequestStatus), default=RequestStatus.PENDING, nullable=False)
    context_id = Column(UUID(as_uuid=True), ForeignKey('context.id'), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey('user.id'), nullable=False)
    completion = Column(Text)
    tokens_used = Column(Integer, default=0)
    duration_ms = Column(Float, default=0.0)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error_message = Column(Text)
    metadata = Column(JSONB, default={})
    
    # Relationships
    context = relationship("Context", back_populates="inference_requests")
    user = relationship("User", back_populates="inference_requests")
    
    # Indices
    __table_args__ = (
        Index('idx_inference_request_context_id', context_id),
        Index('idx_inference_request_user_id', user_id),
        Index('idx_inference_request_status', status),
        Index('idx_inference_request_created_at', 'created_at'),
    )

