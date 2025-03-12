import logging
import os
from contextlib import contextmanager
from typing import Any, AsyncGenerator, Generator, Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy import create_engine, event, pool
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine, 
    AsyncSession, 
    async_sessionmaker, 
    create_async_engine
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import SQLAlchemyError, OperationalError

logger = logging.getLogger(__name__)

# Configuration for database connections
DEFAULT_DB_URL = "sqlite:///./mcp.db"
DEFAULT_ASYNC_DB_URL = "sqlite+aiosqlite:///./mcp.db"

# Timeout settings (in seconds)
DEFAULT_POOL_RECYCLE = 3600  # 1 hour
DEFAULT_POOL_TIMEOUT = 30
DEFAULT_POOL_SIZE = 5
DEFAULT_MAX_OVERFLOW = 10
DEFAULT_CONNECT_TIMEOUT = 10

# Get database URL from environment or use default
def get_db_url() -> str:
    """Get the database URL from environment variable or use the default."""
    return os.environ.get("MCP_DB_URL", DEFAULT_DB_URL)

def get_async_db_url() -> str:
    """Get the async database URL from environment variable or use the default."""
    return os.environ.get("MCP_ASYNC_DB_URL", DEFAULT_ASYNC_DB_URL)

# Create engine with proper configuration
def create_db_engine(url: Optional[str] = None, **kwargs) -> Engine:
    """Create a SQLAlchemy engine with proper configuration and connection pooling."""
    if url is None:
        url = get_db_url()
    
    engine_kwargs = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE", DEFAULT_POOL_RECYCLE)),
        "pool_timeout": int(os.environ.get("DB_POOL_TIMEOUT", DEFAULT_POOL_TIMEOUT)),
        "pool_size": int(os.environ.get("DB_POOL_SIZE", DEFAULT_POOL_SIZE)),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", DEFAULT_MAX_OVERFLOW)),
        "connect_args": {"timeout": int(os.environ.get("DB_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT))}
    }
    
    # SQLite specific configuration
    if url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    
    # Override defaults with provided kwargs
    engine_kwargs.update(kwargs)
    
    engine = create_engine(url, **engine_kwargs)
    
    # Add engine event listeners for monitoring
    @event.listens_for(engine, "connect")
    def on_connect(dbapi_connection, connection_record):
        logger.debug("Database connection established")
    
    @event.listens_for(engine, "checkout")
    def on_checkout(dbapi_connection, connection_record, connection_proxy):
        logger.debug("Database connection checked out")
        
    @event.listens_for(engine, "checkin")
    def on_checkin(dbapi_connection, connection_record):
        logger.debug("Database connection checked in")
    
    return engine

# Create async engine with proper configuration
def create_async_db_engine(url: Optional[str] = None, **kwargs) -> AsyncEngine:
    """Create an async SQLAlchemy engine with proper configuration and connection pooling."""
    if url is None:
        url = get_async_db_url()
    
    engine_kwargs = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE", DEFAULT_POOL_RECYCLE)),
        "pool_timeout": int(os.environ.get("DB_POOL_TIMEOUT", DEFAULT_POOL_TIMEOUT)),
        "pool_size": int(os.environ.get("DB_POOL_SIZE", DEFAULT_POOL_SIZE)),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", DEFAULT_MAX_OVERFLOW)),
    }
    
    # SQLite specific configuration
    if url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    
    # Override defaults with provided kwargs
    engine_kwargs.update(kwargs)
    
    return create_async_engine(url, **engine_kwargs)

# Create a singleton engine to be reused
engine = create_db_engine()
async_engine = create_async_db_engine()

# Create session factories
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
AsyncSessionLocal = async_sessionmaker(
    autocommit=False, autoflush=False, bind=async_engine, expire_on_commit=False
)

# Dependency for FastAPI routes (sync)
@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Get a database session for use in a with statement."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Database error: {str(e)}")
        raise
    finally:
        session.close()

# Dependency for FastAPI routes (async)
async def get_async_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session for use in FastAPI dependency injection."""
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except SQLAlchemyError as e:
        await session.rollback()
        logger.error(f"Database error: {str(e)}")
        raise
    finally:
        await session.close()

# FastAPI dependency
def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a database session."""
    with get_db_session() as session:
        yield session

# FastAPI async dependency
async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides an async database session."""
    async for session in get_async_db_session():
        yield session

# Database connection check
def check_db_connection() -> bool:
    """Check if the database connection is working."""
    try:
        with get_db_session() as session:
            session.execute("SELECT 1")
        return True
    except OperationalError as e:
        logger.error(f"Database connection check failed: {str(e)}")
        return False

# Async database connection check
async def check_async_db_connection() -> bool:
    """Check if the async database connection is working."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute("SELECT 1")
        return True
    except OperationalError as e:
        logger.error(f"Async database connection check failed: {str(e)}")
        return False

# Helper function to get db session or raise HTTPException
def get_db_or_error() -> Generator[Session, None, None]:
    """Get a database session or raise an HTTP exception if the database is not available."""
    try:
        with get_db_session() as session:
            yield session
    except SQLAlchemyError as e:
        logger.error(f"Database error in dependency: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection error",
        )

# Helper function to get async db session or raise HTTPException
async def get_async_db_or_error() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session or raise an HTTP exception if the database is not available."""
    try:
        async for session in get_async_db_session():
            yield session
    except SQLAlchemyError as e:
        logger.error(f"Database error in async dependency: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection error",
        )

# Function to initialize database at startup
def initialize_db() -> None:
    """Initialize the database connection at application startup."""
    try:
        # Check connection
        with get_db_session() as session:
            session.execute("SELECT 1")
        logger.info("Database connection established successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        raise

# Function to close database at shutdown
def close_db() -> None:
    """Close the database connection at application shutdown."""
    try:
        engine.dispose()
        logger.info("Database connection closed successfully")
    except Exception as e:
        logger.error(f"Error closing database connection: {str(e)}")

# Function to close async database at shutdown
async def close_async_db() -> None:
    """Close the async database connection at application shutdown."""
    try:
        await async_engine.dispose()
        logger.info("Async database connection closed successfully")
    except Exception as e:
        logger.error(f"Error closing async database connection: {str(e)}")

