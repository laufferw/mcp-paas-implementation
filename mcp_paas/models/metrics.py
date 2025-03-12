import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np


@dataclass
class ModelMetrics:
    """
    Class for tracking performance metrics of a model.
    """
    model_id: str
    version_id: str
    # Timing metrics
    inference_times: List[float] = field(default_factory=list)
    loading_time: Optional[float] = None
    last_accessed: Optional[datetime] = None
    
    # Resource usage
    memory_usage: List[float] = field(default_factory=list)
    gpu_memory_usage: List[float] = field(default_factory=list)
    
    # Request metrics
    request_count: int = 0
    success_count: int = 0
    error_count: int = 0
    
    # Error tracking
    error_types: Dict[str, int] = field(default_factory=dict)
    
    def record_inference_time(self, duration_ms: float) -> None:
        """Record a single inference time in milliseconds."""
        self.inference_times.append(duration_ms)
        self.request_count += 1
        self.last_accessed = datetime.now()
    
    def record_success(self) -> None:
        """Record a successful inference."""
        self.success_count += 1
    
    def record_error(self, error_type: str) -> None:
        """Record an error of the specified type."""
        self.error_count += 1
        self.error_types[error_type] = self.error_types.get(error_type, 0) + 1
    
    def record_memory_usage(self, memory_mb: float, gpu_memory_mb: Optional[float] = None) -> None:
        """Record memory usage in megabytes."""
        self.memory_usage.append(memory_mb)
        if gpu_memory_mb is not None:
            self.gpu_memory_usage.append(gpu_memory_mb)
    
    def set_loading_time(self, duration_ms: float) -> None:
        """Set the loading time for the model in milliseconds."""
        self.loading_time = duration_ms
    
    @property
    def avg_inference_time(self) -> Optional[float]:
        """Get the average inference time in milliseconds."""
        if not self.inference_times:
            return None
        return np.mean(self.inference_times)
    
    @property
    def median_inference_time(self) -> Optional[float]:
        """Get the median inference time in milliseconds."""
        if not self.inference_times:
            return None
        return np.median(self.inference_times)
    
    @property
    def p95_inference_time(self) -> Optional[float]:
        """Get the 95th percentile inference time in milliseconds."""
        if not self.inference_times:
            return None
        return np.percentile(self.inference_times, 95)
    
    @property
    def p99_inference_time(self) -> Optional[float]:
        """Get the 99th percentile inference time in milliseconds."""
        if not self.inference_times:
            return None
        return np.percentile(self.inference_times, 99)
    
    @property
    def error_rate(self) -> float:
        """Calculate the error rate as a percentage."""
        if self.request_count == 0:
            return 0.0
        return (self.error_count / self.request_count) * 100.0
    
    @property
    def avg_memory_usage(self) -> Optional[float]:
        """Get the average memory usage in megabytes."""
        if not self.memory_usage:
            return None
        return np.mean(self.memory_usage)
    
    @property
    def max_memory_usage(self) -> Optional[float]:
        """Get the maximum memory usage in megabytes."""
        if not self.memory_usage:
            return None
        return np.max(self.memory_usage)
    
    @property
    def summary(self) -> Dict[str, any]:
        """Get a summary of all metrics."""
        return {
            "model_id": self.model_id,
            "version_id": self.version_id,
            "request_count": self.request_count,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "error_rate": self.error_rate,
            "avg_inference_time_ms": self.avg_inference_time,
            "median_inference_time_ms": self.median_inference_time,
            "p95_inference_time_ms": self.p95_inference_time,
            "p99_inference_time_ms": self.p99_inference_time,
            "loading_time_ms": self.loading_time,
            "last_accessed": self.last_accessed,
            "avg_memory_usage_mb": self.avg_memory_usage,
            "max_memory_usage_mb": self.max_memory_usage,
            "error_types": self.error_types
        }

