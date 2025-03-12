import logging
import time
from typing import Dict, List, Optional, Any
import asyncio
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, Response, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, Gauge, Summary, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel, Field
import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Define Prometheus metrics
REQUEST_COUNT = Counter(
    "request_count", 
    "Total count of requests by endpoint and status", 
    ["endpoint", "method", "status"]
)

REQUEST_LATENCY = Histogram(
    "request_latency_seconds", 
    "Request latency in seconds", 
    ["endpoint", "method"]
)

TENANT_REQUEST_COUNT = Counter(
    "tenant_request_count", 
    "Request count by tenant", 
    ["tenant_id", "endpoint"]
)

TENANT_RESOURCE_USAGE = Gauge(
    "tenant_resource_usage", 
    "Resource usage by tenant and resource type", 
    ["tenant_id", "resource_type"]
)

ERROR_COUNT = Counter(
    "error_count", 
    "Count of errors by type and tenant", 
    ["error_type", "tenant_id"]
)

RESOURCE_LIMIT_ALERTS = Counter(
    "resource_limit_alerts", 
    "Count of resource limit alerts by tenant and resource type", 
    ["tenant_id", "resource_type"]
)

ACTIVE_CONTEXTS = Gauge(
    "active_contexts", 
    "Number of active contexts by tenant", 
    ["tenant_id"]
)

OPERATION_LATENCY = Summary(
    "operation_latency_seconds", 
    "Latency of operations by operation type", 
    ["operation_type", "tenant_id"]
)

# Tenant resource limits configuration
# In a real application, these would come from a database
TENANT_RESOURCE_LIMITS = {
    "default": {
        "max_contexts": 5,
        "max_memory_mb": 1024,
        "max_requests_per_minute": 100,
        "max_concurrent_requests": 10
    }
}

# Current tenant resource usage tracking
tenant_usage: Dict[str, Dict[str, float]] = {}

# Alert thresholds (percentage of limit)
ALERT_THRESHOLD = 0.8  # 80% of limit

# Rate limiter using sliding window
class RateLimiter:
    def __init__(self):
        self.request_timestamps: Dict[str, List[float]] = {}
        
    async def check_rate_limit(self, tenant_id: str, window_seconds: int = 60) -> bool:
        """Check if tenant is within rate limits."""
        if tenant_id not in self.request_timestamps:
            self.request_timestamps[tenant_id] = []
            
        # Get tenant-specific limit
        limit = TENANT_RESOURCE_LIMITS.get(
            tenant_id, 
            TENANT_RESOURCE_LIMITS["default"]
        )["max_requests_per_minute"]
        
        # Remove timestamps outside the window
        current_time = time.time()
        self.request_timestamps[tenant_id] = [
            ts for ts in self.request_timestamps[tenant_id] 
            if current_time - ts <= window_seconds
        ]
        
        # Check if limit exceeded
        if len(self.request_timestamps[tenant_id]) >= limit:
            return False
            
        # Add current request
        self.request_timestamps[tenant_id].append(current_time)
        return True

rate_limiter = RateLimiter()

# Models for API
class TenantResourceUsage(BaseModel):
    tenant_id: str
    contexts: int
    memory_mb: float
    requests_per_minute: float
    concurrent_requests: int

class AlertConfig(BaseModel):
    threshold: float = Field(0.8, ge=0.0, le=1.0)
    enabled: bool = True

class HealthStatus(BaseModel):
    status: str
    version: str
    components: Dict[str, str]

# Lifespan event handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Set up background tasks
    logger.info("Starting server and initializing monitoring")
    background_tasks = set()
    
    # Start background task for periodic resource usage check
    task = asyncio.create_task(periodic_resource_check())
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    
    yield
    
    # Shutdown: Cleanup tasks
    logger.info("Shutting down server")
    for task in background_tasks:
        task.cancel()
    
    await asyncio.gather(*background_tasks, return_exceptions=True)
    logger.info("All background tasks have been canceled")

app = FastAPI(
    title="Model Context Platform Monitoring",
    description="Monitoring and metrics for Multi-tenant Context Platform",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware for request metrics and logging
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    # Extract tenant ID from headers or auth token
    tenant_id = request.headers.get("X-Tenant-ID", "unknown")
    
    # Add context to structured logging
    bind_contextvars(
        tenant_id=tenant_id,
        request_id=request.headers.get("X-Request-ID", ""),
        method=request.method,
        path=request.url.path
    )
    
    # Check rate limit
    if not await rate_limiter.check_rate_limit(tenant_id):
        ERROR_COUNT.labels(error_type="rate_limit_exceeded", tenant_id=tenant_id).inc()
        logger.warning("Rate limit exceeded", tenant_id=tenant_id)
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"}
        )
    
    # Track concurrent requests
    if tenant_id not in tenant_usage:
        tenant_usage[tenant_id] = {"concurrent_requests": 0}
    tenant_usage[tenant_id]["concurrent_requests"] = tenant_usage[tenant_id].get("concurrent_requests", 0) + 1
    TENANT_RESOURCE_USAGE.labels(tenant_id=tenant_id, resource_type="concurrent_requests").set(
        tenant_usage[tenant_id]["concurrent_requests"]
    )
    
    # Record request start time
    start_time = time.time()
    
    # Process request
    try:
        response = await call_next(request)
        
        # Record metrics
        REQUEST_COUNT.labels(
            endpoint=request.url.path,
            method=request.method,
            status=response.status_code
        ).inc()
        
        TENANT_REQUEST_COUNT.labels(
            tenant_id=tenant_id,
            endpoint=request.url.path
        ).inc()
        
        request_latency = time.time() - start_time
        REQUEST_LATENCY.labels(
            endpoint=request.url.path,
            method=request.method
        ).observe(request_latency)
        
        # Log request completion
        logger.info(
            "Request completed",
            status_code=response.status_code,
            duration=request_latency
        )
        
        return response
        
    except Exception as e:
        # Record error
        ERROR_COUNT.labels(
            error_type=type(e).__name__,
            tenant_id=tenant_id
        ).inc()
        
        # Log error
        logger.error(
            "Request failed",
            exc_info=True,
            error=str(e)
        )
        
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )
    finally:
        # Decrement concurrent requests counter
        if tenant_id in tenant_usage:
            tenant_usage[tenant_id]["concurrent_requests"] = max(0, tenant_usage[tenant_id].get("concurrent_requests", 1) - 1)
            TENANT_RESOURCE_USAGE.labels(tenant_id=tenant_id, resource_type="concurrent_requests").set(
                tenant_usage[tenant_id]["concurrent_requests"]
            )
        
        # Clear context vars
        clear_contextvars()

# Background task for resource checks
async def periodic_resource_check():
    """Periodically check resource usage against limits and trigger alerts."""
    while True:
        try:
            logger.debug("Performing periodic resource check")
            for tenant_id, usage in tenant_usage.items():
                # Get tenant-specific limits
                limits = TENANT_RESOURCE_LIMITS.get(tenant_id, TENANT_RESOURCE_LIMITS["default"])
                
                # Check each resource type
                for resource_type, used in usage.items():
                    if resource_type in limits:
                        limit = limits.get(resource_type, float('inf'))
                        usage_ratio = used / limit if limit > 0 else 0
                        
                        # Update metrics
                        TENANT_RESOURCE_USAGE.labels(
                            tenant_id=tenant_id,
                            resource_type=resource_type
                        ).set(used)
                        
                        # Check if threshold exceeded
                        if usage_ratio >= ALERT_THRESHOLD:
                            RESOURCE_LIMIT_ALERTS.labels(
                                tenant_id=tenant_id,
                                resource_type=resource_type
                            ).inc()
                            
                            logger.warning(
                                "Resource limit threshold exceeded",
                                tenant_id=tenant_id,
                                resource_type=resource_type,
                                usage=used,
                                limit=limit,
                                usage_percentage=usage_ratio * 100
                            )
            
            # Sleep for 60 seconds
            await asyncio.sleep(60)
        except Exception as e:
            logger.error("Error in resource check", exc_info=True)
            await asyncio.sleep(60)  # Sleep and try again

# Update resource usage for a tenant
def update_tenant_resource_usage(
    tenant_id: str,
    resource_type: str,
    value: float,
    background_tasks: BackgroundTasks
):
    """Update tracked resource usage for a tenant and check limits."""
    if tenant_id not in tenant_usage:
        tenant_usage[tenant_id] = {}
    
    tenant_usage[tenant_id][resource_type] = value
    
    # Update metrics
    TENANT_RESOURCE_USAGE.labels(
        tenant_id=tenant_id,
        resource_type=resource_type
    ).set(value)
    
    # Schedule limit check in background
    background_tasks.add_task(check_resource_limits, tenant_id, resource_type)

async def check_resource_limits(tenant_id: str, resource_type: str):
    """Check if tenant has exceeded resource limits and log alerts."""
    if tenant_id not in tenant_usage:
        return
    
    if resource_type not in tenant_usage[tenant_id]:
        return
    
    # Get usage and limit
    usage = tenant_usage[tenant_id][resource_type]
    limits = TENANT_RESOURCE_LIMITS.get(tenant_id, TENANT_RESOURCE_LIMITS["default"])
    limit = limits.get(resource_type, float('inf'))
    
    # Calculate usage ratio
    usage_ratio = usage / limit if limit > 0 else 0
    
    # Check if limit exceeded
    if usage_ratio >= 1.0:
        RESOURCE_LIMIT_ALERTS.labels(
            tenant_id=tenant_id,
            resource_type=resource_type
        ).inc()
        
        logger.error(
            "Resource limit exceeded",
            tenant_id=tenant_id,
            resource_type=resource_type,
            usage=usage,
            limit=limit
        )
        
    # Check if approaching limit
    elif usage_ratio >= ALERT_THRESHOLD:
        RESOURCE_LIMIT_ALERTS.labels(
            tenant_id=tenant_id,
            resource_type=resource_type
        ).inc()
        
        logger.warning(
            "Resource limit threshold exceeded",
            tenant_id=tenant_id,
            resource_type=resource_type,
            usage=usage,
            limit=limit,
            usage_percentage=usage_ratio * 100
        )

# Routes

@app.get("/metrics")
async def metrics():
    """Expose Prometheus metrics."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return HealthStatus(
        status="healthy",
        version="1.0.0",
        components={
            "database": "up",
            "context_manager": "up",
            "auth_service": "up"
        }
    )

@app.get("/readiness")
async def readiness():
    """Readiness check for Kubernetes."""
    return {"status": "ready"}

@app.get("/tenant/{tenant_id}/usage")
async def get_tenant_usage(tenant_id: str):
    """Get current resource usage for a tenant."""
    if tenant_id not in tenant_usage:
        return TenantResourceUsage(
            tenant_id=tenant_id,
            contexts=0,
            memory_mb=0,
            requests_per_minute=0,
            concurrent_requests=0
        )
    
    usage = tenant_usage[tenant_id]
    return TenantResourceUsage(
        tenant_id=tenant_id,
        contexts=usage.get("max_contexts", 0),
        memory_mb=usage.get("max_memory_mb", 0),
        requests_per_minute=len(rate_limiter.request_timestamps.get(tenant_id, [])),
        concurrent_requests=usage.get("concurrent_requests", 0)
    )

@app.post("/tenant/{tenant_id}/usage/{resource_type}")
async def report_resource_usage(
    tenant_id: str,
    resource_type: str,
    value: float,
    background_tasks: BackgroundTasks
):
    """Report resource usage for a tenant."""
    update_tenant_resource_usage(tenant_id, resource_type, value, background_tasks)
    return {"status": "recorded"}

@app.get("/alerts")
async def get_alert_config():
    """Get current alert configuration."""
    return AlertConfig(threshold=ALERT_THRESHOLD, enabled=True)

