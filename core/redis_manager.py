"""
Redis/Valkey Manager with Optional Fallbacks

Handles process management, distributed locking, and FIFO queues using Redis.
When Redis is unavailable, provides database and in-memory fallbacks.
"""

import asyncio
import json
import os
import threading
import uuid
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

try:
    import redis.asyncio as redis
    from redis.asyncio.lock import Lock
    from redis.exceptions import ConnectionError, TimeoutError as RedisTimeoutError
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None
    Lock = None
    ConnectionError = Exception
    RedisTimeoutError = Exception

from .logging import get_logger

logger = get_logger(__name__)


class FallbackQueue:
    """In-memory FIFO queue fallback when Redis is unavailable"""
    
    def __init__(self):
        self.queue = deque()
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
    
    def push(self, message: Dict[str, Any]) -> None:
        """Push message to queue"""
        with self.condition:
            self.queue.append(message)
            self.condition.notify()
    
    def pop(self, timeout: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Pop message from queue (blocking)"""
        with self.condition:
            if timeout is None:
                while len(self.queue) == 0:
                    self.condition.wait()
            else:
                end_time = datetime.now() + timedelta(seconds=timeout)
                while len(self.queue) == 0:
                    remaining = (end_time - datetime.now()).total_seconds()
                    if remaining <= 0:
                        return None
                    self.condition.wait(timeout=remaining)
            
            if self.queue:
                return self.queue.popleft()
            return None
    
    def length(self) -> int:
        """Get queue length"""
        with self.lock:
            return len(self.queue)


class FallbackLock:
    """Local thread-based lock fallback when Redis is unavailable"""
    
    def __init__(self, name: str, timeout: int = 30):
        self.name = name
        self.timeout = timeout
        self.lock = threading.RLock()
        self.acquired = False
    
    async def acquire(self) -> bool:
        """Acquire lock"""
        try:
            self.acquired = self.lock.acquire(timeout=self.timeout)
            return self.acquired
        except Exception:
            return False
    
    async def release(self) -> None:
        """Release lock"""
        if self.acquired:
            try:
                self.lock.release()
                self.acquired = False
            except Exception:
                pass


class RedisManager:
    """
    Redis/Valkey connection and process management with optional fallbacks
    
    Provides:
    - Process registration and heartbeat (Redis or database fallback)
    - FIFO queues with BLPOP (Redis or in-memory fallback)  
    - Distributed locking (Redis or local fallback)
    - Process cleanup
    - Graceful degradation when Redis is unavailable
    """
    
    def __init__(self, redis_url: str = "redis://localhost:6379/0", db_manager=None):
        """
        Initialize Redis manager
        
        Args:
            redis_url: Redis connection URL
            db_manager: Database manager for fallback storage
        """
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self.db_manager = db_manager
        self.redis_available = False
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
        
        # Fallback storage
        self._fallback_processes: Dict[str, Dict[str, Any]] = {}
        self._fallback_queues: Dict[str, FallbackQueue] = {}
        self._fallback_locks: Dict[str, FallbackLock] = {}
        self._fallback_data: Dict[str, Any] = {}
        
        # Background tasks
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
    
    async def initialize(self) -> bool:
        """
        Initialize Redis connection and start background tasks
        
        Returns:
            True if Redis is available, False if using fallbacks
        """
        if not REDIS_AVAILABLE:
            logger.warning("Redis library not available, using fallback mechanisms")
            self.redis_available = False
            await self._initialize_fallbacks()
            return False
        
        try:
            # Parse Redis URL and create connection
            self.redis_client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_keepalive=True,
                socket_keepalive_options={},
                health_check_interval=30
            )
            
            # Test connection with short timeout
            await asyncio.wait_for(self.redis_client.ping(), timeout=5.0)
            self.redis_available = True
            logger.info(f"Connected to Redis at {self.redis_url}")
            
            # Register this process
            await self.register_process()
            
            # Start background tasks
            self._heartbeat_task = asyncio.create_task(self._heartbeat_worker())
            self._cleanup_task = asyncio.create_task(self._cleanup_worker())
            
            logger.info(f"Redis manager initialized with process ID: {self.process_id}")
            return True
            
        except (ConnectionError, RedisTimeoutError, asyncio.TimeoutError) as e:
            logger.warning(f"Redis connection failed: {e}, using fallback mechanisms")
            self.redis_available = False
            self.redis_client = None
            await self._initialize_fallbacks()
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Redis manager: {e}, using fallbacks")
            self.redis_available = False
            self.redis_client = None
            await self._initialize_fallbacks()
            return False
    
    async def _initialize_fallbacks(self) -> None:
        """Initialize fallback mechanisms"""
        logger.info("Initializing fallback mechanisms for Redis functionality")
        
        # Register process in fallback storage
        await self.register_process()
        
        # Start heartbeat worker for fallback mode
        self._heartbeat_task = asyncio.create_task(self._heartbeat_worker())
        
        logger.info(f"Fallback mechanisms initialized with process ID: {self.process_id}")
    
    async def is_connected(self) -> bool:
        """Check if Redis is connected"""
        if not self.redis_available or not self.redis_client:
            return False
        
        try:
            await self.redis_client.ping()
            return True
        except:
            return False
    
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
        Register this process in Redis or fallback storage
        
        Args:
            process_type: Type of process (e.g., 'dicom_scp', 'web_server')
            metadata: Additional process metadata
        """
        if process_type:
            self.process_type = process_type
        
        process_info = {
            'process_id': self.process_id,
            'type': self.process_type,
            'pid': os.getpid(),
            'started_at': datetime.now().isoformat(),
            'last_heartbeat': datetime.now().isoformat(),
            'metadata': metadata or {},
            'redis_available': self.redis_available
        }
        
        if self.redis_available and self.redis_client:
            try:
                # Store process info in Redis
                await self.redis_client.hset(
                    self.processes_key,
                    self.process_id,
                    json.dumps(process_info)
                )
                
                # Update heartbeat
                await self.update_heartbeat()
                
                logger.info(f"Registered process {self.process_id} as {self.process_type} in Redis")
                return
            except Exception as e:
                logger.warning(f"Failed to register in Redis: {e}, using fallback")
                self.redis_available = False
        
        # Fallback: store in memory and database
        self._fallback_processes[self.process_id] = process_info
        
        if self.db_manager:
            try:
                await self.db_manager.set_config(
                    f"process_{self.process_id}",
                    json.dumps(process_info)
                )
            except Exception as e:
                logger.warning(f"Failed to register in database: {e}")
        
        logger.info(f"Registered process {self.process_id} as {self.process_type} in fallback storage")
    
    async def unregister_process(self) -> None:
        """Unregister this process from Redis or fallback storage"""
        if self.redis_available and self.redis_client:
            try:
                # Remove from Redis
                await self.redis_client.hdel(self.processes_key, self.process_id)
                await self.redis_client.hdel(self.heartbeat_key, self.process_id)
                
                logger.info(f"Unregistered process {self.process_id} from Redis")
                return
            except Exception:
                pass
        
        # Fallback: remove from memory and database
        self._fallback_processes.pop(self.process_id, None)
        
        if self.db_manager:
            try:
                await self.db_manager.execute_query(
                    "DELETE FROM config WHERE name = ?",
                    (f"process_{self.process_id}",)
                )
            except Exception as e:
                logger.warning(f"Failed to unregister from database: {e}")
        
        logger.info(f"Unregistered process {self.process_id} from fallback storage")
    
    async def update_heartbeat(self) -> None:
        """Update process heartbeat timestamp"""
        timestamp = datetime.now().isoformat()
        
        if self.redis_available and self.redis_client:
            try:
                # Update heartbeat in Redis
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
                return
            except Exception:
                logger.warning("Failed to update heartbeat in Redis, using fallback")
                self.redis_available = False
        
        # Fallback: update in memory
        if self.process_id in self._fallback_processes:
            self._fallback_processes[self.process_id]['last_heartbeat'] = timestamp
    
    async def get_process_info(self, process_id: str) -> Optional[Dict[str, Any]]:
        """
        Get process information
        
        Args:
            process_id: Process ID to lookup
            
        Returns:
            Process information dictionary or None
        """
        if self.redis_available and self.redis_client:
            try:
                process_data = await self.redis_client.hget(self.processes_key, process_id)
                if process_data:
                    return json.loads(process_data)
            except Exception:
                pass
        
        # Fallback: check memory first, then database
        if process_id in self._fallback_processes:
            return self._fallback_processes[process_id]
        
        if self.db_manager:
            try:
                result = await self.db_manager.get_config(f"process_{process_id}")
                if result:
                    return json.loads(result)
            except Exception:
                pass
        
        return None
    
    async def list_processes(self) -> Dict[str, Dict[str, Any]]:
        """
        List all registered processes
        
        Returns:
            Dictionary mapping process IDs to process info
        """
        if self.redis_available and self.redis_client:
            try:
                processes = await self.redis_client.hgetall(self.processes_key)
                return {pid: json.loads(info) for pid, info in processes.items()}
            except Exception:
                pass
        
        # Fallback: return in-memory processes
        return dict(self._fallback_processes)
    
    async def push_to_queue(self, queue_name: str, message: Dict[str, Any]) -> None:
        """
        Push message to FIFO queue
        
        Args:
            queue_name: Queue name
            message: Message to push
        """
        if self.redis_available and self.redis_client:
            try:
                queue_key = f"{self.queues_key}:{queue_name}"
                message_json = json.dumps(message, default=str)
                await self.redis_client.rpush(queue_key, message_json)
                logger.debug(f"Pushed message to Redis queue {queue_name}")
                return
            except Exception as e:
                logger.warning(f"Failed to push to Redis queue: {e}, using fallback")
                self.redis_available = False
        
        # Fallback: use in-memory queue
        if queue_name not in self._fallback_queues:
            self._fallback_queues[queue_name] = FallbackQueue()
        
        self._fallback_queues[queue_name].push(message)
        logger.debug(f"Pushed message to fallback queue {queue_name}")
    
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
        if self.redis_available and self.redis_client:
            try:
                queue_key = f"{self.queues_key}:{queue_name}"
                result = await self.redis_client.blpop(queue_key, timeout=timeout)
                if result:
                    _, message_json = result
                    return json.loads(message_json)
                return None
            except Exception as e:
                logger.warning(f"Failed to pop from Redis queue: {e}, using fallback")
                self.redis_available = False
        
        # Fallback: use in-memory queue
        if queue_name not in self._fallback_queues:
            self._fallback_queues[queue_name] = FallbackQueue()
        
        # Convert to sync call for fallback queue
        return await asyncio.get_event_loop().run_in_executor(
            None,
            self._fallback_queues[queue_name].pop,
            timeout if timeout > 0 else None
        )
    
    async def get_queue_length(self, queue_name: str) -> int:
        """
        Get queue length
        
        Args:
            queue_name: Queue name
            
        Returns:
            Queue length
        """
        if self.redis_available and self.redis_client:
            try:
                queue_key = f"{self.queues_key}:{queue_name}"
                return await self.redis_client.llen(queue_key)
            except Exception:
                pass
        
        # Fallback: check in-memory queue
        if queue_name in self._fallback_queues:
            return self._fallback_queues[queue_name].length()
        return 0
    
    async def acquire_lock(
        self,
        lock_name: str,
        timeout: int = 30,
        blocking_timeout: Optional[int] = None
    ) -> Union[Lock, FallbackLock]:
        """
        Acquire distributed lock using Redis or fallback
        
        Args:
            lock_name: Lock name
            timeout: Lock timeout in seconds
            blocking_timeout: Time to wait for lock (None = don't block)
            
        Returns:
            Lock object (Redis or fallback)
        """
        if self.redis_available and self.redis_client:
            try:
                lock_key = f"{self.locks_key}:{lock_name}"
                lock = Lock(
                    self.redis_client,
                    lock_key,
                    timeout=timeout,
                    blocking_timeout=blocking_timeout
                )
                
                if await lock.acquire():
                    logger.debug(f"Acquired Redis lock: {lock_name}")
                    return lock
                else:
                    raise asyncio.TimeoutError(f"Failed to acquire Redis lock: {lock_name}")
            except Exception as e:
                logger.warning(f"Failed to acquire Redis lock: {e}, using fallback")
                self.redis_available = False
        
        # Fallback: use local lock
        if lock_name not in self._fallback_locks:
            self._fallback_locks[lock_name] = FallbackLock(lock_name, timeout)
        
        lock = self._fallback_locks[lock_name]
        if await lock.acquire():
            logger.debug(f"Acquired fallback lock: {lock_name}")
            return lock
        else:
            raise asyncio.TimeoutError(f"Failed to acquire fallback lock: {lock_name}")
    
    async def release_lock(self, lock: Union[Lock, FallbackLock]) -> None:
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
        Set a value in Redis or fallback storage
        
        Args:
            key: Redis key
            value: Value to store
            expire: Expiration time in seconds
        """
        if self.redis_available and self.redis_client:
            try:
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, default=str)
                await self.redis_client.set(key, value, ex=expire)
                return
            except Exception:
                self.redis_available = False
        
        # Fallback: store in memory (expiration not supported)
        self._fallback_data[key] = value
    
    async def get_value(self, key: str) -> Optional[Union[str, Dict, List]]:
        """
        Get a value from Redis or fallback storage
        
        Args:
            key: Redis key
            
        Returns:
            Value or None if not found
        """
        if self.redis_available and self.redis_client:
            try:
                value = await self.redis_client.get(key)
                if value is None:
                    return None
                
                # Try to parse as JSON
                try:
                    return json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    return value
            except Exception:
                self.redis_available = False
        
        # Fallback: check memory
        return self._fallback_data.get(key)
    
    async def delete_key(self, key: str) -> bool:
        """
        Delete a key from Redis or fallback storage
        
        Args:
            key: Redis key
            
        Returns:
            True if key was deleted, False if not found
        """
        if self.redis_available and self.redis_client:
            try:
                return await self.redis_client.delete(key) > 0
            except Exception:
                self.redis_available = False
        
        # Fallback: remove from memory
        if key in self._fallback_data:
            del self._fallback_data[key]
            return True
        return False
    
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
        if not self.redis_available:
            return  # Skip cleanup for fallback mode
        
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
    
    async def cleanup_stale_processes(self) -> int:
        """
        Clean up stale/dead processes
        
        Returns:
            Number of processes cleaned up
        """
        if not self.redis_available or not self.redis_client:
            return 0
        
        cleaned_count = 0
        cutoff_time = datetime.now() - timedelta(seconds=self.process_timeout)
        
        try:
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
        
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        
        return cleaned_count


# Context manager for lock acquisition
class RedisLock:
    """Context manager for Redis locks with fallback support"""
    
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
        self.lock: Optional[Union[Lock, FallbackLock]] = None
    
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
    'RedisLock',
    'FallbackQueue',
    'FallbackLock'
]
