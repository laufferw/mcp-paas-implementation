from typing import List, Dict, Optional, Any, Union
import os
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import logging
import secrets


class ServerSettings(BaseSettings):
    """Server configuration settings."""
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    HOST: str = Field("0.0.0.0", validation_alias="MCP_HOST", description="Host address to bind the server to")
    PORT: int = Field(8000, validation_alias="MCP_PORT", description="Port to bind the server to")
    DEBUG: bool = Field(False, validation_alias="MCP_DEBUG", description="Enable debug mode")
    WORKERS: int = Field(4, validation_alias="MCP_WORKERS", description="Number of worker processes")
    API_PREFIX: str = Field("/api/v1", validation_alias="MCP_API_PREFIX", description="API route prefix")
    PROJECT_NAME: str = Field("MCP PaaS Implementation", validation_alias="MCP_PROJECT_NAME", description="Project name")
    
    @field_validator("PORT")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v


class CORSSettings(BaseSettings):
    """CORS configuration settings."""
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    ALLOW_ORIGINS: List[str] = Field(["*"], validation_alias="MCP_CORS_ALLOW_ORIGINS", description="List of allowed origins")
    ALLOW_METHODS: List[str] = Field(["*"], validation_alias="MCP_CORS_ALLOW_METHODS", description="List of allowed HTTP methods")
    ALLOW_HEADERS: List[str] = Field(["*"], validation_alias="MCP_CORS_ALLOW_HEADERS", description="List of allowed HTTP headers")
    ALLOW_CREDENTIALS: bool = Field(True, validation_alias="MCP_CORS_ALLOW_CREDENTIALS", description="Allow credentials")

    @field_validator("ALLOW_ORIGINS", "ALLOW_METHODS", "ALLOW_HEADERS", mode="before")
    @classmethod
    def parse_list(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.split(",")
        return v


class AuthSettings(BaseSettings):
    """Authentication and security settings."""
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    SECRET_KEY: str = Field(
        secrets.token_urlsafe(32),
        validation_alias="JWT_SECRET_KEY",
        description="Secret key for JWT token encoding"
    )
    ALGORITHM: str = Field("HS256", validation_alias="JWT_ALGORITHM", description="JWT encoding algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        30, 
        validation_alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 
        description="Access token expiration in minutes"
    )
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        7, 
        validation_alias="MCP_REFRESH_TOKEN_EXPIRE_DAYS", 
        description="Refresh token expiration in days"
    )
    ALLOW_ANONYMOUS: bool = Field(
        False, 
        validation_alias="MCP_ALLOW_ANONYMOUS", 
        description="Allow anonymous access to certain endpoints"
    )
    TOKEN_URL: str = Field("/api/v1/auth/token", validation_alias="MCP_TOKEN_URL", description="URL for token endpoint")


class ResourceLimits(BaseSettings):
    """Resource limitation settings."""
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    MAX_CONTEXTS_PER_TENANT: int = Field(
        10, 
        validation_alias="MCP_MAX_CONTEXTS_PER_TENANT", 
        description="Maximum number of active contexts per tenant"
    )
    MAX_MEMORY_PER_TENANT_MB: int = Field(
        1024, 
        validation_alias="MCP_MAX_MEMORY_PER_TENANT", 
        description="Maximum memory allocation per tenant in MB"
    )
    MAX_CPU_PER_TENANT: float = Field(
        2.0, 
        validation_alias="MCP_MAX_CPU_PER_TENANT", 
        description="Maximum CPU allocation per tenant in cores"
    )
    MAX_GPU_PER_TENANT: float = Field(
        0.0, 
        validation_alias="MCP_MAX_GPU_PER_TENANT", 
        description="Maximum GPU allocation per tenant in units"
    )
    MAX_TOKENS_PER_MINUTE: int = Field(
        10000, 
        validation_alias="MCP_MAX_TOKENS_PER_MINUTE", 
        description="Maximum tokens processed per minute per tenant"
    )
    MAX_CONTEXT_LIFETIME_HOURS: int = Field(
        24, 
        validation_alias="MCP_MAX_CONTEXT_LIFETIME", 
        description="Maximum lifetime of a context in hours"
    )


class LoggingSettings(BaseSettings):
    """Logging configuration settings."""
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    LEVEL: str = Field("INFO", validation_alias="MCP_LOG_LEVEL", description="Logging level")
    FORMAT: str = Field(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        validation_alias="MCP_LOG_FORMAT",
        description="Log message format"
    )
    FILE: Optional[Path] = Field(None, validation_alias="MCP_LOG_FILE", description="Log file path")
    ROTATION: str = Field("1 day", validation_alias="MCP_LOG_ROTATION", description="Log rotation interval")
    RETENTION: str = Field("30 days", validation_alias="MCP_LOG_RETENTION", description="Log retention period")
    
    @field_validator("LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in allowed_levels:
            raise ValueError(f"Log level must be one of {allowed_levels}")
        return v.upper()


class RateLimitSettings(BaseSettings):
    """Rate limiting configuration."""
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    ENABLED: bool = Field(True, validation_alias="MCP_RATE_LIMIT_ENABLED", description="Enable rate limiting")
    DEFAULT_LIMIT: int = Field(
        100, 
        validation_alias="MCP_RATE_LIMIT_DEFAULT", 
        description="Default requests per minute limit"
    )
    WINDOW_SIZE: int = Field(
        60, 
        validation_alias="MCP_RATE_LIMIT_WINDOW", 
        description="Rate limit window size in seconds"
    )
    BY_IP: bool = Field(
        True, 
        validation_alias="MCP_RATE_LIMIT_BY_IP", 
        description="Apply rate limiting by IP address"
    )
    BY_TENANT: bool = Field(
        True, 
        validation_alias="MCP_RATE_LIMIT_BY_TENANT", 
        description="Apply rate limiting by tenant"
    )
    TENANT_LIMITS: Dict[str, int] = Field(
        {}, 
        validation_alias="MCP_RATE_LIMIT_TENANT_LIMITS", 
        description="Custom rate limits per tenant (tenant_id:limit)"
    )
    
    @field_validator("TENANT_LIMITS", mode="before")
    @classmethod
    def parse_tenant_limits(cls, v: Any) -> Any:
        if isinstance(v, str):
            tenant_limits = {}
            for item in v.split(","):
                if ":" in item:
                    tenant_id, limit = item.split(":")
                    tenant_limits[tenant_id] = int(limit)
            return tenant_limits
        return v


class DatabaseSettings(BaseSettings):
    """Database configuration settings."""
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    PATH: Path = Field(
        Path("data/mcp.db"),
        validation_alias="MCP_DB_PATH",
        description="Path to the database file"
    )
    MAX_CONNECTIONS: int = Field(
        10,
        validation_alias="MCP_DB_MAX_CONNECTIONS",
        description="Maximum number of database connections"
    )
    TIMEOUT: int = Field(
        30,
        validation_alias="MCP_DB_TIMEOUT",
        description="Database connection timeout in seconds"
    )
    
    @field_validator("PATH")
    @classmethod
    def ensure_path_exists(cls, v: Path) -> Path:
        # Create parent directories if they don't exist
        v.parent.mkdir(parents=True, exist_ok=True)
        return v


class Settings(BaseSettings):
    """Main application settings combining all subsections."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        validate_assignment=True,
        extra="ignore",
    )

    # Base configuration
    ENV: str = Field("development", validation_alias="MCP_ENV", description="Environment (development, testing, production)")
    ROOT_PATH: Path = Field(Path(__file__).parent.parent, validation_alias="MCP_ROOT_PATH", description="Root path of the application")
    
    # Subsections
    SERVER: ServerSettings = ServerSettings()
    CORS: CORSSettings = CORSSettings()
    AUTH: AuthSettings = AuthSettings()
    RESOURCE_LIMITS: ResourceLimits = ResourceLimits()
    LOGGING: LoggingSettings = LoggingSettings()
    RATE_LIMIT: RateLimitSettings = RateLimitSettings()
    DATABASE: DatabaseSettings = DatabaseSettings()


# Create a global settings object
settings = Settings()


def configure_logging():
    """Configure logging based on settings."""
    log_level = getattr(logging, settings.LOGGING.LEVEL)
    logging.basicConfig(
        level=log_level,
        format=settings.LOGGING.FORMAT,
    )
    
    # Add file handler if specified
    if settings.LOGGING.FILE:
        file_handler = logging.FileHandler(settings.LOGGING.FILE)
        file_handler.setLevel(log_level)
        formatter = logging.Formatter(settings.LOGGING.FORMAT)
        file_handler.setFormatter(formatter)
        logging.getLogger('').addHandler(file_handler)

