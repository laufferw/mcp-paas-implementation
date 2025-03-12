"""
Configuration module for the MCP application.
"""

import os
from typing import Any, Dict, List, Optional, Union

from pydantic import AnyHttpUrl, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application settings
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Model Context Platform"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"
    
    # CORS configuration
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        """Parse CORS origins from string to list if needed."""
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # Database settings
    DATABASE_URI: Optional[PostgresDsn] = None
    ASYNC_DATABASE_URI: Optional[PostgresDsn] = None

    # JWT settings
    SECRET_KEY: str = "CHANGE_THIS_TO_A_SECURE_SECRET"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Redis settings
    REDIS_URI: str = "redis://localhost:6379/0"
    
    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    DEFAULT_RATE_LIMIT: int = 100  # requests per minute
    
    # Resource Limits
    MAX_CONTEXTS_PER_TENANT: int = 10
    MAX_CONTEXT_SIZE_MB: int = 100
    MAX_INFERENCE_TOKENS: int = 1000
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Create global settings instance
settings = Settings()

