import sqlite3
import hashlib
import json
from typing import Tuple, Optional, Dict, Any
from datetime import datetime
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from mcp_paas.models.tenant import Tenant, ResourceLimits, UsageTracking, AuthProvider

# Database file path - should match the one in init_db.py
DB_FILE = "mcp_paas.db"

# API key header
API_KEY_HEADER = APIKeyHeader(name="X-API-Key")

class AuthenticationError(Exception):
    """Raised when authentication fails"""
    pass

class AuthorizationError(Exception):
    """Raised when authorization fails"""
    pass

def get_db_connection():
    """Get a connection to the SQLite database"""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row  # This enables dictionary-like access to rows
        return conn
    except Exception as e:
        raise Exception(f"Database connection error: {str(e)}")

def validate_api_key(api_key: str) -> Tuple[str, str]:
    """
    Validate an API key and return the tenant_id and user_id associated with it.
    
    Args:
        api_key: The API key to validate
        
    Returns:
        Tuple of (tenant_id, user_id)
        
    Raises:
        AuthenticationError: If the API key is invalid or expired
    """
    if not api_key:
        raise AuthenticationError("API key is required")
    
    # Hash the API key for comparison with stored hash
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Query the database for the API key
        cursor.execute("""
        SELECT ak.id, ak.tenant_id, ak.expires_at, ak.permissions, t.status
        FROM api_keys ak
        JOIN tenants t ON ak.tenant_id = t.id
        WHERE ak.key_hash = ?
        """, (key_hash,))
        
        result = cursor.fetchone()
        
        if not result:
            raise AuthenticationError("Invalid API key")
        
        api_key_id = result['id']
        tenant_id = result['tenant_id']
        expires_at = result['expires_at']
        permissions = json.loads(result['permissions'])
        tenant_status = result['status']
        
        # Check if the tenant is active
        if tenant_status != 'active':
            raise AuthenticationError(f"Tenant is not active (status: {tenant_status})")
        
        # Check if the API key has expired
        if expires_at and datetime.fromisoformat(expires_at) < datetime.now():
            raise AuthenticationError("API key has expired")
        
        # Update last_used_at timestamp
        cursor.execute("""
        UPDATE api_keys
        SET last_used_at = ?
        WHERE id = ?
        """, (datetime.now().isoformat(), api_key_id))
        
        conn.commit()
        
        # Return tenant_id and API key ID as the user_id
        return tenant_id, api_key_id
    
    except AuthenticationError:
        raise  # Re-raise authentication errors
    except Exception as e:
        raise AuthenticationError(f"API key validation error: {str(e)}")
    finally:
        if 'conn' in locals():
            conn.close()

def get_tenant_by_id(tenant_id: str) -> Tenant:
    """
    Retrieve tenant information from the database.
    
    Args:
        tenant_id: The ID of the tenant to retrieve
        
    Returns:
        Tenant: The tenant information
        
    Raises:
        AuthenticationError: If the tenant is not found or not active
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Query the database for the tenant
        cursor.execute("""
        SELECT id, name, email, created_at, updated_at, status, resource_limits
        FROM tenants
        WHERE id = ?
        """, (tenant_id,))
        
        result = cursor.fetchone()
        
        if not result:
            raise AuthenticationError(f"Tenant not found: {tenant_id}")
        
        # Get API keys for the tenant
        cursor.execute("""
        SELECT id, name, created_at, expires_at, permissions
        FROM api_keys
        WHERE tenant_id = ?
        """, (tenant_id,))
        
        api_keys_rows = cursor.fetchall()
        api_keys = []
        
        for key in api_keys_rows:
            # We don't return the actual API keys or hashes for security reasons
            # Just add the key ID to the list for reference
            api_keys.append(key['id'])
        
        # Parse resource limits
        resource_limits_dict = json.loads(result['resource_limits'])
        
        # Convert database row to Tenant model
        tenant = Tenant(
            tenant_id=UUID(result['id']),
            name=result['name'],
            contact_email=result['email'],
            auth_provider=AuthProvider.API_KEY,
            api_keys=api_keys,
            created_at=datetime.fromisoformat(result['created_at']),
            updated_at=datetime.fromisoformat(result['updated_at']),
            enabled=result['status'] == 'active',
            resource_limits=ResourceLimits(
                max_concurrent_contexts=resource_limits_dict.get('max_contexts', 10),
                max_tokens_per_minute=resource_limits_dict.get('max_tokens_per_minute', 100000),
                max_cpu_seconds_per_day=resource_limits_dict.get('max_cpu_seconds_per_day', 3600.0),
                max_memory_mb=resource_limits_dict.get('max_memory_mb', 1024.0),
                storage_limit_mb=resource_limits_dict.get('storage_limit_mb', 5120)
            ),
            usage_tracking=UsageTracking()  # Default usage tracking
        )
        
        return tenant
    
    except AuthenticationError:
        raise  # Re-raise authentication errors
    except Exception as e:
        raise AuthenticationError(f"Error retrieving tenant: {str(e)}")
    finally:
        if 'conn' in locals():
            conn.close()

async def get_current_tenant_from_api_key(api_key: str = Depends(API_KEY_HEADER)) -> Tenant:
    """
    FastAPI dependency for getting the current tenant from an API key.
    
    Args:
        api_key: The API key from the request header
        
    Returns:
        Tenant: The authenticated tenant
        
    Raises:
        HTTPException: If authentication fails
    """
    try:
        tenant_id, _ = validate_api_key(api_key)
        tenant = get_tenant_by_id(tenant_id)
        return tenant
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "ApiKey"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication error: {str(e)}"
        )

from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any
import jwt
from passlib.context import CryptContext
from uuid import UUID
import logging
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from mcp_paas.models.tenant import Tenant


logger = logging.getLogger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 token URL (used by FastAPI security)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# These should come from environment configuration in a real app
JWT_SECRET_KEY = "your-super-secret-key-should-be-in-env-variables"
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 30


class AuthService:
    """
    Service for handling authentication and authorization tasks.
    """
    
    def __init__(self, tenants_db: Dict[UUID, Tenant] = None):
        """Initialize the auth service with a tenant database."""
        self.tenants_db = tenants_db or {}
        
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against a hash."""
        return pwd_context.verify(plain_password, hashed_password)
    
    def get_password_hash(self, password: str) -> str:
        """Generate a hash from a password."""
        return pwd_context.hash(password)
    
    def verify_api_key(self, api_key: str) -> Optional[Tenant]:
        """
        Verify an API key and return the associated tenant.
        
        Args:
            api_key: The API key to verify
            
        Returns:
            The Tenant if valid, None otherwise
        """
        for tenant_id, tenant in self.tenants_db.items():
            if api_key in tenant.api_keys and tenant.enabled:
                return tenant
        return None
    
    def create_jwt_token(
        self, 
        tenant_id: UUID, 
        scopes: List[str] = None,
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        Create a new JWT token for a tenant.
        
        Args:
            tenant_id: The ID of the tenant
            scopes: List of permission scopes to include in the token
            expires_delta: Optional expiration time override
            
        Returns:
            str: The encoded JWT token
        """
        to_encode = {"sub": str(tenant_id)}
        
        if scopes:
            to_encode["scopes"] = scopes
            
        now = datetime.utcnow()
        to_encode.update({"iat": now})
        
        if expires_delta:
            expire = now + expires_delta
        else:
            expire = now + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
            
        to_encode.update({"exp": expire})
        
        return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    
    def verify_token(self, token: str) -> Dict[str, Any]:
        """
        Verify and decode a JWT token.
        
        Args:
            token: The JWT token to verify
            
        Returns:
            Dict[str, Any]: The decoded token payload
            
        Raises:
            AuthenticationError: If the token is invalid or expired
        """
        try:
            payload = jwt.decode(
                token, 
                JWT_SECRET_KEY, 
                algorithms=[JWT_ALGORITHM]
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise AuthenticationError("Token has expired")
        except jwt.InvalidTokenError:
            raise AuthenticationError("Invalid token")
            
    def create_access_token(
        self,
        tenant_id: UUID,
        scopes: List[str] = None,
        expires_minutes: int = JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    ) -> str:
        """
        Create a new access token for a tenant.
        
        Args:
            tenant_id: The tenant ID to encode in the token
            scopes: Optional list of permission scopes
            expires_minutes: Token expiration time in minutes
            
        Returns:
            str: The encoded JWT access token
        """
        expires_delta = timedelta(minutes=expires_minutes)
        return self.create_jwt_token(tenant_id, scopes, expires_delta)
        
    async def get_current_tenant_from_token(
        self, 
        token: str = Depends(oauth2_scheme)
    ) -> Tenant:
        """
        FastAPI dependency for getting the current tenant from a JWT token.
        
        Args:
            token: The JWT token from the Authorization header
            
        Returns:
            Tenant: The authenticated tenant
            
        Raises:
            HTTPException: If authentication fails
        """
        try:
            payload = self.verify_token(token)
            tenant_id = payload.get("sub")
            if tenant_id is None:
                raise AuthenticationError("Invalid token payload")
                
            tenant = self.tenants_db.get(UUID(tenant_id))
            if tenant is None:
                raise AuthenticationError(f"Tenant not found: {tenant_id}")
                
            if not tenant.enabled:
                raise AuthenticationError(f"Tenant is disabled: {tenant_id}")
                
            return tenant
            
        except AuthenticationError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
                headers={"WWW-Authenticate": "Bearer"},
            )
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal authentication error"
            )

# Standalone token management functions for direct import
def create_access_token(
    tenant_id: UUID,
    scopes: List[str] = None,
    expires_minutes: int = JWT_ACCESS_TOKEN_EXPIRE_MINUTES
) -> str:
    """
    Create a new JWT access token for a tenant.
    
    Args:
        tenant_id: The tenant ID to encode in the token
        scopes: Optional list of permission scopes
        expires_minutes: Token expiration time in minutes
        
    Returns:
        str: The encoded JWT access token
    """
    expires_delta = timedelta(minutes=expires_minutes)
    to_encode = {"sub": str(tenant_id)}
    
    if scopes:
        to_encode["scopes"] = scopes
        
    now = datetime.utcnow()
    to_encode.update({"iat": now})
    
    expire = now + expires_delta
    to_encode.update({"exp": expire})
    
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def verify_token(token: str) -> Dict[str, Any]:
    """
    Verify and decode a JWT token.
    
    Args:
        token: The JWT token to verify
        
    Returns:
        Dict[str, Any]: The decoded token payload
        
    Raises:
        AuthenticationError: If the token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token, 
            JWT_SECRET_KEY, 
            algorithms=[JWT_ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Token has expired")
    except jwt.InvalidTokenError:
        raise AuthenticationError("Invalid token")
