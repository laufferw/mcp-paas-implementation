class ModelException(Exception):
    """Base exception for all model-related errors."""
    pass


class ModelNotFoundError(ModelException):
    """Exception raised when a model is not found."""
    def __init__(self, model_id: str, version_id: str = None):
        message = f"Model '{model_id}' not found"
        if version_id:
            message += f" (version: {version_id})"
        super().__init__(message)
        self.model_id = model_id
        self.version_id = version_id


class ModelVersionNotFoundError(ModelException):
    """Exception raised when a specific model version is not found."""
    def __init__(self, model_id: str, version_id: str):
        super().__init__(f"Version '{version_id}' of model '{model_id}' not found")
        self.model_id = model_id
        self.version_id = version_id


class ModelLoadingError(ModelException):
    """Exception raised when a model fails to load."""
    def __init__(self, model_id: str, version_id: str, cause: str):
        super().__init__(f"Failed to load model '{model_id}' (version: {version_id}): {cause}")
        self.model_id = model_id
        self.version_id = version_id
        self.cause = cause


class ModelInitializationError(ModelException):
    """Exception raised when a model fails to initialize."""
    def __init__(self, model_id: str, version_id: str, cause: str):
        super().__init__(f"Failed to initialize model '{model_id}' (version: {version_id}): {cause}")
        self.model_id = model_id
        self.version_id = version_id
        self.cause = cause


class ModelInferenceError(ModelException):
    """Exception raised when model inference fails."""
    def __init__(self, model_id: str, version_id: str, cause: str):
        super().__init__(f"Inference failed for model '{model_id}' (version: {version_id}): {cause}")
        self.model_id = model_id
        self.version_id = version_id
        self.cause = cause


class ResourceExhaustedError(ModelException):
    """Exception raised when system resources are exhausted."""
    def __init__(self, resource_type: str, limit: float, current: float):
        super().__init__(
            f"Resource exhausted: {resource_type} (limit: {limit}, current: {current})"
        )
        self.resource_type = resource_type
        self.limit = limit
        self.current = current


class InvalidModelConfigError(ModelException):
    """Exception raised when a model configuration is invalid."""
    def __init__(self, model_id: str, details: str):
        super().__init__(f"Invalid configuration for model '{model_id}': {details}")
        self.model_id = model_id
        self.details = details


class ModelTimeoutError(ModelException):
    """Exception raised when a model operation times out."""
    def __init__(self, model_id: str, operation: str, timeout_seconds: float):
        super().__init__(
            f"Operation '{operation}' timed out after {timeout_seconds}s for model '{model_id}'"
        )
        self.model_id = model_id
        self.operation = operation
        self.timeout_seconds = timeout_seconds

