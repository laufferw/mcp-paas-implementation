#!/usr/bin/env python3
"""
Database initialization script for MCP PaaS.

This script:
1. Sets up database tables for users, tenants, model contexts, and relationships
2. Configures Alembic for schema migrations
3. Creates performance-optimized indexes
4. Seeds initial data
5. Handles environment-specific configuration

Usage:
    python scripts/init_db.py [--reset] [--seed]
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Tuple, Union

import alembic.config
from dotenv import load_dotenv
from sqlalchemy import (Boolean, Column, DateTime, Enum as SQLAEnum, Float,
                       ForeignKey, Integer, MetaData, String, Table, Text,
                       UniqueConstraint, create_engine, event, inspect)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.schema import Index

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("db_init")

# Load environment variables
load_dotenv()

# Get database connection details from environment
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "mcp_paas")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASSWORD", "postgres")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# SQLAlchemy Base
Base = declarative_base()

# Define Enums
class UserStatus(Enum):
    ACTIVE = auto()
    INACTIVE = auto()
    SUSPENDED = auto()

class TenantPlan(Enum):
    FREE = auto()
    BASIC = auto()
    PROFESSIONAL = auto()
    ENTERPRISE = auto()

class TenantStatus(Enum):
    ACTIVE = auto()
    INACTIVE = auto()
    SUSPENDED = auto()
    TRIAL = auto()

class ContextStatus(Enum):
    INITIALIZING = auto()
    ACTIVE = auto()
    FAILED = auto()
    DELETED = auto()

class AuditAction(Enum):
    CREATE = auto()
    READ = auto()
    UPDATE = auto()
    DELETE = auto()
    LOGIN = auto()
    LOGOUT = auto()
    INFERENCE = auto()

# Define Models
class User(Base):
    """User model for authentication and profile data."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), nullable=False, unique=True)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(64))
    last_name = Column(String(64))
    status = Column(SQLAEnum(UserStatus), nullable=False, default=UserStatus.ACTIVE)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime)
    api_key = Column(String(64), unique=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="users")
    roles = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user")

    def __repr__(self):
        return f"<User id={self.id}, username={self.username}, tenant_id={self.tenant_id}>"


class Tenant(Base):
    """Tenant model for multi-tenancy support."""
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, unique=True)
    plan = Column(SQLAEnum(TenantPlan), nullable=False, default=TenantPlan.FREE)
    status = Column(SQLAEnum(TenantStatus), nullable=False, default=TenantStatus.ACTIVE)
    max_contexts = Column(Integer, nullable=False, default=5)
    max_storage_gb = Column(Float, nullable=False, default=1.0)
    max_requests_per_day = Column(Integer, nullable=False, default=1000)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    billing_email = Column(String(255))
    subscription_id = Column(String(64))
    subscription_expires_at = Column(DateTime)

    # Relationships
    users = relationship("User", back_populates="tenant")
    contexts = relationship("ModelContext", back_populates="tenant")
    audit_logs = relationship("AuditLog", back_populates="tenant")

    def __repr__(self):
        return f"<Tenant id={self.id}, name={self.name}, plan={self.plan}>"


class ModelContext(Base):
    """Model Context for inference operations."""
    __tablename__ = "model_contexts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    context_id = Column(String(64), nullable=False, unique=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String(128), nullable=False)
    model_type = Column(String(128), nullable=False)
    status = Column(SQLAEnum(ContextStatus), nullable=False, default=ContextStatus.INITIALIZING)
    config = Column(Text, nullable=False)  # JSON configuration
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_used_at = Column(DateTime)
    resource_usage = Column(Text)  # JSON with usage stats
    created_by = Column(Integer, ForeignKey("users.id"))

    # Relationships
    tenant = relationship("Tenant", back_populates="contexts")
    creator = relationship("User")
    audit_logs = relationship("AuditLog", back_populates="context")

    # Indexes
    __table_args__ = (
        Index("idx_context_tenant", "tenant_id", "context_id"),
        Index("idx_context_status", "status"),
        Index("idx_context_last_used", "last_used_at"),
        UniqueConstraint("tenant_id", "name", name="uq_tenant_context_name"),
    )

    def __repr__(self):
        return f"<ModelContext id={self.id}, context_id={self.context_id}, tenant_id={self.tenant_id}>"


class Role(Base):
    """Role for RBAC."""
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False, unique=True)
    description = Column(String(255))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user_roles = relationship("UserRole", back_populates="role")
    permissions = relationship("RolePermission", back_populates="role", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Role id={self.id}, name={self.name}>"


class Permission(Base):
    """Permission for RBAC."""
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False, unique=True)
    description = Column(String(255))
    resource = Column(String(64), nullable=False)  # e.g., "context", "user", "tenant"
    action = Column(String(64), nullable=False)    # e.g., "create", "read", "update", "delete"
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    role_permissions = relationship("RolePermission", back_populates="permission")

    # Indexes
    __table_args__ = (
        UniqueConstraint("resource", "action", name="uq_permission_resource_action"),
    )

    def __repr__(self):
        return f"<Permission id={self.id}, name={self.name}, resource={self.resource}, action={self.action}>"


class UserRole(Base):
    """Many-to-many relationship between users and roles."""
    __tablename__ = "user_roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="roles")
    role = relationship("Role", back_populates="user_roles")

    # Indexes
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role"),
    )

    def __repr__(self):
        return f"<UserRole user_id={self.user_id}, role_id={self.role_id}>"


class RolePermission(Base):
    """Many-to-many relationship between roles and permissions."""
    __tablename__ = "role_permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    permission_id = Column(Integer, ForeignKey("permissions.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    role = relationship("Role", back_populates="permissions")
    permission = relationship("Permission", back_populates="role_permissions")

    # Indexes
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )

    def __repr__(self):
        return f"<RolePermission role_id={self.role_id}, permission_id={self.permission_id}>"


class AuditLog(Base):
    """Audit log for tracking operations."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    action = Column(SQLAEnum(AuditAction), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"))
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    context_id = Column(Integer, ForeignKey("model_contexts.id"))
    resource_type = Column(String(64), nullable=False)  # e.g., "user", "tenant", "context"
    resource_id = Column(String(64))
    details = Column(Text)  # JSON with operation details
    ip_address = Column(String(45))
    user_agent = Column(String(255))

    # Relationships
    user = relationship("User", back_populates="audit_logs")
    tenant = relationship("Tenant", back_populates="audit_logs")
    context = relationship("ModelContext", back_populates="audit_logs")

    # Indexes
    __table_args__ = (
        Index("idx_audit_tenant", "tenant_id"),
        Index("idx_audit_user", "user_id"),
        Index("idx_audit_timestamp", "timestamp"),
        Index("idx_audit_action", "action"),
        Index("idx_audit_resource", "resource_type", "resource_id"),
    )

    def __repr__(self):
        return f"<AuditLog id={self.id}, action={self.action}, tenant_id={self.tenant_id}>"


class SchemaVersion(Base):
    """Track database schema versions for migrations."""
    __tablename__ = "schema_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(64), nullable=False, unique=True)
    description = Column(String(255))
    applied_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    script_name = Column(String(255))
    applied_by = Column(String(64))

    def __repr__(self):
        return f"<SchemaVersion id={self.id}, version={self.version}, applied_at={self.applied_at}>"


def get_database_url() -> str:
    """Generate database URL from environment variables."""
    return f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


def create_database_engine():
    """Create and configure SQLAlchemy engine."""
    db_url = get_database_url()
    logger.info(f"Connecting to database: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    
    # Create engine with appropriate settings for the environment
    if ENVIRONMENT == "production":
        engine = create_engine(
            db_url,
            pool_size=20,
            max_overflow=40,
            pool_timeout=30,
            pool_recycle=300,
            pool_pre_ping=True,
            echo=False
        )
    else:
        engine = create_engine(
            db_url,
            pool_size=5,
            max_overflow=10,
            pool_recycle=300,
            pool_pre_ping=True,
            echo=True if ENVIRONMENT == "development" else False
        )
    
    return engine


def init_database(engine, reset=False):
    """Initialize the database schema."""
    try:
        if reset:
            logger.warning("Dropping all tables (--reset flag used)")
            Base.metadata.drop_all(engine)
        
        logger.info("Creating database tables...")
        Base.metadata.create_all(engine)
        logger.info("Database tables created successfully")
        
        # Check if we should initialize Alembic
        if not inspect(engine).has_table("alembic_version"):
            logger.info("Initializing Alembic for migrations")
            init_alembic()
            logger.info("Alembic initialized successfully")
        
        return True
    except SQLAlchemyError as e:
        logger.error(f"Database initialization failed: {str(e)}")
        return False


def init_alembic():
    """Initialize Alembic for database migrations."""
    try:
        # Create migrations directory if it doesn't exist
        migrations_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")
        if not os.path.exists(migrations_dir):
            os.makedirs(migrations_dir)
            logger.info(f"Created migrations directory at {migrations_dir}")
        
        # Initialize Alembic
        alembic_args = [
            "--config", os.path.join(migrations_dir, "alembic.ini"), 
            "init", 
            migrations_dir
        ]
        alembic.config.main(argv=alembic_args)
        
        logger.info("Alembic directory structure created")
        
        # Update alembic.ini with database connection
        alembic_ini = os.path.join(migrations_dir, "alembic.ini")
        if os.path.exists(alembic_ini):
            with open(alembic_ini, "r") as f:
                content = f.read()
            
            # Replace SQLite with PostgreSQL connection
            content = content.replace(
                "sqlalchemy.url = driver://user:pass@localhost/dbname",
                f"sqlalchemy.url = {get_database_url()}"
            )
            
            # Update the file
            with open(alembic_ini, "w") as f:
                f.write(content)
            
            logger.info("Updated alembic.ini with database connection")
            
        # Create env.py with proper imports for our models
        env_py = os.path.join(migrations_dir, "env.py")
        if os.path.exists(env_py):
            with open(env_py, "r") as f:
                content = f.read()
            
            # Add import for our models
            model_import = "\n# Import models for Alembic to detect\nimport sys\nimport os\nsys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\nfrom scripts.init_db import Base\n"
            if "from scripts.init_db import Base" not in content:
                insert_pos = content.find("from alembic import context")
                if insert_pos != -1:
                    content = content[:insert_pos] + model_import + content[insert_pos:]
                    
                    # Update target_metadata
                    content = content.replace(
                        "target_metadata = None",
                        "target_metadata = Base.metadata"
                    )
                    
                    # Write updated content
                    with open(env_py, "w") as f:
                        f.write(content)
                        
                    logger.info("Updated env.py with model imports")
                    
        return True
    except Exception as e:
        logger.error(f"Failed to initialize Alembic: {str(e)}")
        return False


def seed_initial_data(session):
    """Seed initial data for roles, permissions, and admin tenant."""
    logger.info("Seeding initial data...")
    
    try:
        # Check if we already have data
        existing_tenant = session.query(Tenant).filter_by(name="admin").first()
        if existing_tenant:
            logger.info("Initial data already exists, skipping seeding")
            return True
            
        # Create default permissions
        logger.info("Creating default permissions")
        permissions = {
            # User permissions
            "user_create": Permission(name="user_create", description="Create users", resource="user", action="create"),
            "user_read": Permission(name="user_read", description="Read user information", resource="user", action="read"),
            "user_update": Permission(name="user_update", description="Update user information", resource="user", action="update"),
            "user_delete": Permission(name="user_delete", description="Delete users", resource="user", action="delete"),
            
            # Tenant permissions
            "tenant_create": Permission(name="tenant_create", description="Create tenants", resource="tenant", action="create"),
            "tenant_read": Permission(name="tenant_read", description="Read tenant information", resource="tenant", action="read"),
            "tenant_update": Permission(name="tenant_update", description="Update tenant information", resource="tenant", action="update"),
            "tenant_delete": Permission(name="tenant_delete", description="Delete tenants", resource="tenant", action="delete"),
            
            # Context permissions
            "context_create": Permission(name="context_create", description="Create model contexts", resource="context", action="create"),
            "context_read": Permission(name="context_read", description="Read model context information", resource="context", action="read"),
            "context_update": Permission(name="context_update", description="Update model context information", resource="context", action="update"),
            "context_delete": Permission(name="context_delete", description="Delete model contexts", resource="context", action="delete"),
            "context_inference": Permission(name="context_inference", description="Run inference on model contexts", resource="context", action="inference"),
        }
        
        for perm in permissions.values():
            session.add(perm)
        session.flush()
        
        # Create roles
        logger.info("Creating default roles")
        roles = {
            "admin": Role(name="admin", description="Administrator with full access"),
            "user": Role(name="user", description="Regular user with limited access"),
            "developer": Role(name="developer", description="Developer with context management access"),
            "readonly": Role(name="readonly", description="Read-only access")
        }
        
        for role in roles.values():
            session.add(role)
        session.flush()
        
        # Assign permissions to roles
        logger.info("Assigning permissions to roles")
        
        # Admin has all permissions
        for perm in permissions.values():
            session.add(RolePermission(role_id=roles["admin"].id, permission_id=perm.id))
        
        # User has read permissions plus context management
        read_perms = ["user_read", "tenant_read", "context_read"]
        context_perms = ["context_create", "context_update", "context_delete", "context_inference"]
        for perm_name in read_perms + context_perms:
            session.add(RolePermission(role_id=roles["user"].id, permission_id=permissions[perm_name].id))
        
        # Developer has context management permissions
        dev_perms = ["user_read", "tenant_read", "context_read", "context_create", 
                     "context_update", "context_delete", "context_inference"]
        for perm_name in dev_perms:
            session.add(RolePermission(role_id=roles["developer"].id, permission_id=permissions[perm_name].id))
        
        # Read-only has read permissions
        read_perms = ["user_read", "tenant_read", "context_read"]
        for perm_name in read_perms:
            session.add(RolePermission(role_id=roles["readonly"].id, permission_id=permissions[perm_name].id))
        
        # Create admin tenant
        logger.info("Creating admin tenant")
        admin_tenant = Tenant(
            name="admin",
            plan=TenantPlan.ENTERPRISE,
            status=TenantStatus.ACTIVE,
            max_contexts=100,
            max_storage_gb=100.0,
            max_requests_per_day=100000,
            billing_email="admin@example.com"
        )
        session.add(admin_tenant)
        session.flush()
        
        # Create admin user
        from hashlib import sha256
        import secrets
        
        # Generate a random default password and hash it
        default_password = secrets.token_hex(8)
        hashed_password = sha256(default_password.encode()).hexdigest()
        
        admin_user = User(
            username="admin",
            email="admin@example.com",
            password_hash=hashed_password,
            first_name="Admin",
            last_name="User",
            status=UserStatus.ACTIVE,
            tenant_id=admin_tenant.id
        )
        session.add(admin_user)
        session.flush()
        
        # Assign admin role to admin user
        session.add(UserRole(user_id=admin_user.id, role_id=roles["admin"].id))
        
        session.commit()
        logger.info(f"Initial data seeded successfully. Admin password: {default_password}")
        return True
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Failed to seed initial data: {str(e)}")
        return False


def check_database_state(engine):
    """Check the state of the database and report any issues."""
    logger.info("Checking database state...")
    
    try:
        inspector = inspect(engine)
        
        # Check if all tables exist
        missing_tables = []
        required_tables = [
            "users", "tenants", "model_contexts", "roles", "permissions",
            "user_roles", "role_permissions", "audit_logs", "schema_versions",
            "alembic_version"
        ]
        
        existing_tables = inspector.get_table_names()
        
        for table in required_tables:
            if table not in existing_tables:
                missing_tables.append(table)
        
        if missing_tables:
            logger.warning(f"Missing tables: {', '.join(missing_tables)}")
            return False
        
        # Make a session to check data
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Check if admin tenant exists
        admin_tenant = session.query(Tenant).filter_by(name="admin").first()
        if not admin_tenant:
            logger.warning("Admin tenant not found, database may need seeding")
            return False
        
        # Check if roles exist
        roles_count = session.query(Role).count()
        if roles_count < 4:  # We should have at least admin, user, developer, readonly
            logger.warning(f"Found only {roles_count} roles, expected at least 4")
            return False
            
        # Check if permissions exist
        permissions_count = session.query(Permission).count()
        if permissions_count < 10:  # We should have multiple permissions
            logger.warning(f"Found only {permissions_count} permissions, expected at least 10")
            return False
        
        logger.info("Database check completed successfully")
        return True
    except Exception as e:
        logger.error(f"Database check failed: {str(e)}")
        return False


def main():
    """Main function to initialize the database."""
    parser = argparse.ArgumentParser(description='Initialize the MCP PaaS database.')
    parser.add_argument('--reset', action='store_true', help='Reset the database (drop all tables)')
    parser.add_argument('--seed', action='store_true', help='Seed initial data')
    parser.add_argument('--check', action='store_true', help='Check database state')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Configure logging
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
    
    # Create engine
    engine = create_database_engine()
    
    # Check database state if requested
    if args.check:
        if check_database_state(engine):
            logger.info("Database is properly configured")
            return 0
        else:
            logger.error("Database configuration issues detected")
            return 1
    
    # Initialize database
    if not init_database(engine, reset=args.reset):
        logger.error("Failed to initialize database")
        return 1
    
    # Seed initial data if requested
    if args.seed or args.reset:  # Always seed after reset
        Session = sessionmaker(bind=engine)
        session = Session()
        if not seed_initial_data(session):
            logger.error("Failed to seed initial data")
            return 1
    
    logger.info("Database initialization completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
