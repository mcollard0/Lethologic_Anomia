"""
Redis/Valkey Manager for the Migration Service

Handles process management, distributed locking, and FIFO queues using Redis.
Supports both Redis and Valkey (Redis-compatible) servers.
"""

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

import redis.asyncio as redis
from redis.asyncio.lock import Lock
from redis.exceptions import ConnectionError, TimeoutError

from .logging import get_logger

logger = get_logger(__name__)


class RedisManager:
    """
    Redis/Valkey connection and process management
    
    Provides:
    - Process registration and heartbeat
    - FIFO queues with BLPOP
    - Distributed locking
    - Process cleanup
    """
    
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        """
        Initialize Redis manager
        
        Args:
            redis_url: Redis connection URL
        """
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self.process_id = str(uuid.uuid4())
        self.process_type = "migration_service"
        
        # Process management keys
        self.processes_key = "migration:processes"
        self.heartbeat_key = "migration:heartbeats"
        self.queues_key = "migration:queues"
        self.locks_key = "migration:locks"
        
        # Heartbeat settings
        self.heartbeat_interval = 300  # 5 minutes
        self.cleanup_interval = 300    # 5 minutes
        self.process_timeout = 600     # 10 minutes
        
        # Background tasks
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
    
    async def initialize(self) -> None:
        """Initialize Redis connection and start background tasks"""
        try:
            # Parse Redis URL and create connection
            self.redis_client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_keepalive=True,
                socket_keepalive_options={},
                health_check_interval=30
            )
            
            # Test connection
            await self.redis_client.ping()
            logger.info(f"Connected to Redis at {self.redis_url}")
            
            # Register this process
            await self.register_process()
            
            # Start background tasks
            self._heartbeat_task = asyncio.create_task(self._heartbeat_worker())
            self._cleanup_task = asyncio.create_task(self._cleanup_worker())
            
            logger.info(f"Redis manager initialized with process ID: {self.process_id}")
            
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize Redis manager: {e}")
            raise
    
    async def shutdown(self) -> None:
        """Shutdown Redis connection and stop background tasks"""
        logger.info("Shutting down Redis manager...")
        
        # Signal shutdown
        self._shutdown_event.set()
        
        # Cancel background tasks
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Unregister process
        try:
            await self.unregister_process()
        except Exception as e:
            logger.warning(f"Failed to unregister process: {e}")
        
        # Close Redis connection
        if self.redis_client:
            await self.redis_client.close()
        
        logger.info("Redis manager shutdown complete")
    
    async def register_process(
        self,
        process_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Register this process in Redis
        
        Args:
            process_type: Type of process (e.g., 'dicom_scp', 'web_server')
            metadata: Additional process metadata
        """
        if not self.redis_client:
            raise RuntimeError("Redis not initialized")
        
        if process_type:
            self.process_type = process_type
        
        process_info = {
            'process_id': self.process_id,
            'type': self.process_type,
            'pid': os.getpid(),
            'started_at': datetime.now().isoformat(),
            'last_heartbeat': datetime.now().isoformat(),
            'metadata': metadata or {}
        }
        
        # Store process info
        await self.redis_client.hset(
            self.processes_key,
            self.process_id,
            json.dumps(process_info)
        )
        
        # Update heartbeat
        await self.update_heartbeat()
        
        logger.info(f"Registered process {self.process_id} as {self.process_type}")
    
    async def unregister_process(self) -> None:
        """Unregister this process from Redis"""
        if not self.redis_client:
            return
        
        # Remove from processes hash
        await self.redis_client.hdel(self.processes_key, self.process_id)
        
        # Remove heartbeat
        await self.redis_client.hdel(self.heartbeat_key, self.process_id)
        
        logger.info(f"Unregistered process {self.process_id}")
    
    async def update_heartbeat(self) -> None:
        """Update process heartbeat timestamp"""
        if not self.redis_client:
            return
        
        timestamp = datetime.now().isoformat()
        
        # Update heartbeat timestamp
        await self.redis_client.hset(
            self.heartbeat_key,
            self.process_id,
            timestamp
        )
        
        # Also update in process info
        process_info = await self.get_process_info(self.process_id)
        if process_info:
            process_info['last_heartbeat'] = timestamp
            await self.redis_client.hset(
                self.processes_key,
                self.process_id,
                json.dumps(process_info)
            )
    
    async def get_process_info(self, process_id: str) -> Optional[Dict[str, Any]]:
        """
        Get process information
        
        Args:
            process_id: Process ID to lookup
            
        Returns:
            Process information dictionary or None
        """
        if not self.redis_client:
            return None
        
        process_data = await self.redis_client.hget(self.processes_key, process_id)
        if process_data:
            return json.loads(process_data)
        return None
    
    async def list_processes(self) -> Dict[str, Dict[str, Any]]:
        """
        List all registered processes
        
        Returns:
            Dictionary mapping process IDs to process info
        """
        if not self.redis_client:
            return {}
        
        processes = await self.redis_client.hgetall(self.processes_key)
        return {pid: json.loads(info) for pid, info in processes.items()}
    
    async def cleanup_stale_processes(self) -> int:
        """
        Clean up stale/dead processes
        
        Returns:
            Number of processes cleaned up
        """
        if not self.redis_client:
            return 0
        
        cleaned_count = 0
        cutoff_time = datetime.now() - timedelta(seconds=self.process_timeout)
        
        # Get all heartbeats
        heartbeats = await self.redis_client.hgetall(self.heartbeat_key)
        
        for process_id, heartbeat_str in heartbeats.items():
            try:
                heartbeat_time = datetime.fromisoformat(heartbeat_str)
                
                if heartbeat_time < cutoff_time:
                    # Process is stale, remove it
                    await self.redis_client.hdel(self.processes_key, process_id)
                    await self.redis_client.hdel(self.heartbeat_key, process_id)
                    cleaned_count += 1
                    logger.info(f"Cleaned up stale process: {process_id}")
                    
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid heartbeat format for {process_id}: {e}")
                # Clean up invalid entries
                await self.redis_client.hdel(self.heartbeat_key, process_id)
                cleaned_count += 1
        
        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} stale processes")
        
        return cleaned_count
    
    async def push_to_queue(self, queue_name: str, message: Dict[str, Any]) -> None:
        """
        Push message to FIFO queue
        
        Args:
            queue_name: Queue name
            message: Message to push
        """
        if not self.redis_client:
            raise RuntimeError("Redis not initialized")
        
        queue_key = f"{self.queues_key}:{queue_name}"
        message_json = json.dumps(message, default=str)
        
        await self.redis_client.rpush(queue_key, message_json)
        logger.debug(f"Pushed message to queue {queue_name}")
    
    async def pop_from_queue(
        self,
        queue_name: str,
        timeout: int = 0
    ) -> Optional[Dict[str, Any]]:
        """
        Pop message from FIFO queue (blocking)
        
        Args:
            queue_name: Queue name
            timeout: Timeout in seconds (0 = block indefinitely)
            
        Returns:
            Message dictionary or None if timeout
        """
        if not self.redis_client:
            raise RuntimeError("Redis not initialized")
        
        queue_key = f"{self.queues_key}:{queue_name}"
        
        try:
            result = await self.redis_client.blpop(queue_key, timeout=timeout)
            if result:
                _, message_json = result
                return json.loads(message_json)
        except asyncio.TimeoutError:
            pass
        
        return None
    
    async def get_queue_length(self, queue_name: str) -> int:
        """
        Get queue length
        
        Args:
            queue_name: Queue name
            
        Returns:
            Queue length
        """
        if not self.redis_client:
            return 0
        
        queue_key = f"{self.queues_key}:{queue_name}"
        return await self.redis_client.llen(queue_key)
    
    async def acquire_lock(
        self,
        lock_name: str,
        timeout: int = 30,
        blocking_timeout: Optional[int] = None
    ) -> Lock:
        """
        Acquire distributed lock using Redis SET command
        
        Args:
            lock_name: Lock name
            timeout: Lock timeout in seconds
            blocking_timeout: Time to wait for lock (None = don't block)
            
        Returns:
            Redis lock object
        """
        if not self.redis_client:
            raise RuntimeError("Redis not initialized")
        
        lock_key = f"{self.locks_key}:{lock_name}"
        
        lock = Lock(
            self.redis_client,
            lock_key,
            timeout=timeout,
            blocking_timeout=blocking_timeout
        )
        
        if await lock.acquire():
            logger.debug(f"Acquired lock: {lock_name}")
            return lock
        else:
            raise TimeoutError(f"Failed to acquire lock: {lock_name}")
    
    async def release_lock(self, lock: Lock) -> None:
        """
        Release distributed lock
        
        Args:
            lock: Lock object to release
        """
        try:
            await lock.release()
            logger.debug("Released lock")
        except Exception as e:
            logger.warning(f"Failed to release lock: {e}")
    
    async def set_value(
        self,
        key: str,
        value: Union[str, Dict, List],
        expire: Optional[int] = None
    ) -> None:
        """
        Set a value in Redis
        
        Args:
            key: Redis key
            value: Value to store
            expire: Expiration time in seconds
        """
        if not self.redis_client:
            raise RuntimeError("Redis not initialized")
        
        if isinstance(value, (dict, list)):
            value = json.dumps(value, default=str)
        
        await self.redis_client.set(key, value, ex=expire)
    
    async def get_value(self, key: str) -> Optional[Union[str, Dict, List]]:
        """
        Get a value from Redis
        
        Args:
            key: Redis key
            
        Returns:
            Value or None if not found
        """
        if not self.redis_client:
            return None
        
        value = await self.redis_client.get(key)
        if value is None:
            return None
        
        # Try to parse as JSON
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    
    async def delete_key(self, key: str) -> bool:
        """
        Delete a key from Redis
        
        Args:
            key: Redis key
            
        Returns:
            True if key was deleted, False if not found
        """
        if not self.redis_client:
            return False
        
        return await self.redis_client.delete(key) > 0
    
    async def _heartbeat_worker(self) -> None:
        """Background worker to update process heartbeat"""
        while not self._shutdown_event.is_set():
            try:
                await self.update_heartbeat()
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.heartbeat_interval
                )
            except asyncio.TimeoutError:
                # Timeout is expected, continue loop
                continue
            except Exception as e:
                logger.error(f"Heartbeat worker error: {e}")
                await asyncio.sleep(30)  # Wait before retrying
    
    async def _cleanup_worker(self) -> None:
        """Background worker to clean up stale processes"""
        while not self._shutdown_event.is_set():
            try:
                await self.cleanup_stale_processes()
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.cleanup_interval
                )
            except asyncio.TimeoutError:
                # Timeout is expected, continue loop
                continue
            except Exception as e:
                logger.error(f"Cleanup worker error: {e}")
                await asyncio.sleep(60)  # Wait before retrying


# Context manager for lock acquisition
class RedisLock:
    """Context manager for Redis locks"""
    
    def __init__(
        self,
        redis_manager: RedisManager,
        lock_name: str,
        timeout: int = 30,
        blocking_timeout: Optional[int] = None
    ):
        self.redis_manager = redis_manager
        self.lock_name = lock_name
        self.timeout = timeout
        self.blocking_timeout = blocking_timeout
        self.lock: Optional[Lock] = None
    
    async def __aenter__(self):
        self.lock = await self.redis_manager.acquire_lock(
            self.lock_name,
            self.timeout,
            self.blocking_timeout
        )
        return self.lock
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.lock:
            await self.redis_manager.release_lock(self.lock)


# Export commonly used classes
__all__ = [
    'RedisManager',
    'RedisLock'
]
