
from typing import Dict, Optional, Tuple, Set
import time
import asyncio
from datetime import datetime, timedelta
import logging
from pydantic import BaseModel, Field
import hashlib

from mcp_paas.config import settings

logger = logging.getLogger(__name__)

class RateLimitExceeded(Exception):
    """Exception raised when a rate limit is exceeded"""
    def __init__(self, tenant_id: str, limit: int, window_seconds: int, retry_after: int):
        self.tenant_id = tenant_id
        self.limit = limit
        self.window_seconds = window_seconds
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded for tenant {tenant_id}: {limit} requests per {window_seconds}s. Retry after {retry_after}s"
        )

class RateLimitConfig(BaseModel):
    """Configuration for rate limiting"""
    requests_per_window: int = 100
    window_seconds: int = 60
    burst_multiplier: float = 1.5  # Allow temporary bursts
    
    @property
    def burst_limit(self) -> int:
        """Maximum tokens that can be accumulated"""
        return int(self.requests_per_window * self.burst_multiplier)

class RateLimitStatus(BaseModel):
    """Current rate limit status for a tenant/endpoint"""
    tokens: float
    last_refill: float  # Unix timestamp
    config: RateLimitConfig

class RateLimiterStats(BaseModel):
    """Statistics for the rate limiter"""
    total_limited: int = 0
    total_allowed: int = 0
    limited_tenants: Set[str] = Field(default_factory=set)
    
    def record_allowed(self):
        """Record an allowed request"""
        self.total_allowed += 1
    
    def record_limited(self, tenant_id: str):
        """Record a limited request"""
        self.total_limited += 1
        self.limited_tenants.add(tenant_id)
        
    def get_stats(self) -> dict:
        """Get current statistics as a dictionary"""
        return {
            "allowed_requests": self.total_allowed,
            "limited_requests": self.total_limited, 
            "limited_tenants_count": len(self.limited_tenants),
            "limited_tenants": list(self.limited_tenants)
        }

class RateLimiter:
    """
    Async token bucket rate limiter with per-tenant limits.
    Provides configurable limits and window-based rate limiting.
    """
    
    def __init__(
        self,
        default_config: Optional[RateLimitConfig] = None,
        cleanup_interval: int = 3600  # Clean up old entries every hour
    ):
        self.tenant_configs: Dict[str, RateLimitConfig] = {}
        self.tenant_limits: Dict[str, Dict[str, RateLimitStatus]] = {}
        self.default_config = default_config or RateLimitConfig()
        self.cleanup_interval = cleanup_interval
        self.stats = RateLimiterStats()
        self._lock = asyncio.Lock()
        self._cleanup_task = None
        logger.info(f"Rate limiter initialized with default limit of {self.default_config.requests_per_window} requests per {self.default_config.window_seconds}s")
    
    async def initialize(self):
        """Initialize the rate limiter and start the background cleanup task"""
        try:
            if self._cleanup_task is None:
                self._cleanup_task = asyncio.create_task(self._cleanup_loop())
                logger.info(f"Rate limiter cleanup task started with interval {self.cleanup_interval}s")
            else:
                logger.warning("Rate limiter cleanup task already running, skipping initialization")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize rate limiter: {str(e)}", exc_info=True)
            return False
    
    async def shutdown(self):
        """Shutdown the rate limiter and stop the background cleanup task"""
        try:
            if self._cleanup_task:
                logger.info("Stopping rate limiter cleanup task...")
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    logger.debug("Rate limiter cleanup task cancelled successfully")
                except Exception as e:
                    logger.warning(f"Error while waiting for cleanup task to stop: {str(e)}")
                finally:
                    self._cleanup_task = None
                    logger.info("Rate limiter cleanup task stopped")
            else:
                logger.debug("No cleanup task running, nothing to shut down")
            return True
        except Exception as e:
            logger.error(f"Error during rate limiter shutdown: {str(e)}", exc_info=True)
            return False
    
    async def _cleanup_loop(self):
        """Periodically clean up old rate limit entries"""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_old_entries()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in rate limiter cleanup: {str(e)}", exc_info=True)
    
    async def _cleanup_old_entries(self):
        """Remove rate limit entries that haven't been used recently"""
        now = time.time()
        stale_threshold = now - (24 * 3600)  # 24 hours
        
        async with self._lock:
            for tenant_id in list(self.tenant_limits.keys()):
                for key in list(self.tenant_limits[tenant_id].keys()):
                    if self.tenant_limits[tenant_id][key].last_refill < stale_threshold:
                        logger.debug(f"Removing stale rate limit entry for tenant {tenant_id}, key {key}")
                        del self.tenant_limits[tenant_id][key]
                
                # Remove tenant if no more entries
                if not self.tenant_limits[tenant_id]:
                    logger.info(f"Removing tenant {tenant_id} from rate limiter (no active limits)")
                    del self.tenant_limits[tenant_id]
    
    def set_tenant_config(self, tenant_id: str, config: RateLimitConfig):
        """Set a custom rate limit configuration for a tenant"""
        self.tenant_configs[tenant_id] = config
    
    def get_tenant_config(self, tenant_id: str) -> RateLimitConfig:
        """Get the rate limit configuration for a tenant"""
        return self.tenant_configs.get(tenant_id, self.default_config)
    
    def _get_key(self, endpoint: str, ip_address: Optional[str] = None) -> str:
        """Generate a unique key for the endpoint and IP"""
        if ip_address:
            return f"{endpoint}:{ip_address}"
        return endpoint
    
    async def get_rate_limit_headers(self, tenant_id: str, endpoint: str, ip_address: Optional[str] = None) -> dict:
        """
        Get rate limit headers for a response
        
        Returns a dictionary of headers with rate limit information
        """
        key = self._get_key(endpoint, ip_address)
        
        async with self._lock:
            if tenant_id in self.tenant_limits and key in self.tenant_limits[tenant_id]:
                status = self.tenant_limits[tenant_id][key]
                config = status.config
                
                # Calculate tokens available and reset time
                now = time.time()
                time_passed = now - status.last_refill
                tokens = min(
                    status.tokens + time_passed * (config.requests_per_window / config.window_seconds),
                    config.burst_limit
                )
                
                # Calculate when the bucket will be full again
                seconds_to_full = max(0, (config.burst_limit - tokens) / 
                                    (config.requests_per_window / config.window_seconds))
                reset_time = int(now + seconds_to_full)
                
                return {
                    "X-RateLimit-Limit": str(config.requests_per_window),
                    "X-RateLimit-Remaining": str(int(tokens)),
                    "X-RateLimit-Reset": str(reset_time)
                }
            
            # No rate limit info available
            config = self.get_tenant_config(tenant_id)
            return {
                "X-RateLimit-Limit": str(config.requests_per_window),
                "X-RateLimit-Remaining": str(config.requests_per_window),
                "X-RateLimit-Reset": str(int(time.time() + config.window_seconds))
            }
    
    async def check_rate_limit(
        self, 
        tenant_id: str, 
        endpoint: str, 
        ip_address: Optional[str] = None, 
        cost: float = 1.0
    ) -> Tuple[bool, int]:
        """
        Check if a request should be rate limited
        
        Args:
            tenant_id: The tenant making the request
            endpoint: The endpoint being accessed
            ip_address: Optional IP address for additional granularity
            cost: Token cost for this operation (higher for expensive operations)
            
        Returns:
            Tuple of (is_allowed, retry_after_seconds)
        """
        key = self._get_key(endpoint, ip_address)
        
        async with self._lock:
            # Initialize tenant dict if needed
            if tenant_id not in self.tenant_limits:
                self.tenant_limits[tenant_id] = {}
            
            # Get or create rate limit status for this endpoint
            config = self.get_tenant_config(tenant_id)
            if key not in self.tenant_limits[tenant_id]:
                # Initialize with full token bucket
                self.tenant_limits[tenant_id][key] = RateLimitStatus(
                    tokens=config.burst_limit,
                    last_refill=time.time(),
                    config=config
                )
                
            # Get current status
            status = self.tenant_limits[tenant_id][key]
            
            # Calculate token refill based on time passed
            now = time.time()
            time_passed = now - status.last_refill
            refill_amount = time_passed * (status.config.requests_per_window / status.config.window_seconds)
            
            # Update tokens (capped at burst limit)
            new_tokens = min(status.tokens + refill_amount, status.config.burst_limit)
            
            # Check if we have enough tokens for this request
            if new_tokens < cost:
                # Not enough tokens - calculate retry after time
                tokens_needed = cost - new_tokens
                retry_after = int(tokens_needed / (status.config.requests_per_window / status.config.window_seconds))
                # Record the rate limit event
                self.stats.record_limited(tenant_id)
                return False, max(1, retry_after)  # Ensure at least 1 second retry
            
            # We have enough tokens, update the bucket
            status.tokens = new_tokens - cost
            status.last_refill = now
            
            # Record the allowed request
            self.stats.record_allowed()
            return True, 0
