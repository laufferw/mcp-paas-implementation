import datetime
import logging
import time
from typing import Dict, List, Optional, Tuple, Union

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, ValidationError

from src.mcp.db.session import get_db
from src.mcp.models.models import Role, User, UserRole, Permission, RolePermission, Tenant
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select

# Setup logging
logger = logging.getLogger(__name__)

# Constants
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7
ALGORITHM = "HS256"
SECRET_KEY = "CHANGE_THIS_TO_LOADED_FROM_ENV_OR_CONFIG"  # In production, load from environment or secure config

# OAuth2 scheme for token handling
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Rate limiter settings
AUTH_RATE_LIMIT = {
    "login": {"limit": 5, "period": 60},  # 5 attempts per minute
    "token_refresh": {"limit": 10, "period": 60},  # 10 attempts per minute
    "registration": {"limit": 3, "period": 3600},  # 3 attempts per hour
}

# In-memory rate limiting cache
# In production, use Redis or similar for distributed rate limiting
rate_limit_cache = {}


class TokenData(BaseModel):
    """Data model for token payload"""
    user_id: int
    username: str
    tenant_id: Optional[int] = None
    roles: List[str] = []
    permissions: List[str] = []
    exp: datetime.datetime


class AuthException(HTTPException):
    """Custom exception for authentication errors"""
    def __init__(self, detail: str, status_code: int = status.HTTP_401_UNAUTHORIZED):
        super().__init__(
            status_code=status_code,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class AuthService:
    """Service for handling authentication, authorization, and user management"""
    
    def __init__(self, db: Session):
        """Initialize the auth service with a database session"""
        self.db = db
    
    async def rate_limit_check(self, action: str, identifier: str) -> bool:
        """Check if an action is rate limited for a specific identifier
        
        Args:
            action: The action being performed (e.g., 'login', 'token_refresh')
            identifier: The identifier to rate limit (e.g., IP address, username)
            
        Returns:
            True if allowed, False if rate limited
        """
        if action not in AUTH_RATE_LIMIT:
            return True
            
        limit = AUTH_RATE_LIMIT[action]["limit"]
        period = AUTH_RATE_LIMIT[action]["period"]
        cache_key = f"{action}:{identifier}"
        
        current_time = int(time.time())
        
        # Initialize or get records
        if cache_key not in rate_limit_cache:
            rate_limit_cache[cache_key] = []
        
        # Clean expired records
        rate_limit_cache[cache_key] = [
            t for t in rate_limit_cache[cache_key] 
            if t > current_time - period
        ]
        
        # Check if limit reached
        if len(rate_limit_cache[cache_key]) >= limit:
            logger.warning(f"Rate limit exceeded for {action} by {identifier}")
            return False
            
        # Add current attempt
        rate_limit_cache[cache_key].append(current_time)
        return True
    
    def _hash_password(self, password: str) -> str:
        """Hash a password using bcrypt
        
        Args:
            password: Plain text password
            
        Returns:
            Hashed password
        """
        return pwd_context.hash(password)
    
    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against a hash
        
        Args:
            plain_password: Plain text password
            hashed_password: Hashed password
            
        Returns:
            True if password matches, False otherwise
        """
        return pwd_context.verify(plain_password, hashed_password)
    
    def _create_token(
        self, 
        data: dict, 
        expires_delta: Optional[datetime.timedelta] = None
    ) -> str:
        """Create a JWT token with payload and expiration
        
        Args:
            data: Token payload data
            expires_delta: Optional expiration delta, defaults to ACCESS_TOKEN_EXPIRE_MINUTES
            
        Returns:
            Encoded JWT token
        """
        to_encode = data.copy()
        
        if expires_delta:
            expire = datetime.datetime.utcnow() + expires_delta
        else:
            expire = datetime.datetime.utcnow() + datetime.timedelta(
                minutes=ACCESS_TOKEN_EXPIRE_MINUTES
            )
            
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        
        return encoded_jwt
    
    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get a user by username
        
        Args:
            username: User's username
            
        Returns:
            User object if found, None otherwise
        """
        try:
            query = select(User).where(User.username == username)
            result = await self.db.execute(query)
            return result.scalars().first()
        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving user: {str(e)}")
            return None
    
    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get a user by email
        
        Args:
            email: User's email
            
        Returns:
            User object if found, None otherwise
        """
        try:
            query = select(User).where(User.email == email)
            result = await self.db.execute(query)
            return result.scalars().first()
        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving user by email: {str(e)}")
            return None
    
    async def authenticate_user(
        self, 
        username_or_email: str, 
        password: str,
        request: Request
    ) -> Optional[User]:
        """Authenticate a user by username/email and password
        
        Args:
            username_or_email: User's username or email
            password: User's password
            request: FastAPI request object for rate limiting
            
        Returns:
            User object if authentication successful, None otherwise
        """
        client_ip = request.client.host
        
        # Check rate limiting
        if not await self.rate_limit_check("login", client_ip):
            logger.warning(f"Login rate limit exceeded for IP {client_ip}")
            raise AuthException(
                "Too many login attempts. Please try again later.",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS
            )
        
        # Try to find user by username or email
        if '@' in username_or_email:
            user = await self.get_user_by_email(username_or_email)
        else:
            user = await self.get_user_by_username(username_or_email)
            
        if not user:
            logger.info(f"Login failed: user not found for {username_or_email}")
            return None
            
        if not user.is_active:
            logger.warning(f"Login attempt for inactive user: {username_or_email}")
            return None
            
        if not self._verify_password(password, user.hashed_password):
            logger.warning(f"Login failed: incorrect password for {username_or_email}")
            return None
            
        logger.info(f"User authenticated successfully: {user.username}")
        return user
    
    async def create_access_token(self, user: User) -> str:
        """Create an access token for a user
        
        Args:
            user: User object
            
        Returns:
            Encoded JWT access token
        """
        # Get user roles and permissions
        user_roles = await self._get_user_roles(user.id)
        permissions = await self._get_user_permissions(user.id)
        
        # Prepare token data
        token_data = {
            "sub": str(user.id),
            "username": user.username,
            "tenant_id": user.tenant_id,
            "roles": user_roles,
            "permissions": permissions
        }
        
        # Create token with standard expiration
        access_token = self._create_token(
            data=token_data,
            expires_delta=datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        
        logger.info(f"Access token created for user: {user.username}")
        return access_token
    
    async def create_refresh_token(self, user: User) -> str:
        """Create a refresh token for a user
        
        Args:
            user: User object
            
        Returns:
            Encoded JWT refresh token
        """
        # Prepare token data (minimal for security)
        token_data = {
            "sub": str(user.id),
            "token_type": "refresh"
        }
        
        # Create token with longer expiration
        refresh_token = self._create_token(
            data=token_data,
            expires_delta=datetime.timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        )
        
        logger.info(f"Refresh token created for user: {user.username}")
        return refresh_token
    
    async def refresh_access_token(
        self, 
        refresh_token: str,
        request: Request
    ) -> Tuple[str, str]:
        """Refresh an access token using a refresh token
        
        Args:
            refresh_token: Refresh token
            request: FastAPI request object for rate limiting
            
        Returns:
            Tuple of new access token and refresh token
        """
        client_ip = request.client.host
        
        # Check rate limiting
        if not await self.rate_limit_check("token_refresh", client_ip):
            logger.warning(f"Token refresh rate limit exceeded for IP {client_ip}")
            raise AuthException(
                "Too many token refresh attempts. Please try again later.",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS
            )
        
        try:
            # Decode and validate refresh token
            payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
            
            # Check token type
            if payload.get("token_type") != "refresh":
                logger.warning("Invalid token type for refresh")
                raise AuthException("Invalid token type")
                
            user_id = int(payload.get("sub"))
            
            # Get user
            query = select(User).where(User.id == user_id)
            result = await self.db.execute(query)
            user = result.scalars().first()
            
            if not user or not user.is_active:
                logger.warning(f"Refresh token used for inactive user: {user_id}")
                raise AuthException("User is inactive or does not exist")
                
            # Create new tokens
            new_access_token = await self.create_access_token(user)
            new_refresh_token = await self.create_refresh_token(user)
            
            logger.info(f"Tokens refreshed for user: {user.username}")
            return new_access_token, new_refresh_token
            
        except jwt.PyJWTError as e:
            logger.error(f"JWT error during token refresh: {str(e)}")
            raise AuthException("Invalid token")
        except Exception as e:
            logger.error(f"Error during token refresh: {str(e)}")
            raise AuthException("Could not refresh token")
    
    async def validate_token(self, token: str) -> TokenData:
        """Validate a JWT token and return its data
        
        Args:
            token: JWT token
            
        Returns:
            TokenData object containing token claims
        """
        try:
            # Decode and validate token
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            
            # Extract basic user info
            user_id = int(payload.get("sub"))
            username = payload.get("username")
            
            if user_id is None or username is None:
                logger.warning("Invalid token payload structure")
                raise AuthException("Invalid token payload")
                
            # Extract additional data if available
            tenant_id = payload.get("tenant_id")
            roles = payload.get("roles", [])
            permissions = payload.get("permissions", [])
            exp = datetime.datetime.fromtimestamp(payload.get("exp"))
            
            # Check token expiration manually (should be caught by jwt.decode, but as a safeguard)
            if datetime.datetime.utcnow() > exp:
                logger.warning(f"Expired token used for user: {username}")
                raise AuthException("Token has expired")
            
            # Check if user still exists and is active
            query = select(User).where(User.id == user_id)
            result = await self.db.execute(query)
            user = result.scalars().first()
            
            if not user:
                logger.warning(f"Token used for non-existent user: {user_id}")
                raise AuthException("User does not exist")
                
            if not user.is_active:
                logger.warning(f"Token used for inactive user: {username}")
                raise AuthException("User is inactive")
                
            # Check if tenant still exists and is active (if applicable)
            if tenant_id:
                query = select(Tenant).where(Tenant.id == tenant_id)
                result = await self.db.execute(query)
                tenant = result.scalars().first()
                
                if not tenant:
                    logger.warning(f"Token used for non-existent tenant: {tenant_id}")
                    raise AuthException("Tenant does not exist")
                    
                if not tenant.is_active:
                    logger.warning(f"Token used for inactive tenant: {tenant_id}")
                    raise AuthException("Tenant is inactive")
            
            # Create and return token data
            token_data = TokenData(
                user_id=user_id,
                username=username,
                tenant_id=tenant_id,
                roles=roles,
                permissions=permissions,
                exp=exp
            )
            
            return token_data
            
        except jwt.ExpiredSignatureError:
            logger.warning("Token validation failed: expired token")
            raise AuthException("Token has expired")
        except jwt.InvalidTokenError:
            logger.warning("Token validation failed: invalid token")
            raise AuthException("Invalid token")
        except ValidationError as e:
            logger.error(f"Token data validation error: {str(e)}")
            raise AuthException("Invalid token data")
        except Exception as e:
            logger.error(f"Unexpected error during token validation: {str(e)}")
            

