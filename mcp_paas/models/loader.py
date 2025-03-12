import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, Union, Any
import psutil
import numpy as np

from .metrics import ModelMetrics
from .exceptions import (
    ModelNotFoundError,
    ModelLoadError,
    ModelUnloadError,
    ModelVersionError,
    ResourceLimitExceededError,
    ModelHealthCheckError
)

logger = logging.getLogger(__name__)

class ModelLoader:
    """
    Handles model loading, unloading, version management, 
    resource monitoring, and health checks.
    """
    
    def __init__(
        self,
        models_dir: str = "models/artifacts",
        max_memory_usage_percent: float = 80.0,
        cleanup_interval_seconds: int = 300,
        health_check_interval_seconds: int = 600,
        max_models_loaded: int = 10,
        default_model_timeout_seconds: int = 3600
    ):
        """
        Initialize the ModelLoader with configuration parameters.
        
        Args:
            models_dir: Directory where model artifacts are stored
            max_memory_usage_percent: Maximum memory usage before cleanup is triggered
            cleanup_interval_seconds: Interval between periodic cleanup runs
            health_check_interval_seconds: Interval between health checks
            max_models_loaded: Maximum number of models to keep loaded at once
            default_model_timeout_seconds: Default time after which unused models are unloaded
        """
        self.models_dir = models_dir
        self.max_memory_usage_percent = max_memory_usage_percent
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self.health_check_interval_seconds = health_check_interval_seconds
        self.max_models_loaded = max_models_loaded
        self.default_model_timeout_seconds = default_model_timeout_seconds
        
        # Dictionary to track loaded models: {model_id: {"model": model_object, "version": version, ...}}
        self.loaded_models: Dict[str, Dict[str, Any]] = {}
        
        # Dictionary to track model versions: {model_id: {"active": version, "available": [versions]}}
        self.model_versions: Dict[str, Dict[str, Union[str, List[str]]]] = {}
        
        # Dictionary to track model metrics
        self.model_metrics: Dict[str, ModelMetrics] = {}
        
        # Dictionary to track last access time for models
        self.last_accessed: Dict[str, float] = {}
        
        # Dictionary to track health status: {model_id: {"healthy": bool, "last_check": timestamp}}
        self.health_status: Dict[str, Dict[str, Union[bool, float]]] = {}
        
        # Set of models marked for unloading
        self.unload_queue: Set[str] = set()
        
        # Background tasks
        self.cleanup_task = None
        self.health_check_task = None
        
        # Lock for thread-safe operations
        self.lock = asyncio.Lock()
    
    async def initialize(self):
        """
        Initialize the ModelLoader, start background tasks.
        """
        logger.info("Initializing ModelLoader...")
        
        # Start background tasks
        self.cleanup_task = asyncio.create_task(self._periodic_cleanup())
        self.health_check_task = asyncio.create_task(self._periodic_health_check())
        
        # Create models directory if it doesn't exist
        os.makedirs(self.models_dir, exist_ok=True)
        
        # Scan for available models and versions
        await self._scan_available_models()
        
        logger.info(f"ModelLoader initialized. Found {len(self.model_versions)} model(s).")
    
    async def shutdown(self):
        """
        Shutdown the ModelLoader, cancel background tasks and unload all models.
        """
        logger.info("Shutting down ModelLoader...")
        
        # Cancel background tasks
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        
        if self.health_check_task:
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass
        
        # Unload all models
        await self.unload_all_models()
        
        logger.info("ModelLoader shutdown complete.")
    
    async def _scan_available_models(self):
        """
        Scan the models directory to find available models and their versions.
        """
        if not os.path.exists(self.models_dir):
            logger.warning(f"Models directory {self.models_dir} does not exist.")
            return
        
        # Iterate through model directories
        for model_id in os.listdir(self.models_dir):
            model_path = os.path.join(self.models_dir, model_id)
            
            if os.path.isdir(model_path):
                versions = []
                
                # Find all version directories
                for item in os.listdir(model_path):
                    version_path = os.path.join(model_path, item)
                    if os.path.isdir(version_path) and item.startswith("v"):
                        versions.append(item)
                
                if versions:
                    # Sort versions and set the latest as active
                    versions.sort()
                    latest_version = versions[-1]
                    
                    self.model_versions[model_id] = {
                        "active": latest_version,
                        "available": versions
                    }
                    
                    logger.info(f"Found model {model_id} with {len(versions)} version(s). Active: {latest_version}")
                    
                    # Initialize metrics for this model
                    self.model_metrics[model_id] = ModelMetrics(model_id)
    
    async def load_model(self, model_id: str, version: Optional[str] = None) -> Any:
        """
        Load a model with the specified ID and version.
        
        Args:
            model_id: The ID of the model to load
            version: The version to load, or None to use the active version
            
        Returns:
            The loaded model object
            
        Raises:
            ModelNotFoundError: If the model or version doesn't exist
            ModelLoadError: If there's an error loading the model
            ResourceLimitExceededError: If loading the model would exceed memory limits
        """
        start_time = time.time()
        
        async with self.lock:
            # Check if the model is already loaded
            if model_id in self.loaded_models:
                loaded_version = self.loaded_models[model_id]["version"]
                
                # If no version specified or already loaded with the requested version
                if version is None or version == loaded_version:
                    logger.debug(f"Model {model_id}:{loaded_version} already loaded, returning cached instance")
                    # Update last accessed time
                    self.last_accessed[model_id] = time.time()
                    return self.loaded_models[model_id]["model"]
                
                # If different version requested, unload current version
                logger.info(f"Different version requested for {model_id}. Unloading {loaded_version} to load {version}")
                await self.unload_model(model_id)
            
            # Check if model exists
            if model_id not in self.model_versions:
                raise ModelNotFoundError(f"Model {model_id} not found")
            
            # Determine which version to load
            if version is None:
                version = self.model_versions[model_id]["active"]
            elif version not in self.model_versions[model_id]["available"]:
                raise ModelVersionError(f"Version {version} not found for model {model_id}")
            
            # Check if we need to unload models to free memory
            if len(self.loaded_models) >= self.max_models_loaded:
                await self._cleanup_least_used_models(1)
            
            # Check available memory
            if not await self._check_memory_availability():
                await self._cleanup_least_used_models(2)  # Try to free up more memory
                
                if not await self._check_memory_availability():
                    raise ResourceLimitExceededError(
                        f"Memory usage exceeds {self.max_memory_usage_percent}% even after cleanup"
                    )
            
            try:
                # Get model path
                model_path = os.path.join(self.models_dir, model_id, version)
                
                if not os.path.exists(model_path):
                    raise ModelNotFoundError(f"Model path {model_path} not found")
                
                logger.info(f"Loading model {model_id}:{version} from {model_path}")
                
                # This is where the actual model loading would happen
                # For example, using frameworks like TensorFlow, PyTorch, ONNX, etc.
                # For demonstration, we'll just create a placeholder object
                model = {
                    "id": model_id,
                    "version": version,
                    "path": model_path,
                    "loaded_at": datetime.now().isoformat()
                }
                
                # Store the loaded model with metadata
                self.loaded_models[model_id] = {
                    "model": model,
                    "version": version,
                    "path": model_path,
                    "loaded_at": time.time()
                }
                
                # Update last accessed time
                self.last_accessed[model_id] = time.time()
                
                # Update model metrics
                load_time = time.time() - start_time
                
                if model_id not in self.model_metrics:
                    self.model_metrics[model_id] = ModelMetrics(model_id)
                
                self.model_metrics[model_id].record_load(load_time)
                
                # Initialize health status
                self.health_status[model_id] = {
                    "healthy": True,
                    "last_check": time.time()
                }
                
                logger.info(f"Model {model_id}:{version} loaded successfully in {load_time:.2f}s")
                
                return model
                
            except Exception as e:
                error_msg = f"Failed to load model {model_id}:{version} - {str(e)}"
                logger.error(error_msg, exc_info=True)
                
                if model_id in self.model_metrics:
                    self.model_metrics[model_id].record_error("load")
                
                raise ModelLoadError(error_msg) from e
    
    async def unload_model(self, model_id: str) -> bool:
        """
        Unload a model from memory.
        
        Args:
            model_id: The ID of the model to unload
            
        Returns:
            bool: True if the model was unloaded, False if it wasn't loaded
            
        Raises:
            ModelUnloadError: If there's an error unloading the model
        """
        start_time = time.time()
        
        async with self.lock:
            if model_id not in self.loaded_models:
                logger.debug(f"Model {model_id} not loaded, nothing to unload")
                return False
            
            try:
                version = self.loaded_models[model_id]["version"]
                logger.info(f"Unloading model {model_id}:{version}")
                
                # Here you would actually unload the model
                # For example, with PyTorch: del model; torch.cuda.empty_cache()
                
                # Remove from loaded models
                del self.loaded_models[model_id]
                
                # Update last accessed time (actually remove it)
                if model_id in self.last_accessed:
                    del self.last_accessed[model_id]
                
                # Update metrics
                unload_time = time.time() - start_time
                
                if model_id in self.model_metrics:
                    self.model_metrics[model_id].record_unload(unload_time)
                
                # Update health status
                if model_id in self.health_status:
                    del self.health_status[model_id]
                
                # Remove from unload queue if present
                if model_id in self.unload_queue:
                    self.unload_queue.remove(model_id)
                
                logger.info(f"Model {model_id}:{version} unloaded successfully in {unload_time:.2f}s")
                
                return True
                
            except Exception as e:
                error_msg = f"Failed to unload model {model_id} - {str(e)}"
                logger.error(error_msg, exc_info=True)
                
                if model_id in self.model_metrics:
                    self.model_metrics[model_id].record_error("unload")
                
                raise ModelUnloadError(error_msg) from e
    
    async def unload_all_models(self) -> int:
        """
        Unload all currently loaded models.
        
        Returns:
            int: Number of models unloaded
        """
        logger.info("Unloading all models")
        models_to_unload = list(self.loaded_models.keys())
        unload_count = 0
        
        for model_id in models_to_unload:
            try:
                unloaded = await self.unload_model(model_id)
                if unloaded:
                    unload_count += 1
            except Exception as e:
                logger.error(f"Error unloading model {model_id}: {str(e)}", exc_info=True)
        
        logger.info(f"Unloaded {unload_count} model(s)")
        return unload_count
    
    async def switch_version(self, model_id: str, version: str) -> Any:
        """
        Switch a model to a different version.
        
        Args:
            model_id: The ID of the model
            version: The version to switch to
            
        Returns:
            The loaded model with the new version
            
        Raises:
            ModelNotFoundError: If the model doesn't exist
            ModelVersionError: If the version doesn't exist
        """
        async with self.lock:
            # Check if model exists
            if model_id not in self.model_versions:
                raise ModelNotFoundError(f"Model {model_id} not found")
            
            # Check if version exists
            if version not in self.model_versions[model_id]["available"]:
                raise ModelVersionError(f"Version {version} not found for model {model_id}")
            
            # Check if this is already the active version
            if version == self.model_versions[model_id]["active"]:
                logger.debug(f"Version {version} is already active for model {model_id}")
                
                # Load if necessary
                if model_id not in self.loaded_models:
                    return await self.load_model(model_id, version)
                elif self.loaded_models[model_id]["version"] != version:
                    # This shouldn't happen if active version is maintained correctly
                    await self.unload_model(model_id)
                    return await self.load_model(model_id, version)
                else:
                    # Model already loaded with this version
                    self.last_accessed[model_id] = time.time()
                    return self.loaded_models[model_id]["model"]
            
            # Update active version
            old_version = self.model_versions[model_id]["active"]
            old_version = self.model_versions[model_id]["active"]
            self.model_versions[model_id]["active"] = version
            logger.info(f"Switching model {model_id} active version from {old_version} to {version}")
            
            # If model is loaded, unload it and load the new version
            if model_id in self.loaded_models:
                await self.unload_model(model_id)
            
            # Load the new version
            return await self.load_model(model_id, version)

    async def _periodic_cleanup(self):
        """
        Periodic task to cleanup unused models to free memory.
        Runs every cleanup_interval_seconds.
        """
        logger.info(f"Starting model cleanup task with interval of {self.cleanup_interval_seconds}s")
        
        while True:
            try:
                # Wait for the cleanup interval
                await asyncio.sleep(self.cleanup_interval_seconds)
                
                if len(self.loaded_models) == 0:
                    logger.debug("No models loaded, skipping cleanup")
                    continue
                
                logger.debug(f"Running periodic cleanup task. Currently loaded models: {len(self.loaded_models)}")
                
                # Check memory usage
                if not await self._check_memory_availability():
                    logger.info(f"Memory usage exceeds {self.max_memory_usage_percent}%, cleaning up models")
                    await self._cleanup_least_used_models(2)  # Try to free up at least 2 models
                    continue
                
                # Clean up models that haven't been used for a while
                current_time = time.time()
                models_to_unload = []
                
                for model_id, last_accessed in self.last_accessed.items():
                    if current_time - last_accessed > self.default_model_timeout_seconds:
                        logger.info(f"Model {model_id} hasn't been used for {self.default_model_timeout_seconds}s, marking for unload")
                        models_to_unload.append(model_id)
                
                # Unload marked models
                for model_id in models_to_unload:
                    try:
                        await self.unload_model(model_id)
                    except Exception as e:
                        logger.error(f"Error unloading model {model_id} during cleanup: {str(e)}", exc_info=True)
                
                logger.debug(f"Cleanup complete. Models unloaded: {len(models_to_unload)}")
                
            except asyncio.CancelledError:
                logger.info("Model cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in model cleanup task: {str(e)}", exc_info=True)
                await asyncio.sleep(10)  # Short sleep before retrying
    
    async def _periodic_health_check(self):
        """
        Periodic task to check the health of loaded models.
        Runs every health_check_interval_seconds.
        """
        logger.info(f"Starting model health check task with interval of {self.health_check_interval_seconds}s")
        
        while True:
            try:
                # Wait for the health check interval
                await asyncio.sleep(self.health_check_interval_seconds)
                
                if len(self.loaded_models) == 0:
                    logger.debug("No models loaded, skipping health check")
                    continue
                
                logger.debug(f"Running periodic health check task. Currently loaded models: {len(self.loaded_models)}")
                
                # Check health of all loaded models
                for model_id in list(self.loaded_models.keys()):
                    try:
                        healthy = await self._check_model_health(model_id)
                        
                        if not healthy:
                            logger.warning(f"Model {model_id} failed health check, reloading")
                            
                            try:
                                # Get the current version
                                version = self.loaded_models[model_id]["version"]
                                
                                # Unload and reload the model
                                await self.unload_model(model_id)
                                await self.load_model(model_id, version)
                                
                                # Check if reload fixed the issue
                                healthy = await self._check_model_health(model_id)
                                
                                if not healthy:
                                    logger.error(f"Model {model_id} still unhealthy after reload")
                                else:
                                    logger.info(f"Model {model_id} successfully reloaded and now healthy")
                            
                            except Exception as e:
                                logger.error(f"Error reloading model {model_id}: {str(e)}", exc_info=True)
                        
                    except Exception as e:
                        logger.error(f"Error checking health of model {model_id}: {str(e)}", exc_info=True)
                
                logger.debug("Health check complete")
                
            except asyncio.CancelledError:
                logger.info("Model health check task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in model health check task: {str(e)}", exc_info=True)
                await asyncio.sleep(10)  # Short sleep before retrying
    
    async def _check_memory_availability(self) -> bool:
        """
        Check if there's enough memory available based on the maximum memory usage percentage.
        
        Returns:
            bool: True if memory usage is below the threshold, False otherwise
        """
        try:
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            
            # Get system memory info
            system_memory = psutil.virtual_memory()
            
            # Calculate memory usage percentage
            usage_percent = (memory_info.rss / system_memory.total) * 100
            
            logger.debug(f"Current memory usage: {usage_percent:.2f}% ({memory_info.rss / 1024 / 1024:.2f} MB)")
            
            return usage_percent < self.max_memory_usage_percent
        
        except Exception as e:
            logger.error(f"Error checking memory availability: {str(e)}", exc_info=True)
            return True  # Assume memory is available in case of error
    
    async def _cleanup_least_used_models(self, count: int = 1) -> int:
        """
        Unload the least recently used models to free up memory.
        
        Args:
            count: Number of models to unload
            
        Returns:
            int: Number of models actually unloaded
        """
        if not self.last_accessed:
            logger.debug("No models to clean up")
            return 0
        
        # Sort models by last accessed time (oldest first)
        models_by_time = sorted(self.last_accessed.items(), key=lambda x: x[1])
        
        # Take the 'count' oldest models
        models_to_unload = models_by_time[:count]
        
        unloaded_count = 0
        for model_id, _ in models_to_unload:
            try:
                if await self.unload_model(model_id):
                    unloaded_count += 1
            except Exception as e:
                logger.error(f"Error unloading model {model_id} during cleanup: {str(e)}", exc_info=True)
        
        logger.info(f"Cleaned up {unloaded_count} least recently used models")
        return unloaded_count
    
    async def _check_model_health(self, model_id: str) -> bool:
        """
        Check the health of a loaded model.
        
        Args:
            model_id: The ID of the model to check
            
        Returns:
            bool: True if the model is healthy, False otherwise
        """
        if model_id not in self.loaded_models:
            logger.warning(f"Cannot check health of model {model_id}: not loaded")
            return False
        
        async with self.lock:
            start_time = time.time()
            
            try:
                model = self.loaded_models[model_id]["model"]
                version = self.loaded_models[model_id]["version"]
                
                logger.debug(f"Checking health of model {model_id}:{version}")
                
                # This is where you would implement model-specific health checks
                # For example, run a small test inference, check model properties, etc.
                
                # For now, we'll implement a simple check
                if model is None:
                    raise ModelHealthCheckError("Model instance is None")
                
                # Check model attributes based on model type
                # This is placeholder logic - real implementation would depend on model types
                if isinstance(model, dict):
                    if "id" not in model or model["id"] != model_id:
                        raise ModelHealthCheckError("Model ID mismatch")
                
                # Update health status
                health_check_time = time.time() - start_time
                self.health_status[model_id] = {
                    "healthy": True,
                    "last_check": time.time(),
                    "check_duration": health_check_time
                }
                
                # Record health check in metrics
                if model_id in self.model_metrics:
                    self.model_metrics[model_id].record_health_check(True)
                
                logger.debug(f"Model {model_id}:{version} is healthy (check took {health_check_time:.2f}s)")
                return True
                
            except Exception as e:
                error_msg = f"Health check failed for model {model_id}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                
                # Update health status
                self.health_status[model_id] = {
                    "healthy": False,
                    "last_check": time.time(),
                    "error": str(e)
                }
                
                # Record health check failure in metrics
                if model_id in self.model_metrics:
                    self.model_metrics[model_id].record_health_check(False, str(e))
                
                return False
    
    def get_metrics(self, model_id: str = None) -> Dict:
        """
        Get metrics for a specific model or for all models.
        
        Args:
            model_id: The ID of the model to get metrics for, or None for all models
            
        Returns:
            Dict: A dictionary of model metrics
        """
        if model_id is not None:
            if model_id not in self.model_metrics:
                return {}
            
            return self.model_metrics[model_id].get_summary()
        
        # Compile metrics for all models
        all_metrics = {}
        for mid, metrics in self.model_metrics.items():
            all_metrics[mid] = metrics.get_summary()
        
        return all_metrics
    
    def get_model_info(self, model_id: str) -> Dict:
        """
        Get detailed information about a specific model.
        
        Args:
            model_id: The ID of the model
            
        Returns:
            Dict: A dictionary containing model information
            
        Raises:
            ModelNotFoundError: If the model is not found
        """
        if model_id not in self.model_versions:
            raise ModelNotFoundError(f"Model {model_id} not found")
        
        # Build model info
        info = {
            "id": model_id,
            "versions": self.model_versions[model_id]["available"],
            "active_version": self.model_versions[model_id]["active"],
            "loaded": model_id in self.loaded_models,
            "last_accessed": self.last_accessed.get(model_id, None),
            "health": self.health_status.get(model_id, {"healthy": None, "last_check": None}),
            "metrics": self.get_metrics(model_id) if model_id in self.model_metrics else {}
        }
        
        # Add loaded info if model is loaded
        if model_id in self.loaded_models:
            info["loaded_version"] = self.loaded_models[model_id]["version"]
            info["loaded_at"] = self.loaded_models[model_id]["loaded_at"]
        
        return info
    
    def list_available_versions(self, model_id: str = None) -> Dict:
        """
        List available versions for a specific model or for all models.
        
        Args:
            model_id: The ID of the model, or None for all models
            
        Returns:
            Dict: A dictionary mapping model IDs to lists of available versions
            
        Raises:
            ModelNotFoundError: If the specified model is not found
        """
        if model_id is not None:
            if model_id not in self.model_versions:
                raise ModelNotFoundError(f"Model {model_id} not found")
            
            return {
                model_id: {
                    "available": self.model_versions[model_id]["available"],
                    "active": self.model_versions[model_id]["active"]
                }
            }
        
        # Compile versions for all models
        all_versions = {}
        for mid, versions in self.model_versions.items():
            all_versions[mid] = {
                "available": versions["available"],
                "active": versions["active"]
            }
        
        return all_versions

import asyncio
import logging
import os
import time
import gc
import psutil
import json
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from mcp_paas.models.exceptions import (
    ModelInitializationError,
    ModelLoadingError,
    ModelNotFoundError,
    ModelTimeoutError,
    ModelVersionNotFoundError,
    ResourceExhaustedError,
)
from mcp_paas.models.metrics import ModelMetrics


logger = logging.getLogger(__name__)


class ModelLoader:
    """
    Class responsible for loading, caching, and managing model artifacts.
    Handles versioning, memory management, and performance tracking.
    """

    def __init__(
        self,
        artifacts_dir: str,
        max_models_in_memory: int = 10,
        memory_limit_mb: Optional[float] = None,
        cleanup_interval_seconds: int = 3600,
        health_check_interval_seconds: int = 300,
    ):
        self.artifacts_dir = artifacts_dir
        self.max_models_in_memory = max_models_in_memory
        self.memory_limit_mb = memory_limit_mb
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self.health_check_interval_seconds = health_check_interval_seconds
        
        # Internal state
        self._loaded_models: Dict[str, Dict[str, Any]] = {}  # {model_id: {version_id: model_obj}}
        self._model_locks: Dict[str, asyncio.Lock] = {}  # {model_id: lock}
        self._metrics: Dict[str, Dict[str, ModelMetrics]] = {}  # {model_id: {version_id: metrics}}
        self._loaded_versions: Dict[str, str] = {}  # {model_id: active_version_id}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._health_check_task: Optional[asyncio.Task] = None
        self._running: bool = False
        
        # Ensure artifacts directory exists
        os.makedirs(self.artifacts_dir, exist_ok=True)
    
    async def initialize(self) -> None:
        """Initialize the model loader and start background tasks."""
        logger.info("Initializing ModelLoader")
        
        self._running = True
        
        # Start periodic tasks
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        self._health_check_task = asyncio.create_task(self._periodic_health_check())
        
        logger.info("ModelLoader initialized successfully")
    
    async def shutdown(self) -> None:
        """Shutdown the model loader and cleanup resources."""
        logger.info("Shutting down ModelLoader")
        
        self._running = False
        
        # Cancel periodic tasks
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        # Unload all models
        await self.unload_all_models()
        
        logger.info("ModelLoader shutdown complete")

    async def load_model(
        self, 
        model_id: str, 
        version_id: str,
        force_reload: bool = False
    ) -> Any:
        """
        Load a specific model version.
        
        Args:
            model_id: The ID of the model to load
            version_id: The version ID to load
            force_reload: Whether to force reload even if already loaded
            
        Returns:
            The loaded model object
            
        Raises:
            ModelNotFoundError: If the model doesn't exist
            ModelVersionNotFoundError: If the version doesn't exist
            ModelLoadingError: If the model fails to load
            ResourceExhaustedError: If insufficient resources
        """
        # Get or create model lock
        if model_id not in self._model_locks:
            self._model_locks[model_id] = asyncio.Lock()
        
        # Get model metrics tracker
        if model_id not in self._metrics:
            self._metrics[model_id] = {}
        if version_id not in self._metrics[model_id]:
            self._metrics[model_id][version_id] = ModelMetrics(model_id, version_id)
        
        metrics = self._metrics[model_id][version_id]
        
        # Check if already loaded and not forced reload
        if (not force_reload and 
            model_id in self._loaded_models and 
            version_id in self._loaded_models[model_id]):
            
            logger.debug(f"Model {model_id}:{version_id} already loaded, returning cached instance")
            metrics.last_accessed = datetime.now()
            return self._loaded_models[model_id][version_id]
            
        async with self._model_locks[model_id]:
            # Double-check after acquiring the lock
            if (not force_reload and 
                model_id in self._loaded_models and 
                version_id in self._loaded_models[model_id]):
                
                logger.debug(f"Model {model_id}:{version_id} already loaded (checked after lock), returning cached instance")
                metrics.last_accessed = datetime.now()
                return self._loaded_models[model_id][version_id]
            
            # Check available memory before loading
            if self.memory_limit_mb and self._get_memory_usage() >= self.memory_limit_mb:
                # Try to free up memory
                freed_memory = await self._cleanup_least_used_models()
                if self._get_memory_usage() + self._estimate_model_memory(model_id, version_id) > self.memory_limit_mb:
                    raise ResourceExhaustedError(
                        "memory", 
                        self.memory_limit_mb, 
                        self._get_memory_usage()
                    )
            
            # Check if max models limit would be exceeded
            if (len(self._loaded_models) >= self.max_models_in_memory and 
                model_id not in self._loaded_models):
                # Try to unload least used model
                await self._cleanup_least_used_models(count=1)
            
            # Load the model
            model_path = os.path.join(self.artifacts_dir, model_id, version_id)
            if not os.path.exists(model_path):
                model_dir = os.path.join(self.artifacts_dir, model_id)
                if not os.path.exists(model_dir):
                    raise ModelNotFoundError(model_i

import os
import time
import logging
import asyncio
import psutil
import json
from typing import Dict, List, Optional, Union, Set, Tuple, Any
from datetime import datetime
import hashlib

from mcp_paas.models.registry import ModelRegistry, ModelStatus

logger = logging.getLogger(__name__)

class ModelMetrics:
    """Class to track metrics for loaded models"""
    def __init__(self, model_id: str, version: str):
        self.model_id = model_id
        self.version = version
        self.load_time = None  # Time taken to load model
        self.memory_usage = 0  # Memory usage in bytes
        self.inference_count = 0  # Number of inferences
        self.inference_times = []  # List of inference durations
        self.last_used = datetime.now()  # Last time the model was used
        self.health_checks = []  # List of health check results
        self.load_timestamp = None  # When the model was loaded
        self.errors = []  # List of errors encountered
    
    def record_load(self, duration_ms: float, memory_bytes: int):
        """Record model load metrics"""
        self.load_time = duration_ms
        self.memory_usage = memory_bytes
        self.load_timestamp = datetime.now()
    
    def record_inference(self, duration_ms: float):
        """Record a model inference"""
        self.inference_count += 1
        self.inference_times.append(duration_ms)
        self.last_used = datetime.now()
        
        # Keep only the last 100 inference times to avoid memory growth
        if len(self.inference_times) > 100:
            self.inference_times = self.inference_times[-100:]
    
    def record_health_check(self, status: bool, details: str = None):
        """Record health check result"""
        check_result = {"timestamp": datetime.now(), "status": status, "details": details}
        self.health_checks.append(check_result)
        
        # Keep only the last 10 health checks
        if len(self.health_checks) > 10:
            self.health_checks = self.health_checks[-10:]
    
    def record_error(self, error: str):
        """Record an error encountered with the model"""
        error_entry = {"timestamp": datetime.now(), "error": error}
        self.errors.append(error_entry)
        
        # Keep only the last 50 errors
        if len(self.errors) > 50:
            self.errors = self.errors[-50:]
    
    def get_average_inference_time(self) -> float:
        """Get the average inference time for this model"""
        if not self.inference_times:
            return 0
        return sum(self.inference_times) / len(self.inference_times)
    
    def has_been_idle(self, idle_threshold_seconds: int) -> bool:
        """Check if the model has been idle for longer than the threshold"""
        idle_time = (datetime.now() - self.last_used).total_seconds()
        return idle_time > idle_threshold_seconds
    
    def get_summary(self) -> Dict:
        """Get a summary of metrics for this model"""
        return {
            "model_id": self.model_id,
            "version": self.version,
            "load_time_ms": self.load_time,
            "memory_usage_mb": self.memory_usage / (1024 * 1024) if self.memory_usage else 0,
            "inference_count": self.inference_count,
            "avg_inference_time_ms": self.get_average_inference_time(),
            "last_used": self.last_used.isoformat(),
            "load_timestamp": self.load_timestamp.isoformat() if self.load_timestamp else None,
            "health_status": self.health_checks[-1]["status"] if self.health_checks else None,
            "error_count": len(self.errors)
        }


class ModelLoader:
    """
    Handles loading, unloading, and management of model artifacts.
    Provides versioning support, health monitoring, and memory management.
    """
    def __init__(self, registry: ModelRegistry, artifacts_dir: str = "models/artifacts", 
                 config_dir: str = "models/configs", max_models: int = 10,
                 memory_threshold_mb: int = 1024, cleanup_interval_sec: int = 300,
                 health_check_interval_sec: int = 600):
        self.registry = registry
        self.artifacts_dir = artifacts_dir
        self.config_dir = config_dir
        self.max_models = max_models
        self.memory_threshold_mb = memory_threshold_mb
        self.cleanup_interval_sec = cleanup_interval_sec
        self.health_check_interval_sec = health_check_interval_sec
        
        # Dictionary to track loaded models: {model_id: {version: model_object}}
        self.loaded_models: Dict[str, Dict[str, Any]] = {}
        
        # Dictionary to track metrics for loaded models: {model_id: {version: ModelMetrics}}
        self.metrics: Dict[str, Dict[str, ModelMetrics]] = {}
        
        self._cleanup_task = None
        self._health_check_task = None
        self._running = False
        self._lock = asyncio.Lock()
    
    async def initialize(self):
        """Initialize the model loader and start background tasks"""
        logger.info("Initializing ModelLoader")
        self._running = True
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        self._health_check_task = asyncio.create_task(self._periodic_health_check())
        logger.info("ModelLoader initialized successfully")
    
    async def shutdown(self):
        """Shutdown the model loader and clean up resources"""
        logger.info("Shutting down ModelLoader")
        self._running = False
        
        # Cancel background tasks
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        # Unload all models
        models_to_unload = []
        for model_id, versions in self.loaded_models.items():
            for version in versions:
                models_to_unload.append((model_id, version))
        
        for model_id, version in models_to_unload:
            await self.unload_model(model_id, version)
        
        logger.info("ModelLoader shutdown complete")
    
    async def load_model(self, model_id: str, version: str = None) -> Tuple[Any, str]:
        """
        Load a model by ID and version.
        If version is None, load the latest version.
        
        Returns:
            Tuple of (model_object, version)
        """
        async with self._lock:
            # Check if model is already loaded
            if model_id in self.loaded_models and version in self.loaded_models[model_id]:
                # Update last used time
                if model_id in self.metrics and version in self.metrics[model_id]:
                    self.metrics[model_id][version].last_used = datetime.now()
                return self.loaded_models[model_id][version], version
            
            # Check if we need to clean up before loading new model
            if self._should_clean_up():
                await self._perform_cleanup()
            
            # Get model info from registry
            if version is None:
                model_info = await self.registry.get_latest_model_version(model_id)
                if not model_info:
                    raise ValueError(f"No versions found for model {model_id}")
                version = model_info.version
            else:
                model_info = await self.registry.get_model_version(model_id, version)
                if not model_info:
                    raise ValueError(f"Version {version} not found for model {model_id}")
            
            # Check if model is active
            model = await self.registry.get_model(model_id)
            if model.status != ModelStatus.ACTIVE:
                raise ValueError(f"Model {model_id} is not active (status: {model.status.name})")
            
            # Prepare metrics tracking
            if model_id not in self.metrics:
                self.metrics[model_id] = {}
            
            metrics = ModelMetrics(model_id, version)
            self.metrics[model_id][version] = metrics
            
            # Load the model
            logger.info(f"Loading model {model_id} version {version}")
            start_time = time.time()
            
            try:
                # Get paths for model artifacts and config
                artifact_path = os.path.join(self.artifacts_dir, model_id, version)
                config_path = os.path.join(self.config_dir, model_id, f"{version}.json")
                
                # Check if paths exist
                if not os.path.exists(artifact_path):
                    raise FileNotFoundError(f"Model artifact path not found: {artifact_path}")
                
                if not os.path.exists(config_path):
                    raise FileNotFoundError(f"Model config not found: {config_path}")
                
                # Load config
                with open(config_path, 'r') as f:
                    config = json.load(f)
                
                # TODO: This would be replaced with actual model loading code
                # For now, just simulate loading a model
                await asyncio.sleep(0.1)  # Simulate loading time
                model_object = {"model_id": model_id, "version": version, "config": config}
                
                # Initialize the loaded_models dict for this model_id if it doesn't exist
                if model_id not in self.loaded_models:
                    self.loaded_models[model_id] = {}
                
                # Store the loaded model
                self.loaded_models[model_id][version] = model_object
                
                # Record load metrics
                load_time = (time.time() - start_time) * 1000  # Convert to ms
                process = psutil.Process(os.getpid())
                memory_usage = process.memory_info().rss  # in bytes
                metrics.record_load(load_time, memory_usage)
                
                logger.info(f"Model {model_id} version {version} loaded successfully in {load_time:.2f}ms")
                
                # Run initial health check
                await self._check_model_health(model_id, version)
                
                return model_object, version
                
            except Exception as e:
                if model_id in self.metrics and version in self.metrics[model_id]:
                    self.metrics[model_id][version].record_error(str(e))
                logger.error(f"Error loading model {model_id} version {version}: {str(e)}")
                raise
    
    async def unload_model(self, model_id: str, version: str) -> bool:
        """Unload a specific model version"""
        async with self._lock:
            if model_id not in self.loaded_models or version not in self.loaded_models[model_id]:
                logger.warning(f"Cannot unload model {model_id} version {version}: not loaded")
                return False
            
            logger.info(f"Unloading model {model_id} version {version}")
            
            try:
                # TODO: This would be replaced with actual model unloading code
                # For example, calling model.unload() or clearing CUDA memory
                model_object = self.loaded_models[model_id][version]
                
                # Remove the model from loaded_models
                del self.loaded_models[model_id][version]
                
                # Clean up empty dictionaries
                if not self.loaded_models[model_id]:
                    del self.loaded_models[model_id]
                
                # Keep metrics for later reporting
                logger.info(f"Model {model_id} version {version} unloaded successfully")
                return True
                
            except Exception as e:
                if model_id in self.metrics and version in self.metrics[model_id]:
                    self.metrics[model_id][version].record_error(str(e))
                logger.error(f"Error unloading model {model_id} version {version}: {str(e)}")
                return False
    
    async def switch_model_version(self, model_id: str, target_version: str) -> Tuple[Any, str]:
        """Switch to a different version of a model, unloading current version if needed"""
        async with self._lock:
            # First, check if the target version is already loaded
            if (model_id in self.loaded_models and 
                target_version in self.loaded_models[model_id]):
                logger.info(f"Target version {target_version} of model {model_id} already loaded")
                return self.loaded_models[model_id][target_version], target_version
            
            # Find current loaded versions
            current_versions = []
            if model_id in self.loaded_models:
                current_versions = list(self.loaded_models[model_id].keys())
            
            # Load the target version
            model_object, version = await self.load_model(model_id, target_version)
            
            # Unload previous versions if they're different from the target
            for v in current_versions:
                if v != target_version:
                    await self.unload_model(model_id, v)
            
            return model_object, version
    
    async def get_model(self, model_id: str, version: str = None) -> Tuple[Any, str]:
        """
        Get a loaded model or load it if not loaded.
        If version is None, get the latest version.
        """
        # Try to get the model if already loaded
        if model_id in self.loaded_models:
            if version and version in self.loaded_models[model_id]:
                # Update last used time
                if model_id in self.metrics and version in self.metrics[model_id]:
                    self.metrics[model_id][version].last_used = datetime.now()
                return self.loaded_models[model_id][version], version
            elif not version and self.loaded_models[model_id]:
                # Get the highest version number that's loaded
                loaded_versions = list(self.loaded_models[model_id].keys())
                loaded_versions.sort(key=lambda v: [int(x) for x in v.split('.')])
                latest_version = loaded_versions[-1]
                
                # Update last used time
                if model_id in self.metrics and latest_version in self.metrics[model_id]:
                    self.metrics[model_id][latest_version].last_used = datetime.now()
                
                return self.loaded_models[model_id][latest_version], latest_version
        
        # If we get here, we need to load the model
        return await self.load_model(model_id, version)
    
    async def record_inference(self, model_id: str, version: str, duration_ms: float):
        """Record an inference for a model"""
        if model_id in self.metrics and version in self.metrics[model_id]:
            self.metrics[model_id][version].record_inference(duration_ms)
    
    async def get_model_metrics(self, model_id: str = None, version: str = None) -> Dict:
        """Get metrics for a specific model or all loaded models"""
        if model_id:
            if model_id not in self.metrics:
                raise ValueError(f"No metrics available for model

import os
import time
import asyncio
import logging
import traceback
from typing import Dict, List, Optional, Any, Set, Tuple
from datetime import datetime, timedelta
import psutil
import numpy as np
from pydantic import BaseModel

from mcp_paas.models.registry import ModelRegistry
from mcp_paas.models.schema import ModelVersion, ModelStatus, Model
from mcp_paas.config import settings

logger = logging.getLogger(__name__)

class ModelMetrics(BaseModel):
    """Tracks runtime metrics for a loaded model."""
    load_time: float = 0.0
    inference_count: int = 0
    total_inference_time: float = 0.0
    avg_inference_time: float = 0.0
    last_used: datetime = datetime.now()
    memory_usage: int = 0  # in bytes
    peak_memory_usage: int = 0  # in bytes
    health_status: bool = True
    failed_health_checks: int = 0
    
    def update_inference_metrics(self, inference_time: float):
        """Update metrics after an inference call."""
        self.inference_count += 1
        self.total_inference_time += inference_time
        self.avg_inference_time = self.total_inference_time / self.inference_count
        self.last_used = datetime.now()

    def update_memory_usage(self, current_usage: int):
        """Update memory usage statistics."""
        self.memory_usage = current_usage
        if current_usage > self.peak_memory_usage:
            self.peak_memory_usage = current_usage


class ModelLoadError(Exception):
    """Exception raised for errors in model loading."""
    pass


class ModelValidationError(Exception):
    """Exception raised for errors in model validation."""
    pass


class ModelLoader:
    """Manages loading, unloading, and versioning of models."""
    
    def __init__(self, 
                 model_registry: ModelRegistry,
                 artifacts_dir: str = "models/artifacts",
                 configs_dir: str = "models/configs",
                 cleanup_interval: int = 3600,  # 1 hour
                 health_check_interval: int = 600,  # 10 minutes
                 max_memory_usage: int = 0,  # 0 means no limit
                 idle_threshold: int = 1800):  # 30 minutes
        
        self.model_registry = model_registry
        self.artifacts_dir = artifacts_dir
        self.configs_dir = configs_dir
        self.cleanup_interval = cleanup_interval
        self.health_check_interval = health_check_interval
        self.max_memory_usage = max_memory_usage or settings.RESOURCES.MAX_MEMORY_USAGE
        self.idle_threshold = idle_threshold
        
        # Model cache
        self._loaded_models: Dict[str, Dict[str, Any]] = {}  # {model_id: {version_id: model_instance}}
        self._active_versions: Dict[str, str] = {}  # {model_id: active_version_id}
        self._model_metrics: Dict[str, Dict[str, ModelMetrics]] = {}  # {model_id: {version_id: metrics}}
        
        # Task management
        self._cleanup_task = None
        self._health_check_task = None
        self._locks: Dict[str, asyncio.Lock] = {}  # {model_id: lock}
        self._running = False
        
    async def initialize(self):
        """Initialize the model loader and start periodic tasks."""
        logger.info("Initializing ModelLoader...")
        self._running = True
        
        # Start periodic tasks
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        self._health_check_task = asyncio.create_task(self._periodic_health_check())
        
        logger.info("ModelLoader initialized successfully")
        return self
    
    async def shutdown(self):
        """Shutdown the model loader and cleanup resources."""
        logger.info("Shutting down ModelLoader...")
        self._running = False
        
        # Cancel periodic tasks
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        # Unload all models
        await self.unload_all_models()
        logger.info("ModelLoader shutdown complete")
    
    async def load_model(self, model_id: str, version_id: Optional[str] = None) -> Tuple[Any, ModelMetrics]:
        """
        Load a model with the specified version or the latest version if not specified.
        
        Args:
            model_id: The ID of the model to load
            version_id: The specific version to load, or None for the latest
            
        Returns:
            Tuple of (model instance, model metrics)
            
        Raises:
            ModelLoadError: If the model cannot be loaded
        """
        # Get or create lock for this model
        if model_id not in self._locks:
            self._locks[model_id] = asyncio.Lock()
        
        async with self._locks[model_id]:
            # Get model info from registry
            try:
                model = await self.model_registry.get_model(model_id)
                if not model:
                    raise ModelLoadError(f"Model {model_id} not found in registry")
                
                # Get the version to load
                if not version_id:
                    version = await self.model_registry.get_latest_version(model_id)
                    if not version:
                        raise ModelLoadError(f"No versions found for model {model_id}")
                    version_id = version.id
                else:
                    version = await self.model_registry.get_model_version(model_id, version_id)
                    if not version:
                        raise ModelLoadError(f"Version {version_id} not found for model {model_id}")
                
                # Check if model is already loaded
                if model_id in self._loaded_models and version_id in self._loaded_models[model_id]:
                    # Update last used time
                    if model_id in self._model_metrics and version_id in self._model_metrics[model_id]:
                        self._model_metrics[model_id][version_id].last_used = datetime.now()
                    
                    # Return the loaded model
                    return self._loaded_models[model_id][version_id], self._model_metrics[model_id][version_id]
                
                # Load the model
                start_time = time.time()
                model_instance = await self._load_model_from_path(model, version)
                load_time = time.time() - start_time
                
                # Initialize model metrics
                metrics = ModelMetrics(load_time=load_time)
                
                # Track memory usage
                process = psutil.Process(os.getpid())
                memory_info = process.memory_info()
                metrics.update_memory_usage(memory_info.rss)
                
                # Store the loaded model and metrics
                if model_id not in self._loaded_models:
                    self._loaded_models[model_id] = {}
                self._loaded_models[model_id][version_id] = model_instance
                
                if model_id not in self._model_metrics:
                    self._model_metrics[model_id] = {}
                self._model_metrics[model_id][version_id] = metrics
                
                # Set as active version if not already set
                if model_id not in self._active_versions:
                    self._active_versions[model_id] = version_id
                
                logger.info(f"Model {model_id} version {version_id} loaded successfully in {load_time:.2f}s")
                
                # Validate the model after loading
                await self._validate_model(model_id, version_id, model_instance)
                
                return model_instance, metrics
                
            except Exception as e:
                logger.error(f"Error loading model {model_id} version {version_id}: {str(e)}")
                logger.error(traceback.format_exc())
                raise ModelLoadError(f"Failed to load model: {str(e)}")
    
    async def unload_model(self, model_id: str, version_id: Optional[str] = None) -> bool:
        """
        Unload a specific model version or all versions if version_id is None.
        
        Args:
            model_id: The ID of the model to unload
            version_id: The specific version to unload, or None for all versions
            
        Returns:
            True if unloaded successfully, False otherwise
        """
        if model_id not in self._locks:
            self._locks[model_id] = asyncio.Lock()
        
        async with self._locks[model_id]:
            try:
                if model_id not in self._loaded_models:
                    logger.warning(f"Model {model_id} not loaded, nothing to unload")
                    return False
                
                if version_id:
                    # Unload specific version
                    if version_id not in self._loaded_models[model_id]:
                        logger.warning(f"Version {version_id} of model {model_id} not loaded, nothing to unload")
                        return False
                    
                    # Check if this is the active version
                    if model_id in self._active_versions and self._active_versions[model_id] == version_id:
                        # Find another version to set as active, or remove active version
                        other_versions = [v for v in self._loaded_models[model_id].keys() if v != version_id]
                        if other_versions:
                            self._active_versions[model_id] = other_versions[0]
                        else:
                            self._active_versions.pop(model_id, None)
                    
                    # Release resources
                    model_instance = self._loaded_models[model_id].pop(version_id)
                    if hasattr(model_instance, 'cleanup') and callable(getattr(model_instance, 'cleanup')):
                        await model_instance.cleanup()
                    
                    # Clean up metrics
                    if model_id in self._model_metrics and version_id in self._model_metrics[model_id]:
                        self._model_metrics[model_id].pop(version_id, None)
                    
                    # Remove empty dictionaries
                    if not self._loaded_models[model_id]:
                        self._loaded_models.pop(model_id, None)
                    if model_id in self._model_metrics and not self._model_metrics[model_id]:
                        self._model_metrics.pop(model_id, None)
                    
                    logger.info(f"Model {model_id} version {version_id} unloaded successfully")
                    return True
                
                else:
                    # Unload all versions
                    versions = list(self._loaded_models[model_id].keys())
                    for v_id in versions:
                        model_instance = self._loaded_models[model_id].pop(v_id, None)
                        if model_instance and hasattr(model_instance, 'cleanup') and callable(getattr(model_instance, 'cleanup')):
                            await model_instance.cleanup()
                    
                    # Clean up all metrics
                    if model_id in self._model_metrics:
                        self._model_metrics.pop(model_id, None)
                    
                    # Remove from active versions
                    self._active_versions.pop(model_id, None)
                    
                    # Remove empty dictionaries
                    self._loaded_models.pop(model_id, None)
                    
                    logger.info(f"All versions of model {model_id} unloaded successfully")
                    return True
                
            except Exception as e:
                logger.error(f"Error unloading model {model_id}: {str(e)}")
                logger.error(traceback.format_exc())
                return False
    
    async def unload_all_models(self) -> bool:
        """Unload all loaded models."""
        logger.info("Unloading all models...")
        
        success = True
        for model_id in list(self._loaded_models.keys()):
            if not await self.unload_model(model_id):
                success = False
        
        return success
    
    async def get_active_model(self, model_id: str) -> Tuple[Any, str, ModelMetrics]:
        """
        Get the currently active version of a model.
        
        Args:
            model_id: The ID of the model
            
        Returns:
            Tuple of (model instance, version_id, model metrics)
            
        Raises:
            ModelLoadError: If the model is not loaded or has no active version
        """
        if model_id not in self._active_versions:
            # Try to load the latest version
            model_instance, metrics = await self.load_model(model_id)
            version_id = self._active_versions.get(model_id)
            return model_instance, version_id, metrics
        
        version_id = self._active_versions[model_id]
        if model_id not in self._loaded_models or version_id not in self._loaded_models[model_id]:
            # The active version is not loaded, which shouldn't happen
            # Load it and update active_versions
            model_instance, metrics = await self.load_model(model_id, version_id)
            return model_instance, version_id, metrics
        
        return (
            self._loaded_models[model_id][version_id],
            version_id,
            self._model_metrics[model_id][version_id]
        )
    
    async def switch_model_version(self, model_id: str, version_id: str) -> bool:
        """
        Switch the active version of a model.
        
        Args:
            model_id: The ID of the model
            version_id: The version to switch to
            
        Returns:
            True if switched successfully, False otherwise
        """
        if model_id not in self._locks:
            self._locks[model_id] = asyncio.Lock()
        
        async with self._locks[model_id]:
            try:
                # Check if version exists in registry
                version = await self.model_registry.get_model_version(model_id, version_id)
                if not version:
                    logger.error(f"Version {version_id} not found for model {model_id}")
                    return False
                
                # Load the model if not already loaded
                if (model_id not in self._loaded_models or 
                    version_id not in self._loaded_models[model_id]):
                    await self.load_model(model_id, version_id)
                
                # Update the active version
                self._active_versions[model_id] = version_id
                logger.info(f"Switched model {model_id} to version {version_id}")
                
                return True
                
            except Exception as e:
                logger.error(f"Error switching model {model_id} to version {version_id}: {str(e)}")
                logger.error(traceback.format_exc())
                return False
    
    async def get_model_metrics(self, model_id: str, version_id: Optional[str]

import os
import time
import asyncio
import shutil
import json
import logging
from typing import Dict, List, Optional, Any, Tuple, Set, Union
from enum import Enum
from datetime import datetime
from pathlib import Path

import aiofiles
import psutil
from pydantic import BaseModel, Field, validator

from mcp_paas.models.registry import ModelRegistry
from mcp_paas.config import settings

logger = logging.getLogger(__name__)

class ModelStatus(Enum):
    """Enum representing various states of a model."""
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"
    UNLOADED = "unloaded"

class ModelVersion(BaseModel):
    """Model version information."""
    version_id: str
    created_at: datetime
    path: Path
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @validator('path')
    def validate_path(cls, v):
        return Path(v) if not isinstance(v, Path) else v

class ModelInfo(BaseModel):
    """Detailed information about a model."""
    model_id: str
    name: str
    description: Optional[str] = None
    current_version: Optional[str] = None
    versions: Dict[str, ModelVersion] = Field(default_factory=dict)
    status: ModelStatus = ModelStatus.UNLOADED
    last_used: Optional[datetime] = None
    load_time: Optional[float] = None
    health_status: Optional[Dict[str, Any]] = None
    memory_usage: Optional[int] = None  # in bytes

class ModelValidationError(Exception):
    """Exception raised for model validation errors."""
    pass

class ModelLoadError(Exception):
    """Exception raised when a model fails to load."""
    pass

class ModelNotFoundError(Exception):
    """Exception raised when a model is not found."""
    pass

class ModelLoader:
    """
    Handles loading, versioning, and management of model artifacts.
    
    Responsibilities:
    - Load model artifacts from filesystem
    - Switch between model versions
    - Memory management and cleanup of unused models
    - Model validation and health checks
    """
    
    def __init__(
        self, 
        artifacts_dir: Union[str, Path] = None,
        registry: Optional[ModelRegistry] = None,
        max_memory_usage: int = None,  # in MB
        cleanup_interval: int = 3600,  # seconds
        health_check_interval: int = 300,  # seconds
    ):
        """
        Initialize the ModelLoader.
        
        Args:
            artifacts_dir: Directory where model artifacts are stored
            registry: Model registry instance for metadata management
            max_memory_usage: Maximum memory usage in MB before cleanup is triggered
            cleanup_interval: Interval in seconds for running cleanup tasks
            health_check_interval: Interval in seconds for running health checks
        """
        self.artifacts_dir = Path(artifacts_dir or settings.MODELS.ARTIFACTS_DIR)
        self.registry = registry
        self.max_memory_usage = max_memory_usage or settings.MODELS.MAX_MEMORY_USAGE_MB
        self.cleanup_interval = cleanup_interval
        self.health_check_interval = health_check_interval
        
        # In-memory cache of loaded models and their info
        self.loaded_models: Dict[str, Any] = {}  # model_id -> model object
        self.model_info: Dict[str, ModelInfo] = {}  # model_id -> ModelInfo
        
        # Background tasks
        self._cleanup_task = None
        self._health_check_task = None
        
        # Lock for model operations
        self._model_locks: Dict[str, asyncio.Lock] = {}
        
        # Set for managing in-use models to prevent cleanup
        self._models_in_use: Set[str] = set()
    
    async def initialize(self):
        """Initialize the model loader and start background tasks."""
        logger.info("Initializing ModelLoader...")
        
        # Ensure directories exist
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        
        # Start background tasks
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        self._health_check_task = asyncio.create_task(self._periodic_health_check())
        
        # Load model metadata from registry if available
        if self.registry:
            await self._sync_with_registry()
        else:
            await self._discover_models()
        
        logger.info("ModelLoader initialized successfully")
    
    async def shutdown(self):
        """Clean up resources and stop background tasks."""
        logger.info("Shutting down ModelLoader...")
        
        # Cancel background tasks
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        # Unload all models
        await self.unload_all_models()
        
        logger.info("ModelLoader shut down successfully")
    
    async def _sync_with_registry(self):
        """Synchronize model information with the registry."""
        try:
            models = await self.registry.list_models()
            for model in models:
                model_info = ModelInfo(
                    model_id=model.id,
                    name=model.name,
                    description=model.description,
                    current_version=model.active_version,
                    status=ModelStatus.UNLOADED
                )
                
                # Get versions for this model
                versions = await self.registry.get_model_versions(model.id)
                for version in versions:
                    model_info.versions[version.version] = ModelVersion(
                        version_id=version.version,
                        created_at=version.created_at,
                        path=Path(version.path),
                        metadata=json.loads(version.metadata) if version.metadata else {}
                    )
                
                self.model_info[model.id] = model_info
                
            logger.info(f"Synchronized {len(models)} models from registry")
        except Exception as e:
            logger.error(f"Error synchronizing with registry: {e}")
            raise
    
    async def _discover_models(self):
        """Discover models from the filesystem structure."""
        try:
            if not self.artifacts_dir.exists():
                logger.warning(f"Artifacts directory {self.artifacts_dir} does not exist")
                return
            
            for model_dir in self.artifacts_dir.iterdir():
                if not model_dir.is_dir():
                    continue
                
                model_id = model_dir.name
                versions = {}
                current_version = None
                
                # Find version directories
                for version_dir in model_dir.iterdir():
                    if not version_dir.is_dir():
                        continue
                    
                    version_id = version_dir.name
                    metadata_file = version_dir / "metadata.json"
                    
                    metadata = {}
                    if metadata_file.exists():
                        async with aiofiles.open(metadata_file, 'r') as f:
                            metadata = json.loads(await f.read())
                    
                    versions[version_id] = ModelVersion(
                        version_id=version_id,
                        created_at=datetime.fromtimestamp(version_dir.stat().st_ctime),
                        path=version_dir,
                        metadata=metadata
                    )
                    
                    # Use the latest version as current
                    if current_version is None or versions[version_id].created_at > versions[current_version].created_at:
                        current_version = version_id
                
                if versions:
                    model_info = ModelInfo(
                        model_id=model_id,
                        name=model_id,  # Use model_id as name by default
                        current_version=current_version,
                        versions=versions,
                        status=ModelStatus.UNLOADED
                    )
                    self.model_info[model_id] = model_info
            
            logger.info(f"Discovered {len(self.model_info)} models from filesystem")
        except Exception as e:
            logger.error(f"Error discovering models: {e}")
            raise
    
    def _get_model_lock(self, model_id: str) -> asyncio.Lock:
        """Get or create a lock for a specific model."""
        if model_id not in self._model_locks:
            self._model_locks[model_id] = asyncio.Lock()
        return self._model_locks[model_id]
    
    async def load_model(self, model_id: str, version_id: Optional[str] = None) -> Any:
        """
        Load a model from the filesystem.
        
        Args:
            model_id: ID of the model to load
            version_id: Specific version to load, or None for default/current
            
        Returns:
            The loaded model object
            
        Raises:
            ModelNotFoundError: If the model or version is not found
            ModelLoadError: If the model fails to load
        """
        if model_id not in self.model_info:
            raise ModelNotFoundError(f"Model {model_id} not found")
        
        model_info = self.model_info[model_id]
        
        # Determine which version to load
        if version_id is None:
            version_id = model_info.current_version
            
        if version_id is None or version_id not in model_info.versions:
            raise ModelNotFoundError(f"Version {version_id} not found for model {model_id}")
        
        # Check if model is already loaded with the requested version
        if (model_id in self.loaded_models and 
            model_info.current_version == version_id and 
            model_info.status == ModelStatus.READY):
            
            # Update last used timestamp
            model_info.last_used = datetime.now()
            return self.loaded_models[model_id]
        
        # Acquire lock to prevent concurrent loads of the same model
        async with self._get_model_lock(model_id):
            try:
                # Mark model as loading
                model_info.status = ModelStatus.LOADING
                model_info.current_version = version_id
                
                # Get version details
                version = model_info.versions[version_id]
                model_path = version.path
                
                # Validate model artifacts
                await self._validate_model_artifacts(model_id, version_id)
                
                # Record start time for load time measurement
                start_time = time.time()
                
                # Actual model loading logic would depend on the model type
                # Here we'll implement a placeholder that loads different model types
                logger.info(f"Loading model {model_id} version {version_id} from {model_path}")
                
                # Check model type from metadata and load accordingly
                model_type = version.metadata.get("type", "unknown")
                model = await self._load_model_by_type(model_id, version_id, model_type)
                
                # Update model info
                model_info.load_time = time.time() - start_time
                model_info.last_used = datetime.now()
                model_info.status = ModelStatus.READY
                model_info.memory_usage = self._estimate_memory_usage(model)
                
                # Store model in cache
                self.loaded_models[model_id] = model
                
                logger.info(f"Successfully loaded model {model_id} version {version_id} in {model_info.load_time:.2f}s")
                return model
                
            except Exception as e:
                model_info.status = ModelStatus.ERROR
                model_info.health_status = {"error": str(e)}
                logger.error(f"Error loading model {model_id} version {version_id}: {e}")
                raise ModelLoadError(f"Failed to load model {model_id}: {e}")
    
    async def _load_model_by_type(self, model_id: str, version_id: str, model_type: str) -> Any:
        """
        Load a model based on its type.
        
        This method should be extended to support various model types.
        
        Args:
            model_id: ID of the model
            version_id: Version of the model
            model_type: Type of the model (e.g., "pytorch", "tensorflow", etc.)
            
        Returns:
            Loaded model object
        """
        model_info = self.model_info[model_id]
        version = model_info.versions[version_id]
        model_path = version.path
        
        # Placeholder for actual model loading logic
        # In a real implementation, different model types would be handled differently
        if model_type == "pytorch":
            # Placeholder for PyTorch model loading
            return {"model_type": "pytorch", "path": str(model_path)}
        elif model_type == "tensorflow":
            # Placeholder for TensorFlow model loading
            return {"model_type": "tensorflow", "path": str(model_path)}
        elif model_type == "onnx":
            # Placeholder for ONNX model loading
            return {"model_type": "onnx", "path": str(model_path)}
        else:
            # Generic model loading for unknown types
            return {"model_type": "unknown", "path": str(model_path)}
    
    async def unload_model(self, model_id: str):
        """
        Unload a model from memory.
        
        Args:
            model_id: ID of the model to unload
            
        Raises:
            ModelNotFoundError: If the model is not found
        """
        if model_id not in self.model_info:
            raise ModelNotFoundError(f"Model {model_id} not found")
        
        if model_id in self._models_in_use:
            logger.warning(f"Attempted to unload model {model_id} that is currently in use")
            return
        
        async with self._get_model_lock(model_id):
            if model_id in self.loaded_models:
                model_info = self.model_info[model_id]
                
                logger.info(f"Unloading model {model_id}")
                
                # Actual unloading logic would depend on the model type
                # For some frameworks, explicit cleanup may be needed
                self.loaded_models.pop(model_id)
                
                # Update model status
                model_info.status = ModelStatus.UNLOADED
                model_info.memory_usage = None
                
                # Force garbage collection to free memory
                import gc
                gc.collect()
                
                logger.info(f"Successfully unloaded model {model_id}")
    
    async def unload_all_models(self):
        """Unload all models from memory."""
        for model_id in list(self.loaded_models.keys()):
            if model_id not in self._models_in_use:
                await self.unload_model(model_id)
    
    async def switch_model_version(self, model_id: str, version_id: str) -> Any:
        """
        Switch a model to a different version.
        
        Args:
            model_id: ID of the model
            version_id: Version to switch to
            
        Returns:
            The loaded model object
            
        Raises:
            ModelNotFoundError: If the model or version is not found
            ModelLoadError: If the model fails to load
        """
        if model_id not in self.model_info:
            raise ModelNotFoundError

