#!/usr/bin/env python3
"""
Model Context Platform (MCP) - FastAPI Application Entry Point

This module sets up the FastAPI application with all necessary middleware,
routers, and event handlers for the Model Context Platform.
"""
import logging
import time
from contextlib import asynccontextmanager

import prometheus_client
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.mcp.api.v1.api import api_router
from src.mcp.config import settings
from src.mcp.db.session import create_db_and_tables, engine, sessionmaker
from src.mcp.services.auth import AuthService
from src.mcp.services.context_manager import MCPContextManager
from src.mcp.utils.rate_limiter import RateLimiter

# Configure logging
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize metrics
REQUEST_TIME = prometheus_client.Summary(
    "request_processing_seconds", "Time spent processing request"
)
REQUEST_COUNT = prometheus_client.Counter(
    "request_count", "Total count of requests", ["method", "endpoint", "http_status"]
)
ACTIVE_REQUESTS = prometheus_client.Gauge(
    "active_requests", "Number of active requests"
)


# Lifespan context manager for startup/shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting up MCP application")
    create_db_and_tables()  # Initialize database
    
    # Initialize services
    app.state.context_manager = MCPContextManager()
    app.state.auth_service = AuthService()
    app.state.rate_limiter = RateLimiter()
    
    await app.state.context_manager.initialize()
    
    logger.info("MCP application started successfully")
    yield
    # Shutdown
    logger.info("Shutting down MCP application")
    
    # Clean up resources
    await app.state.context_manager.cleanup()
    
    # Close database connections
    if engine is not None:
        engine.dispose()
    
    logger.info("MCP application shutdown complete")


# Create FastAPI application
app = FastAPI(
    title="Model Context Platform",
    description="API for managing model contexts and running inference",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Authentication middleware
class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware for JWT authentication."""
    
    async def dispatch(self, request: Request, call_next):
        # Skip auth for certain paths
        if request.url.path in [
            "/api/docs", 
            "/api/redoc", 
            "/api/openapi.json",
            "/api/v1/auth/login", 
            "/api/v1/auth/register",
            "/api/health",
            "/metrics",
        ]:
            return await call_next(request)
            
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authorization header missing"},
            )
            
        try:
            # Get auth service from app state
            auth_service = request.app.state.auth_service
            token = auth_header.split(" ")[1]
            user = await auth_service.validate_token(token)
            
            # Add user to request state
            request.state.user = user
            request.state.tenant_id = user.tenant_id
            
            return await call_next(request)
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid authentication credentials"},
            )


# Rate limiting middleware
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware for rate limiting requests."""
    
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for certain paths
        if request.url.path in [
            "/api/docs", 
            "/api/redoc", 
            "/api/openapi.json",
            "/api/health",
            "/metrics",
        ]:
            return await call_next(request)
            
        # Get client identifier (IP or user ID if authenticated)
        client_id = getattr(request.state, "user_id", None) or request.client.host
        
        # Get rate limiter from app state
        rate_limiter = request.app.state.rate_limiter
        endpoint = request.url.path
        
        # Check rate limit
        allowed, headers = await rate_limiter.check_rate_limit(
            client_id, endpoint
        )
        
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers=headers,
            )
            
        # Add rate limit headers to response
        response = await call_next(request)
        for name, value in headers.items():
            response.headers[name] = value
            
        return response


# Metrics middleware
class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware for collecting request metrics."""
    
    async def dispatch(self, request: Request, call_next):
        ACTIVE_REQUESTS.inc()
        start_time = time.time()
        
        try:
            response = await call_next(request)
            status_code = response.status_code
            
            # Record request metrics
            REQUEST_COUNT.labels(
                method=request.method,
                endpoint=request.url.path,
                http_status=status_code,
            ).inc()
            
            # Record request processing time
            REQUEST_TIME.observe(time.time() - start_time)
            
            return response
        except Exception as exc:
            logger.exception("Request failed")
            raise exc
        finally:
            ACTIVE_REQUESTS.dec()


# Add middleware to app (order matters)
app.add_middleware(MetricsMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)


# Error handler for global exception catching
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled exceptions."""
    logger.exception(f"Unhandled exception: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error_id": str(time.time())},
    )


# Include API router
app.include_router(
    api_router,
    prefix="/api/v1",
)


# Health check endpoint
@app.get("/api/health", tags=["Health"])
async def health_check():
    """Health check endpoint to verify service status."""
    return {
        "status": "healthy",
        "version": app.version,
        "timestamp": time.time(),
    }


# Metrics endpoint
@app.get("/metrics", tags=["Monitoring"])
def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        prometheus_client.generate_latest(),
        media_type="text/plain",
    )


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "src.mcp.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )

"""
Main application entry point for the Model Context Platform (MCP).
"""

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from mcp.config import settings


# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    This handles startup and shutdown events, like initializing and closing database connections.
    """
    # Startup: Initialize resources
    logger.info("Starting up MCP application")
    # TODO: Initialize database connection
    # TODO: Initialize cache and other resources
    
    yield
    
    # Shutdown: Clean up resources
    logger.info("Shutting down MCP application")
    # TODO: Close database connections
    # TODO: Clean up other resources


def create_application() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(
        title=settings.PROJECT_NAME,
        description="Model Context Platform API",
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.DEBUG,
    )

    # Configure CORS
    if settings.BACKEND_CORS_ORIGINS:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Add Prometheus metrics
    metrics_app = make_asgi_app()
    application.mount("/metrics", metrics_app)
    
    # API routes will be included here
    # TODO: Include API routers
    
    @application.get("/health")
    async def health_check():
        """Basic health check endpoint."""
        return {"status": "ok"}

    return application


app = create_application()


if __name__ == "__main__":
    """Run the application using Uvicorn when script is executed directly."""
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )

