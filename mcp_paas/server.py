import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Union

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

from mcp_paas.config import settings
from mcp_paas.middleware.auth import authenticate_user, get_current_tenant
from mcp_paas.models.context import ContextStatus, ModelContext
from mcp_paas.models.tenant import Tenant
from mcp_paas.services.auth import create_access_token, verify_token
from mcp_paas.services.context_manager import MCPContextManager
from mcp_paas.utils.rate_limiter import RateLimiter

# Temporary bridge so we can import the new gateway package from ./src.
SRC_PATH = Path(__file__).resolve().parent.parent / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.append(str(SRC_PATH))

from mcp_gateway.api import router as gateway_router

# Set up logging
logging.basicConfig(
    level=getattr(logging, settings.LOGGING.LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mcp_paas")

# Initialize metrics
REQUESTS = Counter("http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"])
LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency", ["method", "endpoint"])

# Initialize FastAPI app
app = FastAPI(
    title="MCP PaaS Server",
    description="Model Context Protocol Platform as a Service Implementation",
    version="0.1.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS.ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
context_manager = MCPContextManager()
rate_limiter = RateLimiter()
security = HTTPBearer()


# Middleware to track request metrics
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    
    REQUESTS.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code
    ).inc()
    
    LATENCY.labels(
        method=request.method,
        endpoint=request.url.path
    ).observe(duration)
    
    return response


# Middleware for rate limiting
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Skip rate limiting for certain paths
    if request.url.path in ["/health", "/metrics", "/docs", "/redoc", "/openapi.json"]:
        return await call_next(request)
    
    # Get tenant ID from request if authenticated
    tenant_id = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
        try:
            payload = verify_token(token)
            tenant_id = payload.get("tenant_id")
        except Exception:
            # Continue with default rate limiting if token is invalid
            pass
    
    # Apply rate limiting
    if not await rate_limiter.check_rate_limit(tenant_id or "anonymous", request.url.path):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Rate limit exceeded"},
        )
    
    return await call_next(request)


# Error handler for custom exceptions
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.error(f"HTTP error: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


# Generic error handler
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


# API Models
class ContextCreate(BaseModel):
    model_name: str
    parameters: Dict = Field(default_factory=dict)
    timeout_seconds: Optional[int] = 600


class InferenceRequest(BaseModel):
    input: Union[str, List[str], Dict]
    parameters: Dict = Field(default_factory=dict)


class InferenceResponse(BaseModel):
    output: Union[str, List[str], Dict]
    usage: Dict = Field(default_factory=dict)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


# Mount gateway/control-plane scaffold endpoints.
app.include_router(gateway_router)


# Health check endpoint
@app.get("/health", status_code=200)
async def health_check():
    return {"status": "healthy"}


# Metrics endpoint
@app.get("/metrics", status_code=200)
async def metrics():
    return Response(content=generate_latest().decode(), media_type="text/plain")


# Authentication endpoints
@app.post("/auth/token", response_model=TokenResponse)
async def login(request: LoginRequest):
    tenant = await authenticate_user(request.username, request.password)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(data={"sub": tenant.id, "tenant_id": tenant.id})
    return {"access_token": access_token, "token_type": "bearer"}


# MCP Context endpoints
@app.post("/contexts", response_model=ModelContext, status_code=status.HTTP_201_CREATED)
async def create_context(
    context_create: ContextCreate,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    tenant: Tenant = Depends(get_current_tenant),
):
    logger.info(f"Creating context for tenant: {tenant.id}")
    try:
        context = await context_manager.create_context(
            tenant_id=tenant.id,
            model_name=context_create.model_name,
            parameters=context_create.parameters,
            timeout_seconds=context_create.timeout_seconds,
        )
        return context
    except Exception as e:
        logger.error(f"Failed to create context: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create context: {str(e)}",
        )


@app.get("/contexts/{context_id}", response_model=ModelContext)
async def get_context(
    context_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    tenant: Tenant = Depends(get_current_tenant),
):
    logger.info(f"Getting context {context_id} for tenant: {tenant.id}")
    context = await context_manager.get_context(context_id, tenant.id)
    if not context:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Context {context_id} not found",
        )
    return context


@app.delete("/contexts/{context_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_context(
    context_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    tenant: Tenant = Depends(get_current_tenant),
):
    logger.info(f"Deleting context {context_id} for tenant: {tenant.id}")
    success = await context_manager.delete_context(context_id, tenant.id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Context {context_id} not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/contexts/{context_id}/inference", response_model=InferenceResponse)
async def run_inference(
    context_id: str,
    request: InferenceRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    tenant: Tenant = Depends(get_current_tenant),
):
    logger.info(f"Running inference on context {context_id} for tenant: {tenant.id}")
    context = await context_manager.get_context(context_id, tenant.id)
    if not context:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Context {context_id} not found",
        )
    
    if context.status != ContextStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Context {context_id} is not ready (status: {context.status})",
        )
    
    try:
        result = await context_manager.run_inference(
            context_id=context_id,
            tenant_id=tenant.id,
            input_data=request.input,
            parameters=request.parameters,
        )
        return result
    except Exception as e:
        logger.error(f"Inference failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inference failed: {str(e)}",
        )


# List all contexts for a tenant
@app.get("/contexts", response_model=List[ModelContext])
async def list_contexts(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    tenant: Tenant = Depends(get_current_tenant),
):
    logger.info(f"Listing contexts for tenant: {tenant.id}")
    contexts = await context_manager.list_contexts(tenant.id)
    return contexts


# Server startup and shutdown events
@app.on_event("startup")
async def startup_event():
    logger.info("Starting MCP PaaS server")
    # Initialize services that need startup
    await context_manager.initialize()
    await rate_limiter.initialize()


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down MCP PaaS server")
    # Clean up resources
    await context_manager.shutdown()
    await rate_limiter.shutdown()


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "mcp_paas.server:app",
        host=settings.SERVER.HOST,
        port=settings.SERVER.PORT,
        reload=settings.SERVER.DEBUG,
        log_level=settings.LOGGING.LEVEL.lower(),
    )
