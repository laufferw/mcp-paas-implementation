import datetime
import logging
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Tuple, Union

import bcrypt
import jwt
from pydantic import BaseModel, EmailStr, Field, validator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
JWT_SECRET = "YOUR_SECRET_KEY_HERE"  # In production, use environment variables
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION = 3600  # 1 hour in seconds
PASSWORD_REGEX = r"^(?=.*[A-Za-z])(?=.*\d)(?=.*[@$!%*#?&])[A-Za-z\d@$!%*#?&]{8,}$"


# Exceptions
class AuthenticationError(Exception):
    """Base class for authentication errors"""
    pass


class InvalidCredentialsError(AuthenticationError):
    """Raised when login credentials are invalid"""
    pass


class UserNotFoundError(AuthenticationError):
    """Raised when a user is not found"""
    pass


class TokenExpiredError(AuthenticationError):
    """Raised when a JWT token has expired"""
    pass


class InvalidTokenError(AuthenticationError):
    """Raised when a JWT token is invalid"""
    pass


class AuthorizationError(Exception):
    """Base class for authorization errors"""
    pass


class InsufficientPermissionsError(AuthorizationError):
    """Raised when user has insufficient permissions"""
    pass


class TenantNotFoundError(AuthorizationError):
    """Raised when a tenant is not found"""
    pass


class RegistrationError(Exception):
    """Base class for registration errors"""
    pass


class UserExistsError(RegistrationError):
    """Raised when trying to register an existing user"""
    pass


class TenantExistsError(RegistrationError):
    """Raised when trying to register an existing tenant"""
    pass


class InvalidPasswordError(RegistrationError):
    """Raised when password doesn't meet requirements"""
    pass


# Enums for Permissions and Roles
class Permission(Enum):
    READ_CONTEXTS = auto()
    CREATE_CONTEXT = auto()
    DELETE_CONTEXT = auto()
    RUN_INFERENCE = auto()
    MANAGE_USERS = auto()
    MANAGE_ROLES = auto()
    MANAGE_TENANT = auto()
    VIEW_METRICS = auto()


class Role(Enum):
    ADMIN = "ADMIN"
    USER = "USER"
    MANAGER = "MANAGER"
    VIEWER = "VIEWER"


# Role to Permission mapping
ROLE_PERMISSIONS = {
    Role.ADMIN: {
        Permission.READ_CONTEXTS,
        Permission.CREATE_CONTEXT,
        Permission.DELETE_CONTEXT,
        Permission.RUN_INFERENCE,
        Permission.MANAGE_USERS,
        Permission.MANAGE_ROLES,
        Permission.MANAGE_TENANT,
        Permission.VIEW_METRICS
    },
    Role.MANAGER: {
        Permission.READ_CONTEXTS,
        Permission.CREATE_CONTEXT,
        Permission.DELETE_CONTEXT,
        Permission.RUN_INFERENCE,
        Permission.MANAGE_USERS,
        Permission.VIEW_METRICS
    },
    Role.USER: {
        Permission.READ_CONTEXTS,
        Permission.CREATE_CONTEXT,
        Permission.RUN_INFERENCE
    },
    Role.VIEWER: {
        Permission.READ_CONTEXTS,
        Permission.VIEW_METRICS
    }
}


# Data Models
@dataclass
class User:
    id: str
    email: str
    hashed_password: str
    first_name: str
    last_name: str
    tenant_id: str
    roles: List[Role] = field(default_factory=list)
    is_active: bool = True
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    last_login: Optional[datetime.datetime] = None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def permissions(self) -> Set[Permission]:
        """Get all permissions this user has based on their roles"""
        all_permissions = set()
        for role in self.roles:
            all_permissions.update(ROLE_PERMISSIONS.get(role, set()))
        return all_permissions

    def has_permission(self, permission: Permission) -> bool:
        """Check if user has a specific permission"""
        return permission in self.permissions

    def has_role(self, role: Role) -> bool:
        """Check if user has a specific role"""
        return role in self.roles


@dataclass
class Tenant:
    id: str
    name: str
    plan_type: str  # e.g., "free", "basic", "premium"
    is_active: bool = True
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    max_contexts: int = 5
    max_users: int = 10
    resource_limits: Dict = field(default_factory=dict)


# Pydantic models for validation
class UserRegistration(BaseModel):
    email: EmailStr
    password: str
    confirm_password: str
    first_name: str
    last_name: str
    tenant_id: str

    @validator('password')
    def password_complexity(cls, v):
        if not re.match(PASSWORD_REGEX, v):
            raise ValueError(
                "Password must be at least 8 characters and include a letter, "
                "a number, and a special character"
            )
        return v

    @validator('confirm_password')
    def passwords_match(cls, v, values):
        if 'password' in values and v != values['password']:
            raise ValueError('Passwords do not match')
        return v


class TenantRegistration(BaseModel):
    name: str
    plan_type: str = "basic"
    admin_email: EmailStr
    admin_password: str
    admin_first_name: str
    admin_last_name: str

    @validator('admin_password')
    def password_complexity(cls, v):
        if not re.match(PASSWORD_REGEX, v):
            raise ValueError(
                "Password must be at least 8 characters and include a letter, "
                "a number, and a special character"
            )
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_id: Optional[str] = None


class TokenData(BaseModel):
    user_id: str
    email: str
    tenant_id: str
    roles: List[str]
    exp: datetime.datetime


# Authentication Service
class AuthService:
    def __init__(self):
        """Initialize the authentication service"""
        self.users: Dict[str, User] = {}  # user_id -> User
        self.tenants: Dict[str, Tenant] = {}  # tenant_id -> Tenant
        self.user_email_index: Dict[Tuple[str, str], str] = {}  # (tenant_id, email) -> user_id
        self.tenant_name_index: Dict[str, str] = {}  # tenant_name -> tenant_id
        logger.info("Authentication service initialized")

    def register_tenant(self, tenant_data: TenantRegistration) -> Tuple[Tenant, User]:
        """
        Register a new tenant with an admin user
        
        Args:
            tenant_data: Tenant registration data including admin user details
            
        Returns:
            Tuple containing the created tenant and admin user
            
        Raises:
            TenantExistsError: If a tenant with the same name already exists
        """
        # Check if tenant name is already in use
        if tenant_data.name in self.tenant_name_index:
            logger.warning(f"Tenant registration failed: {tenant_data.name} already exists")
            raise TenantExistsError(f"Tenant with name '{tenant_data.name}' already exists")

        # Create tenant
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(
            id=tenant_id,
            name=tenant_data.name,
            plan_type=tenant_data.plan_type,
        )

        # Set resource limits based on plan
        if tenant_data.plan_type == "basic":
            tenant.max_contexts = 10
            tenant.max_users = 25
            tenant.resource_limits = {"memory": "2GB", "storage": "10GB"}
        elif tenant_data.plan_type == "premium":
            tenant.max_contexts = 50
            tenant.max_users = 100
            tenant.resource_limits = {"memory": "8GB", "storage": "50GB"}

        # Create admin user
        hashed_password = self._hash_password(tenant_data.admin_password)
        admin_id = str(uuid.uuid4())
        admin_user = User(
            id=admin_id,
            email=tenant_data.admin_email,
            hashed_password=hashed_password,
            first_name=tenant_data.admin_first_name,
            last_name=tenant_data.admin_last_name,
            tenant_id=tenant_id,
            roles=[Role.ADMIN]
        )

        # Store tenant and admin user
        self.tenants[tenant_id] = tenant
        self.tenant_name_index[tenant.name] = tenant_id
        self.users[admin_id] = admin_user
        self.user_email_index[(tenant_id, admin_user.email)] = admin_id

        logger.info(f"Tenant registered: {tenant.name} (ID: {tenant_id}) with admin user")
        return tenant, admin_user

    def register_user(self, user_data: UserRegistration) -> User:
        """
        Register a new user within a tenant
        
        Args:
            user_data: User registration data
            
        Returns:
            The created user
            
        Raises:
            TenantNotFoundError: If tenant doesn't exist
            UserExistsError: If user with email already exists in tenant
            InvalidPasswordError: If password doesn't meet requirements
        """
        # Verify tenant exists
        if user_data.tenant_id not in self.tenants:
            logger.warning(f"User registration failed: Tenant {user_data.tenant_id} not found")
            raise TenantNotFoundError(f"Tenant with ID '{user_data.tenant_id}' not found")

        # Check if email is already registered in tenant
        if (user_data.tenant_id, user_data.email) in self.user_email_index:
            logger.warning(f"User registration failed: {user_data.email} already exists in tenant")
            raise UserExistsError(f"User with email '{user_data.email}' already exists in this tenant")

        # Check tenant user limit
        tenant = self.tenants[user_data.tenant_id]
        tenant_users_count = sum(1 for user in self.users.values() if user.tenant_id == user_data.tenant_id)
        if tenant_users_count >= tenant.max_users:
            logger.warning(f"User registration failed: Tenant {tenant.name} has reached user limit")
            raise RegistrationError(f"Tenant has reached maximum user limit of {tenant.max_users}")

        # Create user
        hashed_password = self._hash_password(user_data.password)
        user_id = str(uuid.uuid4())
        user = User(
            id=user_id,
            email=user_data.email,
            hashed_password=hashed_password,
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            tenant_id=user_data.tenant_id,
            roles=[Role.USER]  # Default role
        )

        # Store user
        self.users[user_id] = user
        self.user_email_index[(user_data.tenant_id, user_data.email)] = user_id

        logger.info(f"User registered: {user.email} in tenant {tenant.name}")
        return user

    def login(self, login_data: LoginRequest) -> Tuple[str, User]:
        """
        Authenticate user and generate JWT token
        
        Args:
            login_data: Login credentials
            
        Returns:
            Tuple containing the JWT token and user object
            
        Raises:
            InvalidCredentialsError: If credentials are invalid
            UserNotFoundError: If user or tenant not found
        """
        # Check if user exists
        user_id = self.user_email_index.get((login_data.tenant_id, login_data.email))
        if not user_id:
            logger.warning(f"Login failed: User {login_data.email} not found in tenant {login_data.tenant_id}")
            raise UserNotFoundError(f"User with email '{login_data.email}' not found in this tenant")

        user = self.users[user_id]

        # Verify password
        if not self._verify_password(login_data.password, user.hashed_password):
            logger.warning(f"Login failed: Invalid password for user {login_data.email}")
            raise InvalidCredentialsError("Invalid email or password")

        # Check if user is active
        if not user.is_active:
            logger.warning(f"Login failed: User {login_data.email} is inactive")
            raise InvalidCredentialsError("User account is inactive")

        # Check if tenant is active
        tenant = self.tenants.get(user.tenant_id)
        if not tenant or not tenant.is_active:
            logger.warning(f"Login failed: Tenant {user.tenant_id} is inactive or not found")
            raise InvalidCredentialsError("Tenant is inactive or not found")

        # Update last login
        user.last_login = datetime.datetime.now()

        # Generate token
        token = self._create_jwt_token(user)

        logger.info(f"User logged in: {user.email} (Tenant: {tenant.name})")
        return token, user

    def validate_token(self, token: str) -> Tuple[User, Tenant]:
        """
        Validate JWT token and return the associated user and tenant
        
        Args:
            token: JWT token to validate
            
        Returns:
            Tuple containing the user and tenant
            
        Raises:
            InvalidTokenError: If token is invalid
            TokenExpiredError: If token has expired
            UserNotFoundError: If user or tenant no longer exists
        """
        try:
            # Decode token
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            token_data = TokenData(**payload)

            # Check if token is expired
            current_time = datetime.datetime.now()
            if token_data.exp < current_time:
                logger.warning("Token validation failed: Token expired")
                raise TokenExpiredError("Token has expired")

            # Get user and tenant
            user = self.users.get(token_data.user_id)
            if not user:
                logger.warning(f"Token validation failed: User {token_data.user_id} not found")
                raise UserNotFoundError("User not found")

            tenant = self.tenants.get(user.tenant_id)
            if not tenant:
                logger.warning(f"Token validation failed: Tenant {user.tenant_id} not found")
                raise TenantNotFoundError("Tenant not found")

            # Check if user and tenant are active
            if not user.is_active:
                logger.warning(f"Token validation failed: User {user.email} is inactive")
                raise InvalidCredentialsError("User account is inactive")

            if not tenant.is_active:
                logger.warning(f"Token validation failed: Tenant {tenant.name} is inactive")
                raise InvalidCredentialsError("Tenant is inactive")

            # Validate that roles stored in token match current user roles
            token_roles = [Role(role) for role in token_data.roles]
            if set(token_roles) != set(user.roles):
                logger.warning(f"Token validation failed: Role mismatch for user {user.email}")
                raise InvalidTokenError("Token contains invalid roles")

            logger.info(f"Token validated for user: {user.email} (Tenant: {tenant.name})")
            return user, tenant

        except jwt.ExpiredSignatureError:
            logger.warning("Token validation failed: Token expired")
            raise TokenExpiredError("Token has expired")
        except jwt.InvalidTokenError:
            logger.warning("Token validation failed: Invalid token")
            raise InvalidTokenError("Invalid token")
        except Exception as e:
            logger.error(f"Token validation failed: {str(e)}")
            raise InvalidTokenError(f"Token validation error: {str(e)}")

    def _hash_password(self, password: str) -> str:
        """
        Hash a password using bcrypt
        
        Args:
            password: Plain text password
            
        Returns:
            Hashed password
        """
        # Generate salt and hash the password
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    
    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        Verify a password against its hash
        
        Args:
            plain_password: Plain text password to verify
            hashed_password: Hashed password to check against
            
        Returns:
            True if password matches, False otherwise
        """
        try:
            return bcrypt.checkpw(
                plain_password.encode('utf-8'),
                hashed_password.encode('utf-8')
            )
        except Exception as e:
            logger.error(f"Password verification error: {str(e)}")
            return False
    
    def _create_jwt_token(self, user: User) -> str:
        """
        Create a JWT token for a user
        
        Args:
            user: User to create token for
            
        Returns:
            JWT token string
        """
        # Set expiration time
        expiration = datetime.datetime.now() + datetime.timedelta(seconds=JWT_EXPIRATION)
        
        # Create token payload
        payload = {
            "user_id": user.id,
            "email": user.email,
            "tenant_id": user.tenant_id,
            "roles": [role.value for role in user.roles],
            "exp": expiration
        }
        
        # Generate token
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        
        return token
    
    def assign_role(self, user_id: str, role: Role, admin_user: User) -> User:
        """
        Assign a role to a user
        
        Args:
            user_id: ID of user to assign role to
            role: Role to assign
            admin_user: User performing the action (must have MANAGE_ROLES permission)
            
        Returns:
            Updated user
            
        Raises:
            UserNotFoundError: If user not found
            InsufficientPermissionsError: If admin_user lacks required permissions
        """
        # Check admin permissions
        if not admin_user.has_permission(Permission.MANAGE_ROLES):
            logger.warning(f"Role assignment failed: User {admin_user.email} lacks permission")
            raise InsufficientPermissionsError("You do not have permission to manage roles")
        
        # Check same tenant
        user = self.users.get(user_id)
        if not user:
            logger.warning(f"Role assignment failed: User {user_id} not found")
            raise UserNotFoundError(f"User with ID '{user_id}' not found")
        
        if user.tenant_id != admin_user.tenant_id:
            logger.warning(f"Role assignment failed: User {user_id} is in different tenant")
            raise InsufficientPermissionsError("Cannot manage users in different tenants")
        
        # Add role if not already assigned
        if role not in user.roles:
            user.roles.append(role)
            logger.info(f"Role {role.value} assigned to user {user.email} by {admin_user.email}")
        
        return user
    
    def remove_role(self, user_id: str, role: Role, admin_user: User) -> User:
        """
        Remove a role from a user
        
        Args:
            user_id: ID of user to remove role from
            role: Role to remove
            admin_user: User performing the action (must have MANAGE_ROLES permission)
            
        Returns:
            Updated user
            
        Raises:
            UserNotFoundError: If user not found
            InsufficientPermissionsError: If admin_user lacks required permissions
        """
        # Check admin permissions
        if not admin_user.has_permission(Permission.MANAGE_ROLES):
            logger.warning(f"Role removal failed: User {admin_user.email} lacks permission")
            raise InsufficientPermissionsError("You do not have permission to manage roles")
        
        # Get user
        user = self.users.get(user_id)
        if not user:
            logger.warning(f"Role removal failed: User {user_id} not found")
            raise UserNotFoundError(f"User with ID '{user_id}' not found")
        
        # Check same tenant
        if user.tenant_id != admin_user.tenant_id:
            logger.warning(f"Role removal failed: User {user_id} is in different tenant")
            raise InsufficientPermissionsError("Cannot manage users in different tenants")
        
        # Prevent removing last admin from tenant
        if role == Role.ADMIN and role in user.roles:
            # Count admins in tenant
            tenant_admins = sum(1 for u in self.users.values() 
                              if u.tenant_id == user.tenant_id 
                              and Role.ADMIN in u.roles
                              and u.is_active)
            
            if tenant_admins <= 1:
                logger.warning(f"Role removal failed: Cannot remove last admin from tenant")
                raise AuthorizationError("Cannot remove the last admin from a tenant")
        
        # Remove role if assigned
        if role in user.roles:
            user.roles.remove(role)
            logger.info(f"Role {role.value} removed from user {user.email} by {admin_user.email}")
        
        return user
    
    def check_permission(self, user_id: str, permission: Permission) -> bool:
        """
        Check if a user has a specific permission
        
        Args:
            user_id: ID of user to check
            permission: Permission to check for
            
        Returns:
            True if user has permission, False otherwise
        """
        user = self.users.get(user_id)
        if not user or not user.is_active:
            return False
        
        tenant = self.tenants.get(user.tenant_id)
        if not tenant or not tenant.is_active:
            return False
        
        return user.has_permission(permission)
    
    def deactivate_user(self, user_id: str, admin_user: User) -> User:
        """
        Deactivate a user account
        
        Args:
            user_id: ID of user to deactivate
            admin_user: User performing the action (must have MANAGE_USERS permission)
            
        Returns:
            Deactivated user
            
        Raises:
            UserNotFoundError: If user not found
            InsufficientPermissionsError: If admin_user lacks required permissions
        """
        # Check admin permissions
        if not admin_user.has_permission(Permission.MANAGE_USERS):
            logger.warning(f"User deactivation failed: User {admin_user.email} lacks permission")
            raise InsufficientPermissionsError("You do not have permission to manage users")
        
        # Get user
        user = self.users.get(user_id)
        if not user:
            logger.warning(f"User deactivation failed: User {user_id} not found")
            raise UserNotFoundError(f"User with ID '{user_id}' not found")
        
        # Check same tenant
        if user.tenant_id != admin_user.tenant_id:
            logger.warning(f"User deactivation failed: User {user_id} is in different tenant")
            raise InsufficientPermissionsError("Cannot manage users in different tenants")
        
        # Prevent deactivating last admin
        if Role.ADMIN in user.roles:
            # Count active admins in tenant
            tenant_admins = sum(1 for u in self.users.values() 
                              if u.tenant_id == user.tenant_id 
                              and Role.ADMIN in u.roles
                              and u.is_active)
            
            if tenant_admins <= 1:
                logger.warning(f"User deactivation failed: Cannot deactivate last admin")
                raise AuthorizationError("Cannot deactivate the last admin of a tenant")
        
        # Deactivate user
        user.is_active = False
        logger.info(f"User {user.email} deactivated by {admin_user.email}")
        
        return user
    
    def reactivate_user(self, user_id: str, admin_user: User) -> User:
        """
        Reactivate a deactivated user account
        
        Args:
            user_id: ID of user to reactivate
            admin_user: User performing the action (must have MANAGE_USERS permission)
            
        Returns:
            Reactivated user
            
        Raises:
            UserNotFoundError: If user not found
            InsufficientPermissionsError: If admin_user lacks required permissions
        """
        # Check admin permissions
        if not admin_user.has_permission(Permission.MANAGE_USERS):
            logger.warning(f"User reactivation failed: User {admin_user.email} lacks permission")
            raise InsufficientPermissionsError("You do not have permission to manage users")
        
        # Get user
        user = self.users.get(user_id)
        if not user:
            logger.warning(f"User reactivation failed: User {user_id} not found")
            raise UserNotFoundError(f"User with ID '{user_id}' not found")
        
        # Check same tenant
        if user.tenant_id != admin_user.tenant_id:
            logger.warning(f"User reactivation failed: User {user_id} is in different tenant")
            raise InsufficientPermissionsError("Cannot manage users in different tenants")
        
        # Check tenant user limit
        if not user.is_active:  # Only count if actually reactivating
            tenant = self.tenants[user.tenant_id]
            active_tenant_users = sum(1 for u in self.users.values() 
                                    if u.tenant_id == user.tenant_id and u.is_active)
            
            if active_tenant_users >= tenant.max_users:
                logger.warning(f"User reactivation failed: Tenant {tenant.name} at user limit")
                raise AuthorizationError(f"Tenant has reached maximum user limit of {tenant.max_users}")
        
        # Reactivate user
        user.is_active = True
        logger.info(f"User {user.email} reactivated by {admin_user.email}")
        
        return user
    
    def deactivate_tenant(self, tenant_id: str, admin_user: User) -> Tenant:
        """
        Deactivate a tenant and all its users
        
        Args:
            tenant_id: ID of tenant to deactivate
            admin_user: User performing the action (must have MANAGE_TENANT permission)
            
        Returns:
            Deactivated tenant
            
        Raises:
            TenantNotFoundError: If tenant not found
            InsufficientPermissionsError: If admin_user lacks required permissions
        """
        # Check admin permissions
        if not admin_user.has_permission(Permission.MANAGE_TENANT):
            logger.warning(f"Tenant deactivation failed: User {admin_user.email} lacks permission")
            raise InsufficientPermissionsError("You do not have permission to manage tenants")
        
        # Get tenant
        tenant = self.tenants.get(tenant_id)
        if not tenant:
            logger.warning(f"Tenant deactivation failed: Tenant {tenant_id} not found")
            raise TenantNotFoundError(f"Tenant with ID '{tenant_id}' not found")
        
        # Verify admin is in same tenant or has global admin privileges
        if admin_user.tenant_id != tenant_id and not admin_user.has_role(Role.ADMIN):
            logger.warning(f"Tenant deactivation failed: User {admin_user.email} not in tenant")
            raise InsufficientPermissionsError("You cannot manage other tenants")
        
        # Deactivate tenant
        tenant.is_active = False
        
        # Log deactivation
        logger.info(f"Tenant {tenant.name} deactivated by {admin_user.email}")
        
        return tenant
    
    def reactivate_tenant(self, tenant_id: str, admin_user: User) -> Tenant:
        """
        Reactivate a deactivated tenant
        
        Args:
            tenant_id: ID of tenant to reactivate
            admin_user: User performing the action (must have MANAGE_TENANT permission)
            
        Returns:
            Reactivated tenant
            
        Raises:
            TenantNotFoundError: If tenant not found
            InsufficientPermissionsError: If admin_user lacks required permissions
        """
        # Check admin permissions
        if not admin_user.has_permission(Permission.MANAGE_TENANT):
            logger.warning(f"Tenant reactivation failed: User {admin_user.email} lacks permission")
            raise InsufficientPermissionsError("You do not have permission to manage tenants")
        
        # Get tenant
        tenant = self.tenants.get(tenant_id)
        if not tenant:
            logger.warning(f"Tenant reactivation failed: Tenant {tenant_id} not found")
            raise TenantNotFoundError(f"Tenant with ID '{tenant_id}' not found")
        
        # Verify admin is in same tenant or has global admin privileges
        if admin_user.tenant_id != tenant_id and not admin_user.has_role(Role.ADMIN):
            logger.warning(f"Tenant reactivation failed: User {admin_user.email} not in tenant")
            raise InsufficientPermiss
