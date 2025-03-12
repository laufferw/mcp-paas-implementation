from typing import List, Dict, Optional, Any, Union
import os
from pathlib import Path
from pydantic import BaseSettings, Field, validator, AnyHttpUrl, DirectoryPath
import logging
import secrets


class ServerSettings(BaseSettings):
    """Server configuration settings."""
    HOST: str = Field("0.0.0.0", env="MCP_HOST", description="Host address to bind the server to")
    PORT: int = Field(8000, env="MCP_PORT", description="Port to bind the server to")
    DEBUG: bool = Field(False, env="MCP_DEBUG", description="Enable debug mode")
    WORKERS: int = Field(4, env="MCP_WORKERS", description="Number of worker processes")
    API_PREFIX: str = Field("/api/v1", env="MCP_API_PREFIX", description="API route prefix")
    PROJECT_NAME: str = Field("MCP PaaS Implementation", env="MCP_PROJECT_NAME", description="Project name")
    
    @validator("PORT")
    def validate_port(cls, v):
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v


class CORSSettings(BaseSettings):
    """CORS configuration settings."""
    ALLOW_ORIGINS: List[str] = Field(["*"], env="MCP_CORS_ALLOW_ORIGINS", description="List of allowed origins")
    ALLOW_METHODS: List[str] = Field(["*"], env="MCP_CORS_ALLOW_METHODS", description="List of allowed HTTP methods")
    ALLOW_HEADERS: List[str] = Field(["*"], env="MCP_CORS_ALLOW_HEADERS", description="List of allowed HTTP headers")
    ALLOW_CREDENTIALS: bool = Field(True, env="MCP_CORS_ALLOW_CREDENTIALS", description="Allow credentials")

    @validator("ALLOW_ORIGINS", "ALLOW_METHODS", "ALLOW_HEADERS", pre=True)
    def parse_list(cls, v):
        if isinstance(v, str):
            return v.split(",")
        return v


class AuthSettings(BaseSettings):
    """Authentication and security settings."""
    SECRET_KEY: str = Field(
        secrets.token_urlsafe(32),
        env=["JWT_SECRET_KEY", "MCP_SECRET_KEY"],
        description="Secret key for JWT token encoding"
    )
    ALGORITHM: str = Field("HS256", env=["JWT_ALGORITHM", "MCP_JWT_ALGORITHM"], description="JWT encoding algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        30, 
        env=["JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "MCP_ACCESS_TOKEN_EXPIRE_MINUTES"], 
        description="Access token expiration in minutes"
    )
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        7, 
        env="MCP_REFRESH_TOKEN_EXPIRE_DAYS", 
        description="Refresh token expiration in days"
    )
    ALLOW_ANONYMOUS: bool = Field(
        False, 
        env="MCP_ALLOW_ANONYMOUS", 
        description="Allow anonymous access to certain endpoints"
    )
    TOKEN_URL: str = Field("/api/v1/auth/token", env="MCP_TOKEN_URL", description="URL for token endpoint")


class ResourceLimits(BaseSettings):
    """Resource limitation settings."""
    MAX_CONTEXTS_PER_TENANT: int = Field(
        10, 
        env="MCP_MAX_CONTEXTS_PER_TENANT", 
        description="Maximum number of active contexts per tenant"
    )
    MAX_MEMORY_PER_TENANT_MB: int = Field(
        1024, 
        env="MCP_MAX_MEMORY_PER_TENANT", 
        description="Maximum memory allocation per tenant in MB"
    )
    MAX_CPU_PER_TENANT: float = Field(
        2.0, 
        env="MCP_MAX_CPU_PER_TENANT", 
        description="Maximum CPU allocation per tenant in cores"
    )
    MAX_GPU_PER_TENANT: float = Field(
        0.0, 
        env="MCP_MAX_GPU_PER_TENANT", 
        description="Maximum GPU allocation per tenant in units"
    )
    MAX_TOKENS_PER_MINUTE: int = Field(
        10000, 
        env="MCP_MAX_TOKENS_PER_MINUTE", 
        description="Maximum tokens processed per minute per tenant"
    )
    MAX_CONTEXT_LIFETIME_HOURS: int = Field(
        24, 
        env="MCP_MAX_CONTEXT_LIFETIME", 
        description="Maximum lifetime of a context in hours"
    )


class LoggingSettings(BaseSettings):
    """Logging configuration settings."""
    LEVEL: str = Field("INFO", env="MCP_LOG_LEVEL", description="Logging level")
    FORMAT: str = Field(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        env="MCP_LOG_FORMAT",
        description="Log message format"
    )
    FILE: Optional[Path] = Field(None, env="MCP_LOG_FILE", description="Log file path")
    ROTATION: str = Field("1 day", env="MCP_LOG_ROTATION", description="Log rotation interval")
    RETENTION: str = Field("30 days", env="MCP_LOG_RETENTION", description="Log retention period")
    
    @validator("LEVEL")
    def validate_log_level(cls, v):
        allowed_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in allowed_levels:
            raise ValueError(f"Log level must be one of {allowed_levels}")
        return v.upper()


class RateLimitSettings(BaseSettings):
    """Rate limiting configuration."""
    ENABLED: bool = Field(True, env="MCP_RATE_LIMIT_ENABLED", description="Enable rate limiting")
    DEFAULT_LIMIT: int = Field(
        100, 
        env="MCP_RATE_LIMIT_DEFAULT", 
        description="Default requests per minute limit"
    )
    WINDOW_SIZE: int = Field(
        60, 
        env="MCP_RATE_LIMIT_WINDOW", 
        description="Rate limit window size in seconds"
    )
    BY_IP: bool = Field(
        True, 
        env="MCP_RATE_LIMIT_BY_IP", 
        description="Apply rate limiting by IP address"
    )
    BY_TENANT: bool = Field(
        True, 
        env="MCP_RATE_LIMIT_BY_TENANT", 
        description="Apply rate limiting by tenant"
    )
    TENANT_LIMITS: Dict[str, int] = Field(
        {}, 
        env="MCP_RATE_LIMIT_TENANT_LIMITS", 
        description="Custom rate limits per tenant (tenant_id:limit)"
    )
    
    @validator("TENANT_LIMITS", pre=True)
    def parse_tenant_limits(cls, v):
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
    PATH: Path = Field(
        Path("data/mcp.db"),
        env="MCP_DB_PATH",
        description="Path to the database file"
    )
    MAX_CONNECTIONS: int = Field(
        10,
        env="MCP_DB_MAX_CONNECTIONS",
        description="Maximum number of database connections"
    )
    TIMEOUT: int = Field(
        30,
        env="MCP_DB_TIMEOUT",
        description="Database connection timeout in seconds"
    )
    
    @validator("PATH")
    def ensure_path_exists(cls, v):
        # Create parent directories if they don't exist
        v.parent.mkdir(parents=True, exist_ok=True)
        return v


class Settings(BaseSettings):
    """Main application settings combining all subsections."""
    # Base configuration
    ENV: str = Field("development", env="MCP_ENV", description="Environment (development, testing, production)")
    ROOT_PATH: Path = Field(Path(__file__).parent.parent, env="MCP_ROOT_PATH", description="Root path of the application")
    
    # Subsections
    SERVER: ServerSettings = ServerSettings()
    CORS: CORSSettings = CORSSettings()
    AUTH: AuthSettings = AuthSettings()
    RESOURCE_LIMITS: ResourceLimits = ResourceLimits()
    LOGGING: LoggingSettings = LoggingSettings()
    RATE_LIMIT: RateLimitSettings = RateLimitSettings()
    DATABASE: DatabaseSettings = DatabaseSettings()
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        validate_assignment = True
        extra = "ignore"


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

