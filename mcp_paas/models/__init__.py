"""
Model registry and schema for MCP PaaS implementation.

This package provides classes and utilities for model management, including:
- Model and version registration
- Model configuration
- Status tracking
- Performance metrics
"""

# Import key classes and functions from the registry module
from mcp_paas.models.registry import (
    ModelRegistry,
    RegistryError,
    ModelExistsError,
    ModelNotFoundError,
    VersionExistsError,
    VersionNotFoundError,
    InvalidStatusError,
)

# Import key classes and functions from the schema module
from mcp_paas.models.schema import (
    ModelStatus,
    Model,
    ModelVersion,
    ModelConfiguration,
    ModelMetric,
    Tag,
    init_db,
    create_session,
    get_engine,
)

__all__ = [
    # Registry classes
    "ModelRegistry",
    "RegistryError",
    "ModelExistsError",
    "ModelNotFoundError",
    "VersionExistsError",
    "VersionNotFoundError",
    "InvalidStatusError",
    
    # Schema classes
    "ModelStatus",
    "Model",
    "ModelVersion",
    "ModelConfiguration",
    "ModelMetric",
    "Tag",
    
    # Utility functions
    "init_db",
    "create_session",
    "get_engine",
]

