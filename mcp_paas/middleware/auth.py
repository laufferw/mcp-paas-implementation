from typing import Dict, List, Optional, Callable, Union, Tuple
import time
from fastapi import Request, HTTPException, Depends, status, Header
from fastapi.security import OAuth2PasswordBearer, APIKeyHeader
from jose import JWTError, jwt
from pydantic import BaseModel, Field
import logging
from contextvars import ContextVar

from mcp_paas.models.tenant import Tenant
from mcp_paas.config import settings

# Setup logging
logger = logging.getLogger(__name__)

# Context variables for storing tenant and user info
tenant_context: ContextVar[Optional[Tenant]] = ContextVar("tenant_context", default=None)
user_context: ContextVar[Optional[str]] = ContextVar("user_context", default=None)

# Authentication schemes
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

class TokenData(BaseModel):
    """Data model for JWT token payload"""
    sub: str
    tenant_id: str
    roles: List[str] = Field(default_factory=list)
    exp: Optional[int] = None
    permissions: List[str] = Field(default_factory=list)

class AuthMiddleware:
    """
    FastAPI middleware for authentication and authorization.
    Handles JWT validation, tenant context injection and RBAC.
    """
    
    def __init__(
        self, 
        jwt_secret: str = settings.AUTH.SECRET_KEY,
        jwt_algorithm: str = settings.AUTH.ALGORITHM,
        exclude_paths: List[str] = None
    ):
        self.jwt_secret = jwt_secret
        self.jwt_algorithm = jwt_algorithm
        self.exclude_paths = exclude_paths or ["/health", "/docs", "/openapi.json"]
        
    async def __call__(self, request: Request, call_next):
        # Skip authentication for excluded paths
        if any(request.url.path.startswith(path) for path in self.exclude_paths):
            return await call_next(request)
        
        # Extract and validate JWT token
        try:
            token = await self._extract_token(request)
            if not token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing authentication token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            token_data = self._validate_token(token)
            
            # Retrieve tenant data and set in context
            tenant = await self._get_tenant(token_data.tenant_id)
            tenant_token = tenant_context.set(tenant)
            user_token = user_context.set(token_data.sub)
            
            # Validate authorization if needed
            self._check_authorization(request, token_data)
            
            # Process the request
            response = await call_next(request)
            
            # Reset context vars
            tenant_context.reset(tenant_token)
            user_context.reset(user_token)
            
            return response
            
        except HTTPException as e:
            # Re-raise HTTP exceptions
            logger.warning(f"Authentication error: {e.detail}")
            raise
        except Exception as e:
            # Convert other exceptions to HTTP 500
            logger.error(f"Unexpected auth error: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error during authentication",
            )
    
    async def _extract_token(self, request: Request) -> Optional[str]:
        """Extract JWT token from request headers"""
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return None
            
        # Handle "Bearer" token format
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None
            
        return parts[1]
    
    def _validate_token(self, token: str) -> TokenData:
        """Validate JWT token and extract data"""
        try:
            payload = jwt.decode(
                token, 
                self.jwt_secret, 
                algorithms=[self.jwt_algorithm]
            )
            
            # Check if token has expired
            if "exp" in payload and payload["exp"] < time.time():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has expired",
                    headers={"WWW-Authenticate": "Bearer"},
                )
                
            # Validate required fields
            if not all(k in payload for k in ["sub", "tenant_id"]):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token payload",
                    headers={"WWW-Authenticate": "Bearer"},
                )
                
            return TokenData(**payload)
            
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    async def _get_tenant(self, tenant_id: str) -> Tenant:
        """Retrieve tenant information from database or cache"""
        from mcp_paas.services.auth import get_tenant_by_id
        
        tenant = await get_tenant_by_id(tenant_id)
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid tenant ID: {tenant_id}",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return tenant
    
    def _check_authorization(self, request: Request, token_data: TokenData):
        """Validate user has required roles/permissions for this endpoint"""
        # Get required roles and permissions for this path+method combo
        required_roles = self._get_required_roles(request.url.path, request.method)
        required_permissions = self._get_required_permissions(request.url.path, request.method)
        
        # Check roles
        if required_roles and not any(role in token_data.roles for role in required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient roles. Required one of: {required_roles}",
            )
            
        # Check permissions
        if required_permissions and not all(perm in token_data.permissions for perm in required_permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permissions: {required_permissions}",
            )
    
    def _get_required_roles(self, path: str, method: str) -> List[str]:
        """Get required roles for a specific endpoint"""
        # This would typically be configured via decorators or a config file
        # For demonstration, just return empty list (no roles required)
        return []
    
    def _get_required_permissions(self, path: str, method: str) -> List[str]:
        """Get required permissions for a specific endpoint"""
        # This would typically be configured via decorators or a config file
        # For demonstration, just return empty list (no permissions required)
        return []

# Dependency to get current authenticated tenant
async def get_current_tenant() -> Tenant:
    """Get the current tenant from the context variable"""
    tenant = tenant_context.get()
    if tenant is None:
        # Try to authenticate with API key if context is not set
        # This handles direct API calls without going through middleware
        try:
            tenant = await authenticate_with_api_key()
            if tenant:
                return tenant
        except HTTPException:
            pass
            
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return tenant

# Dependency to get current authenticated user
async def get_current_user() -> str:
    """Get the current user from the context variable"""
    user = user_context.get()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

# Role-based access control decorator
def requires_roles(roles: List[str]):
    """Decorator to require specific roles for an endpoint"""
    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            token_data = await get_token_data()
            if not any(role in token_data.roles for role in roles):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Insufficient roles. Required one of: {roles}",
                )
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# Permission-based access control decorator
def requires_permissions(permissions: List[str]):
    """Decorator to require specific permissions for an endpoint"""
    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            token_data = await get_token_data()
            missing_permissions = [p for p in permissions if p not in token_data.permissions]
            if missing_permissions:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Missing required permissions: {missing_permissions}",
                )
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# Helper function to get token data
async def get_token_data(token: str = Depends(oauth2_scheme)) -> TokenData:
    """Get token data from the provided JWT token"""
    try:
        payload = jwt.decode(
            token, 
            settings.AUTH.SECRET_KEY, 
            algorithms=[settings.AUTH.ALGORITHM]
        )
        return TokenData(**payload)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

# API Key authentication
async def authenticate_user(api_key: str = Depends(api_key_header)) -> Tuple[Tenant, str]:
    """
    Authenticate a user using an API key.
    
    Args:
        api_key: The API key provided in the X-API-Key header
        
    Returns:
        A tuple containing (tenant, user_id)
        
    Raises:
        HTTPException: If authentication fails
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is required",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    # Validate the API key and get tenant information
    from mcp_paas.services.auth import validate_api_key
    
    tenant_id, user_id = await validate_api_key(api_key)
    if not tenant_id or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    # Get tenant details
    from mcp_paas.services.auth import get_tenant_by_id
    
    tenant = await get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tenant not found",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    # Set context variables for current request
    tenant_token = tenant_context.set(tenant)
    user_token = user_context.set(user_id)
    
    return tenant, user_id

async def authenticate_with_api_key() -> Optional[Tenant]:
    """
    Attempt to authenticate with an API key from the request headers.
    Returns the tenant if successful, None otherwise.
    """
    try:
        request = Request.scope.get("request")
        if not request:
            return None
            
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return None
            
        tenant, _ = await authenticate_user(api_key)
        return tenant
    except Exception as e:
        logger.warning(f"API key authentication failed: {str(e)}")
        return None

