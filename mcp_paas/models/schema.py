import datetime
import enum
from typing import Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Table,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.sql import func

Base = declarative_base()

# Association table for many-to-many relationship between models and tags
model_tags = Table(
    "model_tags",
    Base.metadata,
    Column("model_id", Integer, ForeignKey("models.id")),
    Column("tag_id", Integer, ForeignKey("tags.id")),
)


class ModelStatus(enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    DEPRECATED = "deprecated"


class Tag(Base):
    """Tags for models to enable better organization and searchability."""

    __tablename__ = "tags"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Tag(name='{self.name}')>"


class Model(Base):
    """Model entity representing a machine learning model in the registry."""

    __tablename__ = "models"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    owner = Column(String(100), nullable=False)
    repository_url = Column(String(255), nullable=True)
    license = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    versions = relationship("ModelVersion", back_populates="model", cascade="all, delete-orphan")
    tags = relationship("Tag", secondary=model_tags, backref="models")
    # Latest version reference
    latest_version_id = Column(Integer, ForeignKey("model_versions.id", use_alter=True), nullable=True)
    latest_version = relationship("ModelVersion", foreign_keys=[latest_version_id], post_update=True)

    def __repr__(self):
        return f"<Model(name='{self.name}', owner='{self.owner}')>"


class ModelVersion(Base):
    """Version of a model with specific artifacts and configurations."""

    __tablename__ = "model_versions"

    id = Column(Integer, primary_key=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=False)
    version = Column(String(20), nullable=False)  # Semantic versioning
    status = Column(Enum(ModelStatus), default=ModelStatus.DRAFT)
    artifact_path = Column(String(255), nullable=False)
    checksum = Column(String(64), nullable=True)  # SHA-256 hash of the model artifact
    size_bytes = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Version metadata
    framework = Column(String(50), nullable=True)  # e.g., PyTorch, TensorFlow
    framework_version = Column(String(20), nullable=True)
    python_version = Column(String(20), nullable=True)
    is_production = Column(Boolean, default=False)
    
    # Relationships
    model = relationship("Model", foreign_keys=[model_id], back_populates="versions")
    configurations = relationship("ModelConfiguration", back_populates="model_version", cascade="all, delete-orphan")
    metrics = relationship("ModelMetric", back_populates="model_version", cascade="all, delete-orphan")

    # Ensure unique version per model
    __table_args__ = (
        sqlalchemy.UniqueConstraint('model_id', 'version', name='unique_model_version'),
    )

    def __repr__(self):
        return f"<ModelVersion(model='{self.model.name}', version='{self.version}', status='{self.status.value}')>"


class ModelConfiguration(Base):
    """Configuration for model inference including input/output specs and requirements."""

    __tablename__ = "model_configurations"

    id = Column(Integer, primary_key=True)
    model_version_id = Column(Integer, ForeignKey("model_versions.id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Configuration specifications
    input_schema = Column(JSON, nullable=True)  # JSON schema for input validation
    output_schema = Column(JSON, nullable=True)  # JSON schema for output validation
    hardware_requirements = Column(JSON, nullable=True)  # CPU, memory, GPU requirements
    dependencies = Column(JSON, nullable=True)  # Required packages and versions
    environment_variables = Column(JSON, nullable=True)  # Required environment variables
    
    # Runtime settings
    timeout_seconds = Column(Integer, default=30)
    max_batch_size = Column(Integer, default=1)
    
    # Relationships
    model_version = relationship("ModelVersion", back_populates="configurations")

    def __repr__(self):
        return f"<ModelConfiguration(name='{self.name}', model_version_id='{self.model_version_id}')>"


class ModelMetric(Base):
    """Performance metrics for model versions."""

    __tablename__ = "model_metrics"

    id = Column(Integer, primary_key=True)
    model_version_id = Column(Integer, ForeignKey("model_versions.id"), nullable=False)
    name = Column(String(100), nullable=False)
    value = Column(JSON, nullable=False)  # Store metric value as JSON to support different types
    dataset = Column(String(100), nullable=True)  # Dataset used for evaluation
    timestamp = Column(DateTime, default=func.now())
    
    # Relationships
    model_version = relationship("ModelVersion", back_populates="metrics")

    def __repr__(self):
        return f"<ModelMetric(name='{self.name}', model_version_id='{self.model_version_id}')>"


# Create engine and session factory
def get_engine(db_path="models/registry/registry.db"):
    return create_engine(f"sqlite:///{db_path}", echo=False)


def create_session(engine):
    Session = sessionmaker(bind=engine)
    return Session()


def init_db(db_path="models/registry/registry.db"):
    """Initialize the database and create all tables."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    return engine

