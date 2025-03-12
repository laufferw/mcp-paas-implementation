import os
import logging
import datetime
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy import create_engine, update, and_, desc
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

from mcp_paas.models.schema import (
    Base,
    Model,
    ModelVersion,
    ModelStatus,
    ModelConfiguration,
)
from mcp_paas.config import settings

logger = logging.getLogger(__name__)

class RegistryError(Exception):
    """Base exception class for all registry-related errors."""
    pass

class ModelExistsError(RegistryError):
    """Exception raised when attempting to register a model that already exists."""
    pass

class ModelNotFoundError(RegistryError):
    """Exception raised when a requested model is not found."""
    pass

class VersionExistsError(RegistryError):
    """Exception raised when attempting to create a version that already exists."""
    pass

class VersionNotFoundError(RegistryError):
    """Exception raised when a requested version is not found."""
    pass

class InvalidStatusError(RegistryError):
    """Exception raised when attempting to set an invalid status."""
    pass

class ModelRegistry:
    """
    Provides an interface to interact with the model registry database.
    
    This class manages model metadata, versions, and configurations through
    a SQLAlchemy-based interface to the registry database.
    """
    
    def __init__(self, db_url: Optional[str] = None):
        """
        Initialize the ModelRegistry with a connection to the database.
        
        Args:
            db_url: SQLAlchemy database URL. If None, uses the configured default.
        """
        if db_url is None:
            # Use the configured database path or default to a SQLite database in the models/registry directory
            db_path = getattr(settings.DATABASE, 'REGISTRY_PATH', 'models/registry/registry.db')
            db_url = f"sqlite:///{db_path}"
        
        self.engine = create_engine(db_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # Create tables if they don't exist
        Base.metadata.create_all(self.engine)
        logger.info(f"Model registry initialized with database at {db_url}")
    
    def _get_db_session(self) -> Session:
        """
        Get a database session.
        
        Returns:
            A SQLAlchemy Session object.
        """
        return self.SessionLocal()
    
    def register_model(
        self,
        name: str,
        description: str,
        model_type: str,
        tenant_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Model:
        """
        Register a new model in the registry.
        
        Args:
            name: The name of the model
            description: A description of the model
            model_type: The type of model (e.g., "llm", "image", "audio")
            tenant_id: Optional ID of the tenant that owns this model
            tags: Optional list of tags for categorizing the model
            metadata: Optional additional metadata as a dictionary
        
        Returns:
            The created Model object
            
        Raises:
            ModelExistsError: If a model with the given name already exists
        """
        db = self._get_db_session()
        try:
            # Check if model already exists
            existing_model = db.query(Model).filter(Model.name == name).first()
            if existing_model:
                raise ModelExistsError(f"Model with name '{name}' already exists")
            
            # Create new model
            new_model = Model(
                name=name,
                description=description,
                model_type=model_type,
                tenant_id=tenant_id,
                tags=tags or [],
                metadata=metadata or {},
                created_at=datetime.datetime.utcnow(),
                updated_at=datetime.datetime.utcnow(),
                status=ModelStatus.DRAFT.value
            )
            
            db.add(new_model)
            db.commit()
            db.refresh(new_model)
            
            logger.info(f"Registered new model: {name} (ID: {new_model.id})")
            return new_model
        
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error when registering model '{name}': {str(e)}")
            raise RegistryError(f"Failed to register model: {str(e)}")
        
        finally:
            db.close()
    
    def create_model_version(
        self,
        model_id: str,
        version: str,
        artifact_path: str,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ModelVersion:
        """
        Create a new version for an existing model.
        
        Args:
            model_id: The ID of the model
            version: Version string (e.g., "1.0.0")
            artifact_path: Path to the model artifacts
            description: Optional description of the version changes
            metadata: Optional additional metadata as a dictionary
        
        Returns:
            The created ModelVersion object
            
        Raises:
            ModelNotFoundError: If the model doesn't exist
            VersionExistsError: If the version already exists for this model
        """
        db = self._get_db_session()
        try:
            # Check if model exists
            model = db.query(Model).filter(Model.id == model_id).first()
            if not model:
                raise ModelNotFoundError(f"Model with ID '{model_id}' not found")
            
            # Check if version already exists
            existing_version = (
                db.query(ModelVersion)
                .filter(
                    and_(
                        ModelVersion.model_id == model_id,
                        ModelVersion.version == version
                    )
                )
                .first()
            )
            
            if existing_version:
                raise VersionExistsError(
                    f"Version '{version}' already exists for model '{model.name}'"
                )
            
            # Create new version
            new_version = ModelVersion(
                model_id=model_id,
                version=version,
                artifact_path=artifact_path,
                description=description or "",
                metadata=metadata or {},
                created_at=datetime.datetime.utcnow(),
                status=ModelStatus.DRAFT.value
            )
            
            db.add(new_version)
            
            # Update model's updated_at timestamp
            model.updated_at = datetime.datetime.utcnow()
            
            db.commit()
            db.refresh(new_version)
            
            logger.info(f"Created new version '{version}' for model '{model.name}' (ID: {model_id})")
            return new_version
        
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error when creating version '{version}' for model '{model_id}': {str(e)}")
            raise RegistryError(f"Failed to create model version: {str(e)}")
        
        finally:
            db.close()
    
    def get_model(self, model_id: str) -> Model:
        """
        Get a model by its ID.
        
        Args:
            model_id: The ID of the model to retrieve
            
        Returns:
            The Model object
            
        Raises:
            ModelNotFoundError: If the model doesn't exist
        """
        db = self._get_db_session()
        try:
            model = db.query(Model).filter(Model.id == model_id).first()
            if not model:
                raise ModelNotFoundError(f"Model with ID '{model_id}' not found")
            
            return model
            
        except SQLAlchemyError as e:
            logger.error(f"Database error when retrieving model '{model_id}': {str(e)}")
            raise RegistryError(f"Failed to retrieve model: {str(e)}")
            
        finally:
            db.close()
    
    def get_model_by_name(self, name: str) -> Model:
        """
        Get a model by its name.
        
        Args:
            name: The name of the model to retrieve
            
        Returns:
            The Model object
            
        Raises:
            ModelNotFoundError: If the model doesn't exist
        """
        db = self._get_db_session()
        try:
            model = db.query(Model).filter(Model.name == name).first()
            if not model:
                raise ModelNotFoundError(f"Model with name '{name}' not found")
            
            return model
            
        except SQLAlchemyError as e:
            logger.error(f"Database error when retrieving model '{name}': {str(e)}")
            raise RegistryError(f"Failed to retrieve model: {str(e)}")
            
        finally:
            db.close()
    
    def list_models(
        self,
        tenant_id: Optional[str] = None,
        model_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Model]:
        """
        List models with optional filtering.
        
        Args:
            tenant_id: Optional filter by tenant ID
            model_type: Optional filter by model type
            tags: Optional filter by tags (any of the specified tags)
            status: Optional filter by status
            limit: Maximum number of results to return
            offset: Number of results to skip
            
        Returns:
            List of Model objects
        """
        db = self._get_db_session()
        try:
            query = db.query(Model)
            
            # Apply filters
            if tenant_id:
                query = query.filter(Model.tenant_id == tenant_id)
            
            if model_type:
                query = query.filter(Model.model_type == model_type)
            
            if status:
                query = query.filter(Model.status == status)
            
            if tags:
                # Filter for models that have any of the specified tags
                # This depends on the specific implementation of the tags field
                for tag in tags:
                    query = query.filter(Model.tags.contains([tag]))
            
            # Apply pagination
            query = query.order_by(desc(Model.updated_at))
            query = query.limit(limit).offset(offset)
            
            return query.all()
            
        except SQLAlchemyError as e:
            logger.error(f"Database error when listing models: {str(e)}")
            raise RegistryError(f"Failed to list models: {str(e)}")
            
        finally:
            db.close()
    
    def get_model_version(self, model_id: str, version: str) -> ModelVersion:
        """
        Get a specific version of a model.
        
        Args:
            model_id: The ID of the model
            version: The version string
            
        Returns:
            The ModelVersion object
            
        Raises:
            ModelNotFoundError: If the model doesn't exist
            VersionNotFoundError: If the version doesn't exist
        """
        db = self._get_db_session()
        try:
            # Check if model exists
            model = db.query(Model).filter(Model.id == model_id).first()
            if not model:
                raise ModelNotFoundError(f"Model with ID '{model_id}' not found")
            
            # Get the version
            model_version = (
                db.query(ModelVersion)
                .filter(
                    and_(
                        ModelVersion.model_id == model_id,
                        ModelVersion.version == version
                    )
                )
                .first()
            )
            
            if not model_version:
                raise VersionNotFoundError(
                    f"Version '{version}' not found for model '{model.name}'"
                )
            
            return model_version
            
        except SQLAlchemyError as e:
            logger.error(
                f"Database error when retrieving version '{version}' of model '{model_id}': {str(e)}"
            )
            raise RegistryError(f"Failed to retrieve model version: {str(e)}")
            
        finally:
            db.close()
    
    def get_latest_version(self, model_id: str) -> ModelVersion:
        """
        Get the latest version of a model.
        
        Args:
            model_id: The ID of the model
            
        Returns:
            The latest ModelVersion object
            
        Raises:
            ModelNotFoundError: If the model doesn't exist
            VersionNotFoundError: If the model has no versions
        """
        db = self._get_db_session()
        try:
            # Check if model exists
            model = db.query(Model).filter(Model.id == model_id).first()
            if not model:
                raise ModelNotFoundError(f"Model with ID '{model_id}' not found")
            
            # Get the latest version (assuming semantic versioning - might need to adjust based on versioning scheme)
            latest_version = (
                db.query(ModelVersion)
                .filter(ModelVersion.model_id == model_id)
                .order_by(desc(ModelVersion.created_at))
                .first()
            )
            
            if not latest_version:
                raise VersionNotFoundError(
                    f"No versions found for model '{model.name}'"
                )
            
            return latest_version
            
        except SQLAlchemyError as e:
            logger.error(
                f"Database error when retrieving latest version of model '{model_id}': {str(e)}"
            )
            raise RegistryError(f"Failed to retrieve latest model version: {str(e)}")
            
        finally:
            db.close()
    
    def list_model_versions(self, model_id: str) -> List[ModelVersion]:
        """
        List all versions of a model.
        
        Args:
            model_id: The ID of the model
            
        Returns:
            List of ModelVersion objects
            
        Raises:
            ModelNotFoundError: If the model doesn't exist
        """
        db = self._get_db_session()
        try:
            # Check if model exists
            model = db.query(Model).filter(Model.id == model_id).first()
            if not model:
                raise ModelNotFoundError(f"Model with ID '{model_id}' not found")
            
            # Get all versions
            versions = (
                db.query(ModelVersion)
                .filter(ModelVersion.model_id == model_id)
                .order_by(desc(ModelVersion.created_at))
                .all()
            )
            
            return versions
            
        except SQLAlchemyError as e:
            logger.error(
                f"Database error when listing versions of model '{model_id}': {str(e)}"
            )
            raise RegistryError(f"Failed to list model versions: {str(e)}")
            
        finally:
            db.close()
    
    def update_model_status(self, model_id: str, status: str) -> Model:
        """
        Update the status of a model.
        
        Args:
            model_id: The ID of the model
            status: The new status (must be a valid ModelStatus value)
            
        Returns:
            The updated Model object
            
        Raises:
            ModelNotFoundError: If the model doesn't exist
            InvalidStatusError: If the status is not valid
        """
        # Validate status
        try:
            valid_status = ModelStatus(status)
        except ValueError:
            raise InvalidStatusError(f"Invalid status: {status}. Must be one of {[s.value for s in ModelStatus]}")
            
        db = self._get_db_session()
        try:
            # Find the model
            model = db.query(Model).filter(Model.id == model_id).first()
            if not model:
                raise ModelNotFoundError(f"Model with ID '{model_id}' not found")
                
            # Update the status
            model.status = valid_status.value
            model.updated_at = datetime.datetime.utcnow()
            
            db.commit()
            db.refresh(model)
            
            logger.info(f"Updated status of model '{model.name}' (ID: {model_id}) to '{status}'")
            return model
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error when updating status of model '{model_id}': {str(e)}")
            raise RegistryError(f"Failed to update model status: {str(e)}")
            
        finally:
            db.close()

