#!/usr/bin/env python3
"""
Rate limiting utility for MCP PaaS.

This module provides rate limiting capabilities with multiple strategies,
per-tenant resource tracking, and automatic cleanup of expired resources.
"""

import asyncio
import enum
import logging
import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import wraps
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import aioredis
import prometheus_client as prom
from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)

# Prometheus metrics
RATE_LIMIT_REQUESTS = Counter(
    "mcp_rate_limit_requests_total",
    "Total number of rate limited requests",
    ["tenant_id", "resource_type", "action", "result"]
)

RATE_LIMIT_CURRENT = Gauge(
    "mcp_rate_limit_current",
    "Current rate limit usage",
    ["tenant_id", "resource_type", "limit_type"]
)

RATE_LIMIT_LATENCY = Histogram(
    "mcp_rate_limit_latency_seconds",
    "Rate limiting operation latency",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
)


class RateLimitExceededError(Exception):
    """Raised when a rate limit is exceeded."""
    
    def __init__(self, tenant_id: str, resource_type: str, 
                 current: int, limit: int, retry_after: float):
        self.tenant_id = tenant_id
        self.resource_type = resource_type
        self.current = current
        self.limit = limit
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded for tenant '{tenant_id}' on resource '{resource_type}': "
            f"{current}/{limit}. Retry after {retry_after:.2f} seconds."
        )


class ResourceType(enum.Enum):
    """Types of resources that can be rate limited."""
    API_CALL = "api_call"
    MODEL_INFERENCE = "model_inference"
    CONTEXT_CREATION = "context_creation"
    DATABASE_WRITE = "database_write"
    AUTHENTICATION = "authentication"


class LimitType(enum.Enum):
    """Types of rate limiting strategies."""
    SLIDING_WINDOW = "sliding_window"
    TOKEN_BUCKET = "token_bucket"


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit."""
    limit: int  # Maximum number of requests/tokens
    window: int = 60  # Time window in seconds (for sliding window)
    refill_rate: float = 1.0  # Tokens per second (for token bucket)
    burst: int = None  # Maximum burst size (for token bucket)
    
    def __post_init__(self):
        # Set default burst to limit if not specified
        if self.burst is None:
            self.burst = self.limit


@dataclass
class ResourceUsage:
    """Tracks usage of a specific resource by a tenant."""
    current: int = 0
    last_updated: float = 0.0
    requests: List[float] = None
    
    def __post_init__(self):
        if self.requests is None:
            self.requests = []
        self.last_updated = time.time()


class RateLimitStrategy(ABC):
    """Abstract base class for rate limiting strategies."""
    
    @abstractmethod
    def check_limit(self, tenant_id: str, resource_type: str, 
                    usage: ResourceUsage, config: RateLimitConfig) -> Tuple[bool, float]:
        """
        Check if the rate limit has been exceeded.
        
        Args:
            tenant_id: The ID of the tenant
            resource_type: The type of resource being limited
            usage: Current usage statistics
            config: Rate limit configuration
            
        Returns:
            Tuple containing (is_allowed, retry_after_seconds)
        """
        pass
    
    @abstractmethod
    def update_usage(self, usage: ResourceUsage, config: RateLimitConfig) -> ResourceUsage:
        """
        Update usage statistics after a request.
        
        Args:
            usage: Current usage statistics
            config: Rate limit configuration
            
        Returns:
            Updated usage statistics
        """
        pass
    
    @abstractmethod
    def cleanup_expired(self, usage: ResourceUsage, config: RateLimitConfig) -> ResourceUsage:
        """
        Clean up expired usage data.
        
        Args:
            usage: Current usage statistics
            config: Rate limit configuration
            
        Returns:
            Updated usage statistics with expired data removed
        """
        pass


class SlidingWindowStrategy(RateLimitStrategy):
    """Sliding window rate limiting strategy."""
    
    def check_limit(self, tenant_id: str, resource_type: str, 
                    usage: ResourceUsage, config: RateLimitConfig) -> Tuple[bool, float]:
        """Check if the sliding window rate limit has been exceeded."""
        now = time.time()
        window_start = now - config.window
        
        # Remove expired timestamps
        usage = self.cleanup_expired(usage, config)
        
        # Count requests within the current window
        count = len(usage.requests)
        
        # If we've exceeded the limit, calculate retry-after time
        if count >= config.limit:
            if usage.requests:
                # The oldest request will expire after window seconds
                retry_after = usage.requests[0] + config.window - now
            else:
                retry_after = config.window
                
            return False, max(0, retry_after)
        
        return True, 0
    
    def update_usage(self, usage: ResourceUsage, config: RateLimitConfig) -> ResourceUsage:
        """Update sliding window usage statistics after a request."""
        now = time.time()
        usage.requests.append(now)
        usage.current = len(usage.requests)
        usage.last_updated = now
        return usage
    
    def cleanup_expired(self, usage: ResourceUsage, config: RateLimitConfig) -> ResourceUsage:
        """Clean up expired usage data for sliding window strategy."""
        now = time.time()
        window_start = now - config.window
        
        # Keep only timestamps within the window
        usage.requests = [ts for ts in usage.requests if ts > window_start]
        usage.current = len(usage.requests)
        return usage


class TokenBucketStrategy(RateLimitStrategy):
    """Token bucket rate limiting strategy."""
    
    def check_limit(self, tenant_id: str, resource_type: str, 
                    usage: ResourceUsage, config: RateLimitConfig) -> Tuple[bool, float]:
        """Check if the token bucket rate limit has been exceeded."""
        now = time.time()
        elapsed = now - usage.last_updated
        
        # Calculate how many tokens should be added since last update
        new_tokens = elapsed * config.refill_rate
        
        # Update current token count, but don't exceed burst limit
        current_tokens = min(config.burst, usage.current + new_tokens)
        
        # If we don't have at least 1 token, calculate retry-after time
        if current_tokens < 1:
            # Calculate time until we have one token
            retry_after = (1 - current_tokens) / config.refill_rate
            return False, retry_after
        
        return True, 0
    
    def update_usage(self, usage: ResourceUsage, config: RateLimitConfig) -> ResourceUsage:
        """Update token bucket usage statistics after a request."""
        now = time.time()
        elapsed = now - usage.last_updated
        
        # Calculate how many tokens should be added since last update
        new_tokens = elapsed * config.refill_rate
        
        # Update current token count, then consume one token
        usage.current = min(config.burst, usage.current + new_tokens) - 1
        usage.last_updated = now
        return usage
    
    def cleanup_expired(self, usage: ResourceUsage, config: RateLimitConfig) -> ResourceUsage:
        """
        Clean up expired usage data for token bucket strategy.
        
        For token bucket, we just need to update the current token count
        based on the time elapsed since the last update.
        """
        now = time.time()
        elapsed = now - usage.last_updated
        
        # Calculate how many tokens should be added since last update
        new_tokens = elapsed * config.refill_rate
        
        # Update current token count, but don't exceed burst limit
        usage.current = min(config.burst, usage.current + new_tokens)
        usage.last_updated = now
        return usage


class RateLimiter:
    """
    Rate limiter with multiple strategies and per-tenant resource tracking.
    
    Features:
    - Multiple rate limiting strategies (sliding window, token bucket)
    - Per-tenant resource tracking and quotas
    - Automatic cleanup of expired resources
    - Thread-safe implementation with asyncio support
    - Redis support for distributed rate limiting
    """
    
    def __init__(self, 
                 default_config: Dict[ResourceType, RateLimitConfig] = None,
                 tenant_configs: Dict[str, Dict[ResourceType, RateLimitConfig]] = None,
                 strategy_type: LimitType = LimitType.SLIDING_WINDOW,
                 cleanup_interval: int = 300,
                 redis_url: Optional[str] = None):
        """
        Initialize the rate limiter.
        
        Args:
            default_config: Default rate limit configuration for all tenants
            tenant_configs: Per-tenant rate limit configurations
            strategy_type: The rate limiting strategy to use
            cleanup_interval: How often to clean up expired resources (seconds)
            redis_url: Redis URL for distributed rate limiting
        """
        self.default_config = default_config or {
            ResourceType.API_CALL: RateLimitConfig(limit=100, window=60),
            ResourceType.MODEL_INFERENCE: RateLimitConfig(limit=10, window=60),
            ResourceType.CONTEXT_CREATION: RateLimitConfig(limit=5, window=60),
            ResourceType.DATABASE_WRITE: RateLimitConfig(limit=50, window=60),
            ResourceType.AUTHENTICATION: RateLimitConfig(limit=20, window=60),
        }
        
        self.tenant_configs = tenant_configs or {}
        
        # Set up the appropriate strategy
        if strategy_type == LimitType.SLIDING_WINDOW:
            self.strategy = SlidingWindowStrategy()
        elif strategy_type == LimitType.TOKEN_BUCKET:
            self.strategy = TokenBucketStrategy()
        else:
            raise ValueError(f"Unknown rate limiting strategy: {strategy_type}")
        
        self.cleanup_interval = cleanup_interval
        self.redis_url = redis_url
        self.redis = None
        
        # Local tracking of resource usage by tenant and resource type
        self._usage: Dict[str, Dict[str, ResourceUsage]] = {}
        self._lock = Lock()
        
        # Set up async cleanup task
        self._cleanup_task = None
        self._stopping = False
        
        logger.info(f"Initialized rate limiter with {strategy_type.value} strategy")
    
    async def initialize(self):
        """Initialize the rate limiter, setting up Redis if needed."""
        if self.redis_url:
            logger.info(f"Connecting to Redis at {self.redis_url}")
            self.redis = await aioredis.from_url(self.redis_url)
        
        # Start the cleanup task
        if not self._cleanup_task:
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            logger.info(f"Started cleanup task with interval {self.cleanup_interval}s")
    
    async def close(self):
        """Clean up resources when shutting down."""
        self._stopping = True
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        
        if self.redis:
            await self.redis.close()
            self.redis = None
        
        logger.info("Rate limiter shut down")
    
    def get_config(self, tenant_id: str, resource_type: ResourceType) -> RateLimitConfig:
        """Get the rate limit configuration for a tenant and resource type."""
        # Try to get tenant-specific config
        tenant_config = self.tenant_configs.get(tenant_id, {})
        return tenant_config.get(resource_type, self.default_config[resource_type])
    
    async def check_rate_limit(self, 
                              tenant_id: str, 
                              resource_type: ResourceType) -> bool:
        """
        Check if a request is allowed under the rate limit.
        
        Args:
            tenant_id: The ID of the tenant
            resource_type: The type of resource being limited
            
        Returns:
            True if the request is allowed, False otherwise
            
        Raises:
            RateLimitExceededError: If the rate limit is exceeded
        """
        start_time = time.time()
        
        try:
            # Get the appropriate configuration
            config = self.get_config(tenant_id, resource_type)
            
            # Check if using Redis for distributed rate limiting
            if self.redis:
                allowed, retry_after = await self._check_redis_rate_limit(
                    tenant_id, resource_type, config)
            else:
                allowed, retry_after = self._check_local_rate_limit(
                    tenant_id, resource_type, config)
            
            # Update metrics
            result = "allowed" if allowed else "blocked"
            RATE_LIMIT_REQUESTS.labels(
                tenant_id=tenant_id,
                resource_type=resource_type.value,
                action="check",
                result=result
            ).inc()
            
            if not allowed:
                raise RateLimitExceededError(
                    tenant_id=tenant_id,
                    resource_type=resource_type.value,
                    current=self._get_current_usage(tenant_id, resource_type),
                    limit=config.limit,
                    retry_after=retry_after
                )
            
            return True
        
        finally:
            # Record the latency of the operation
            RATE_LIMIT_LATENCY.labels(operation="check_rate_limit").observe(
                time.time() - start_time
            )
    
    def _get_current_usage(self, tenant_id: str, resource_type: ResourceType) -> int:
        """Get the current usage count for a tenant and resource type."""
        with self._lock:
            tenant_usage = self._usage.get(tenant_id, {})
            resource_usage = tenant_usage.get(resource_type.value, ResourceUsage())
            
            if isinstance(self.strategy, TokenBucketStrategy):
                # For token bucket, return the inverse of tokens available
                config = self.get_config(tenant_id, resource_type)
                return max(0, config.burst - int(resource_usage.current))
            else:
                # For sliding window, return the number of requests in the current window
                config = self.get_config(tenant_id, resource_type)
                # Clean up expired requests first
                resource_usage = self.strategy.cleanup_expired(resource_usage, config)
                return len(resource_usage.requests)
    
    def _check_local_rate_limit(self, tenant_id: str, resource_type: ResourceType, 
                              config: RateLimitConfig) -> Tuple[bool, float]:
        """
        Check if a request is allowed under the local rate limit.
        
        Args:
            tenant_id: The ID of the tenant
            resource_type: The type of resource being limited
            config: Rate limit configuration
            
        Returns:
            Tuple containing (is_allowed, retry_after_seconds)
        """
        with self._lock:
            # Get or create usage tracking for this tenant and resource
            if tenant_id not in self._usage:
                self._usage[tenant_id] = {}
            
            if resource_type.value not in self._usage[tenant_id]:
                self._usage[tenant_id][resource_type.value] = ResourceUsage()
            
            usage = self._usage[tenant_id][resource_type.value]
            
            # Check if we're allowed to proceed
            allowed, retry_after = self.strategy.check_limit(
                tenant_id, resource_type.value, usage, config
            )
            
            if allowed:
                # Update usage statistics
                self._usage[tenant_id][resource_type.value] = self.strategy.update_usage(
                    usage, config
                )
                
                # Update metrics
                current = self._get_current_usage(tenant_id, resource_type)
                RATE_LIMIT_CURRENT.labels(
                    tenant_id=tenant_id,
                    resource_type=resource_type.value,
                    limit_type=config.__class__.__name__
                ).set(current)
            
            return allowed, retry_after
    
    async def _check_redis_rate_limit(self, tenant_id: str, resource_type: ResourceType,
                                    config: RateLimitConfig) -> Tuple[bool, float]:
        """
        Check if a request is allowed under the distributed rate limit using Redis.
        
        Args:
            tenant_id: The ID of the tenant
            resource_type: The type of resource being limited
            config: Rate limit configuration
            
        Returns:
            Tuple containing (is_allowed, retry_after_seconds)
        """
        if not self.redis:
            logger.warning("Redis not configured, falling back to local rate limiting")
            return self._check_local_rate_limit(tenant_id, resource_type, config)
        
        resource_key = f"rate_limit:{tenant_id}:{resource_type.value}"
        now = time.time()
        
        try:
            if isinstance(self.strategy, SlidingWindowStrategy):
                # For sliding window, we store timestamps of requests in a sorted set
                # with the timestamp as score
                
                # Clean up old entries
                window_start = now - config.window
                await self.redis.zremrangebyscore(resource_key, 0, window_start)
                
                # Count existing requests in the window
                count = await self.redis.zcard(resource_key)
                
                # Check if we're at the limit
                if count >= config.limit:
                    # Get the oldest timestamp to calculate retry-after
                    oldest = await self.redis.zrange(resource_key, 0, 0, withscores=True)
                    if oldest:
                        _, oldest_ts = oldest[0]
                        retry_after = oldest_ts + config.window - now
                    else:
                        retry_after = config.window
                    
                    return False, max(0, retry_after)
                
                # We're under the limit, add new request timestamp
                await self.redis.zadd(resource_key, {str(now): now})
                
                # Set expiry on the key to auto-cleanup
                await self.redis.expire(resource_key, config.window * 2)
                
                # Update metrics
                RATE_LIMIT_CURRENT.labels(
                    tenant_id=tenant_id,
                    resource_type=resource_type.value,
                    limit_type="redis_sliding_window"
                ).set(count + 1)
                
                return True, 0
                
            elif isinstance(self.strategy, TokenBucketStrategy):
                # For token bucket, we store:
                # - The last updated timestamp
                # - The current number of tokens
                
                # Try to get the current state
                last_updated, tokens = await self._get_redis_token_bucket(resource_key)
                
                if last_updated is None:
                    # Key doesn't exist, initialize it
                    last_updated = now
                    tokens = config.burst
                else:
                    # Calculate token refill
                    elapsed = now - last_updated
                    new_tokens = elapsed * config.refill_rate
                    tokens = min(config.burst, tokens + new_tokens)
                
                # Check if we have enough tokens
                if tokens < 1:
                    # Calculate time until we have one token
                    retry_after = (1 - tokens) / config.refill_rate
                    return False, retry_after
                
                # Consume one token
                tokens -= 1
                
                # Update the bucket
                await self._set_redis_token_bucket(resource_key, now, tokens)
                
                # Set expiry based on how long until bucket is full again
                ttl = int((config.burst - tokens) / config.refill_rate) + config.window
                await self.redis.expire(resource_key, ttl)
                
                # Update metrics
                RATE_LIMIT_CURRENT.labels(
                    tenant_id=tenant_id,
                    resource_type=resource_type.value,
                    limit_type="redis_token_bucket"
                ).set(config.burst - tokens)
                
                return True, 0
            
            else:
                logger.error(f"Unsupported strategy for Redis: {self.strategy.__class__.__name__}")
                return self._check_local_rate_limit(tenant_id, resource_type, config)
        
        except Exception as e:
            logger.error(f"Error in Redis rate limiting: {str(e)}")
            # Fall back to local rate limiting on Redis errors
            return self._check_local_rate_limit(tenant_id, resource_type, config)
    
    async def _get_redis_token_bucket(self, key: str) -> Tuple[Optional[float], float]:
        """
        Get the current state of a token bucket from Redis.
        
        Args:
            key: Redis key for the token bucket
            
        Returns:
            Tuple of (last_updated_timestamp, current_tokens)
        """
        # Get both values in a single call
        data = await self.redis.hmget(key, "last_updated", "tokens")
        
        if not data[0] or not data[1]:
            return None, 0
        
        return float(data[0]), float(data[1])
    
    async def _set_redis_token_bucket(self, key: str, timestamp: float, tokens: float) -> None:
        """
        Update the state of a token bucket in Redis.
        
        Args:
            key: Redis key for the token bucket
            timestamp: Current timestamp
            tokens: Current token count
        """
        await self.redis.hmset(key, {
            "last_updated": str(timestamp),
            "tokens": str(tokens)
        })
    
    async def _periodic_cleanup(self) -> None:
        """
        Periodically clean up expired rate limit data.
        
        This runs in the background to prevent memory leaks from
        accumulated usage data that is no longer needed.
        """
        while not self._stopping:
            try:
                start_time = time.time()
                logger.debug(f"Starting rate limit data cleanup")
                
                # Clean up local usage data
                with self._lock:
                    for tenant_id in list(self._usage.keys()):
                        for resource_type in list(self._usage[tenant_id].keys()):
                            try:
                                # Convert string resource type back to enum if needed
                                rt = resource_type
                                if isinstance(resource_type, str):
                                    rt = ResourceType(resource_type)
                                
                                # Get config and clean up
                                config = self.get_config(tenant_id, rt)
                                usage = self._usage[tenant_id][resource_type]
                                
                                # Clean up this resource
                                self._usage[tenant_id][resource_type] = \
                                    self.strategy.cleanup_expired(usage, config)
                                
                                # If empty and old, remove it entirely
                                if (isinstance(self.strategy, SlidingWindowStrategy) and 
                                    not self._usage[tenant_id][resource_type].requests and
                                    time.time() - self._usage[tenant_id][resource_type].last_updated > config.window * 2):
                                    del self._usage[tenant_id][resource_type]
                                
                            except Exception as e:
                                logger.error(f"Error cleaning up {tenant_id}/{resource_type}: {str(e)}")
                        
                        # If tenant has no resources, remove it
                        if not self._usage[tenant_id]:
                            del self._usage[tenant_id]
                
                # Don't need to clean Redis keys since we set TTL on them
                
                logger.debug(f"Completed rate limit cleanup in {time.time() - start_time:.2f} seconds")
                
                # Wait for next cleanup interval
                await asyncio.sleep(self.cleanup_interval)
            
            except asyncio.CancelledError:
                logger.info("Rate limit cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in rate limit cleanup: {str(e)}")
                # Wait a bit before retrying to avoid tight loop on errors
                await asyncio.sleep(10)
    
    # Decorator for rate limiting functions
    def limit(self, resource_type: ResourceType):
        """
        Decorator to apply rate limiting to a function.
        
        The decorated function must have a 'tenant_id' parameter.
        
        Args:
            resource_type: The type of resource to rate limit
            
        Returns:
            Decorated function with rate limiting applied
        """
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Try to get tenant_id from kwargs
                tenant_id = kwargs.get('tenant_id')
                
                # If not in kwargs, check if it's in args by looking at function signature
                if tenant_id is None:
                    import inspect
                    sig = inspect.signature(func)
                    params = list(sig.parameters.keys())
                    
                    # Find tenant_id position in params
                    try:
                        tenant_pos = params.index('tenant_id')
                        if len(args) > tenant_pos:
                            tenant_id = args[tenant_pos]
                    except ValueError:
                        # tenant_id not in function signature
                        raise ValueError(
                            "Rate limited function must have a 'tenant_id' parameter"
                        )
                
                if tenant_id is None:
                    raise ValueError("tenant_id must be provided to rate limited function")
                
                # Check rate limit
                await self.check_rate_limit(tenant_id, resource_type)
                
                # If we get here, rate limit check passed
                return await func(*args, **kwargs)
            
            return wrapper
        
        return decorator
    
    # Sync version of the decorator
    def limit_sync(self, resource_type: ResourceType):
        """
        Sync version of the rate limiting decorator.
        
        The decorated function must have a 'tenant_id' parameter.
        
        Args:
            resource_type: The type of resource to rate limit
            
        Returns:
            Decorated function with rate limiting applied
        """
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                # Try to get tenant_id from kwargs
                tenant_id = kwargs.get('tenant_id')
                
                # If not in kwargs, check if it's in args by looking at function signature
                if tenant_id is None:
                    import inspect
                    sig = inspect.signature(func)
                    params = list(sig.parameters.keys())
                    
                    # Find tenant_id position in params
                    try:
                        tenant_pos = params.index('tenant_id')
                        if len(args) > tenant_pos:
                            tenant_id = args[tenant_pos]
                    except ValueError:
                        # tenant_id not in function signature
                        raise ValueError(
                            "Rate limited function must have a 'tenant_id' parameter"
                        )
                
                if tenant_id is None:
                    raise ValueError("tenant_id must be provided to rate limited function")
                
                # For sync functions, we need to run the coroutine in the event loop
                loop = asyncio.get_event_loop()
                loop.run_until_complete(self.check_rate_limit(tenant_id, resource_type))
                
                # If we get here, rate limit check passed
                return func(*args, **kwargs)
            
            return wrapper
        
        return decorator
