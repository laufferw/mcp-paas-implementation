import os
import pytest
import uuid
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mcp_paas.models.registry import (
    ModelRegistry,
    ModelExistsError,
    ModelNotFoundError,
    VersionExistsError,
    VersionNotFoundError,
    InvalidStatusError,
)
from mcp_paas.models.schema import Base, Model, ModelVersion, ModelStatus


@pytest.fixture(scope="function")
def test_db_path():
    """Create a unique path for each test's SQLite database."""
    # Use in-memory database for tests
    return ":memory:"


@pytest.fixture(scope="function")
def model_registry(test_db_path):
    """Initialize a model registry with a test database."""
    # Create a unique SQLite database URL for isolation
    db_url = f"sqlite:///{test_db_path}"
    
    # Create registry instance
    registry = ModelRegistry(db_url=db_url)
    
    # Return registry for testing
    yield registry
    
    # Cleanup (important for file-based DBs, less so for in-memory)
    if test_db_path != ":memory:" and os.path.exists(test_db_path):
        os.remove(test_db_path)


@pytest.fixture(scope="function")
def sample_model(model_registry):
    """Create a sample model for testing."""
    model = model_registry.register_model(
        name="test-model",
        description="Test model for unit tests",
        model_type="llm",
        tenant_id="test-tenant",
        tags=["test", "nlp"],
        metadata={"framework": "PyTorch", "epochs": 10}
    )
    return model


@pytest.fixture(scope="function")
def sample_model_version(model_registry, sample_model):
    """Create a sample model version for testing."""
    version = model_registry.create_model_version(
        model_id=sample_model.id,
        version="1.0.0",
        artifact_path="models/artifacts/test-model/v1",
        description="Initial version",
        metadata={"accuracy": 0.95}
    )
    return version


class TestModelRegistry:
    """Test suite for the ModelRegistry class."""
    
    def test_register_model(self, model_registry):
        """Test registering a new model."""
        # Arrange
        model_name = f"test-model-{uuid.uuid4()}"
        
        # Act
        model = model_registry.register_model(
            name=model_name,
            description="Test model",
            model_type="llm",
            tenant_id="test-tenant",
            tags=["test", "llm"],
            metadata={"framework": "PyTorch"}
        )
        
        # Assert
        assert model is not None
        assert model.name == model_name
        assert model.description == "Test model"
        assert model.model_type == "llm"
        assert model.tenant_id == "test-tenant"
        assert "test" in model.tags
        assert "llm" in model.tags
        assert model.metadata.get("framework") == "PyTorch"
        assert model.status == ModelStatus.DRAFT.value
        
        # Verify we can't register the same model twice
        with pytest.raises(ModelExistsError):
            model_registry.register_model(
                name=model_name,
                description="Duplicate model",
                model_type="llm"
            )
    
    def test_create_model_version(self, model_registry, sample_model):
        """Test creating a new model version."""
        # Act
        version = model_registry.create_model_version(
            model_id=sample_model.id,
            version="1.0.0",
            artifact_path="models/artifacts/test-model/v1",
            description="Initial version",
            metadata={"accuracy": 0.95}
        )
        
        # Assert
        assert version is not None
        assert version.model_id == sample_model.id
        assert version.version == "1.0.0"
        assert version.artifact_path == "models/artifacts/test-model/v1"
        assert version.description == "Initial version"
        assert version.metadata.get("accuracy") == 0.95
        assert version.status == ModelStatus.DRAFT.value
        
        # Verify we can't create the same version twice
        with pytest.raises(VersionExistsError):
            model_registry.create_model_version(
                model_id=sample_model.id,
                version="1.0.0",
                artifact_path="models/artifacts/test-model/v1-duplicate"
            )
        
        # Verify we can create a different version
        v2 = model_registry.create_model_version(
            model_id=sample_model.id,
            version="2.0.0",
            artifact_path="models/artifacts/test-model/v2"
        )
        assert v2 is not None
        assert v2.version == "2.0.0"
    
    def test_model_retrieval(self, model_registry, sample_model):
        """Test retrieving models by ID and name."""
        # Retrieve by ID
        model_by_id = model_registry.get_model(sample_model.id)
        assert model_by_id is not None
        assert model_by_id.id == sample_model.id
        assert model_by_id.name == sample_model.name
        
        # Retrieve by name
        model_by_name = model_registry.get_model_by_name(sample_model.name)
        assert model_by_name is not None
        assert model_by_name.id == sample_model.id
        assert model_by_name.name == sample_model.name
        
        # Test retrieval with non-existent ID
        with pytest.raises(ModelNotFoundError):
            model_registry.get_model(999999)
        
        # Test retrieval with non-existent name
        with pytest.raises(ModelNotFoundError):
            model_registry.get_model_by_name("non-existent-model")
    
    def test_list_models(self, model_registry):
        """Test listing models with different filters."""
        # Create multiple models with different attributes
        model_registry.register_model(
            name="test-model-1",
            description="Test model 1",
            model_type="llm",
            tenant_id="tenant-1",
            tags=["test", "llm", "large"]
        )
        
        model_registry.register_model(
            name="test-model-2",
            description="Test model 2",
            model_type="image",
            tenant_id="tenant-1",
            tags=["test", "image"]
        )
        
        model_registry.register_model(
            name="test-model-3",
            description="Test model 3",
            model_type="llm",
            tenant_id="tenant-2",
            tags=["test", "llm", "small"]
        )
        
        # Test listing all models
        all_models = model_registry.list_models()
        assert len(all_models) >= 3
        
        # Test filtering by tenant
        tenant_1_models = model_registry.list_models(tenant_id="tenant-1")
        assert len(tenant_1_models) == 2
        
        # Test filtering by model type
        llm_models = model_registry.list_models(model_type="llm")
        assert len(llm_models) >= 2
        
        # Test filtering by tags
        large_models = model_registry.list_models(tags=["large"])
        assert len(large_models) == 1
        assert large_models[0].name == "test-model-1"
    
    def test_version_retrieval(self, model_registry, sample_model, sample_model_version):
        """Test retrieving model versions."""
        # Retrieve specific version
        version = model_registry.get_model_version(
            model_id=sample_model.id,
            version=sample_model_version.version
        )
        assert version is not None
        assert version.id == sample_model_version.id
        assert version.version == sample_model_version.version
        
        # Test retrieval with non-existent version
        with pytest.raises(VersionNotFoundError):
            model_registry.get_model_version(
                model_id=sample_model.id,
                version="non-existent-version"
            )
        
        # Test latest version retrieval
        latest = model_registry.get_latest_version(model_id=sample_model.id)
        assert latest is not None
        assert latest.id == sample_model_version.id
        
        # Create another version and verify latest changes
        v2 = model_registry.create_model_version(
            model_id=sample_model.id,
            version="2.0.0",
            artifact_path="models/artifacts/test-model/v2"
        )
        
        latest = model_registry.get_latest_version(model_id=sample_model.id)
        assert latest is not None
        assert latest.id == v2.id
        assert latest.version == "2.0.0"
        
        # Test listing all versions
        all_versions = model_registry.list_model_versions(model_id=sample_model.id)
        assert len(all_versions) == 2
        # Versions should be ordered by created_at (newest first)
        assert all_versions[0].version == "2.0.0"
        assert all_versions[1].version == "1.0.0"
    
    def test_update_model_status(self, model_registry, sample_model):
        """Test updating the status of a model."""
        # Verify initial status
        assert sample_model.status == ModelStatus.DRAFT.value
        
        # Update to ACTIVE
        updated_model = model_registry.update_model_status(
            model_id=sample_model.id,
            status=ModelStatus.ACTIVE.value
        )
        assert updated_model is not None
        assert updated_model.status == ModelStatus.ACTIVE.value
        
        # Update to ARCHIVED
        updated_model = model_registry.update_model_status(
            model_id=sample_model.id,
            status=ModelStatus.ARCHIVED.value
        )
        assert updated_model is not None
        assert updated_model.status == ModelStatus.ARCHIVED.value
        
        # Verify we get an error with invalid status
        with pytest.raises(InvalidStatusError):
            model_registry.update_model_status(
                model_id=sample_model.id,
                status="invalid-status"
            )
        
        # Verify status didn't change after error
        model = model_registry.get_model(sample_model.id)
        assert model.status == ModelStatus.ARCHIVED.value

