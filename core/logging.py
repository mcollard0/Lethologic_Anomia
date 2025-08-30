"""
Logging System for Lethologic Anomia

Provides structured logging with database integration and multiple output formats.
Equivalent to the C++ dblog functionality with enhanced features.
"""

import asyncio
import json
import logging
import logging.handlers
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from rich.console import Console
from rich.logging import RichHandler
from rich.traceback import install

# Install rich traceback
install()

# Global console for rich output
console = Console()


class RedisRingBufferHandler(logging.Handler):
    """
    Custom log handler that writes to Redis as a ring buffer
    
    This handler stores log entries in Redis as a circular buffer with a maximum size.
    When the buffer is full, new entries overwrite the oldest ones.
    """
    
    def __init__(self, redis_manager=None, buffer_size: int = 1000, key_prefix: str = "migration:logs"):
        super().__init__()
        self.redis_manager = redis_manager
        self.buffer_size = buffer_size
        self.log_key = f"{key_prefix}:ring_buffer"
        self.index_key = f"{key_prefix}:index"
        self.max_key = f"{key_prefix}:max_index"
        
    def emit(self, record: logging.LogRecord):
        """Emit log record to Redis ring buffer"""
        if not self.redis_manager or not self.redis_manager.redis_client:
            return
            
        try:
            # Format the log entry
            log_entry = {
                'timestamp': datetime.fromtimestamp(record.created).isoformat(),
                'level': record.levelname,
                'logger': record.name,
                'module': record.module,
                'function': getattr(record, 'funcName', 'unknown'),
                'line': record.lineno,
                'message': record.getMessage(),
                'thread': record.thread,
                'process': os.getpid(),
            }
            
            # Add exception info if present
            if record.exc_info:
                log_entry['exception'] = self.format(record)
            
            # Write to Redis ring buffer asynchronously
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(self._write_to_redis_ring(log_entry))
            except RuntimeError:
                # No event loop, skip Redis logging
                pass
                
        except Exception as e:
            # Don't let logging errors crash the application
            print(f"Redis ring buffer logging error: {e}", file=sys.stderr)
    
    async def _write_to_redis_ring(self, log_entry: Dict[str, Any]):
        """Write log entry to Redis ring buffer"""
        if not self.redis_manager or not self.redis_manager.redis_client:
            return
            
        try:
            redis_client = self.redis_manager.redis_client
            
            # Get current index and increment atomically
            current_index = await redis_client.incr(self.index_key)
            
            # Calculate ring buffer position
            ring_position = (current_index - 1) % self.buffer_size
            
            # Store log entry at ring position
            log_data = json.dumps(log_entry, default=str)
            await redis_client.hset(self.log_key, str(ring_position), log_data)
            
            # Update max index for tracking
            await redis_client.set(self.max_key, current_index)
            
            # Set expiration on ring buffer (optional, for cleanup)
            await redis_client.expire(self.log_key, 86400)  # 24 hours
            await redis_client.expire(self.index_key, 86400)
            await redis_client.expire(self.max_key, 86400)
            
        except Exception as e:
            print(f"Failed to write log to Redis ring buffer: {e}", file=sys.stderr)
    
    async def get_logs(self, count: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieve logs from the ring buffer
        
        Args:
            count: Number of logs to retrieve (None = all available)
            
        Returns:
            List of log entries in chronological order (oldest first)
        """
        if not self.redis_manager or not self.redis_manager.redis_client:
            return []
        
        try:
            redis_client = self.redis_manager.redis_client
            
            # Get current state
            max_index_str = await redis_client.get(self.max_key)
            if not max_index_str:
                return []
                
            max_index = int(max_index_str)
            total_entries = min(max_index, self.buffer_size)
            
            if count is not None:
                total_entries = min(total_entries, count)
            
            # Calculate starting position for chronological order
            if max_index <= self.buffer_size:
                # Buffer not full yet, start from 0
                start_pos = 0
            else:
                # Buffer is full, start from oldest entry
                start_pos = max_index % self.buffer_size
            
            # Retrieve log entries
            logs = []
            for i in range(total_entries):
                pos = (start_pos + i) % self.buffer_size
                log_data = await redis_client.hget(self.log_key, str(pos))
                if log_data:
                    try:
                        log_entry = json.loads(log_data)
                        logs.append(log_entry)
                    except json.JSONDecodeError:
                        continue
            
            return logs
            
        except Exception as e:
            print(f"Failed to retrieve logs from Redis ring buffer: {e}", file=sys.stderr)
            return []
    
    async def clear_logs(self):
        """Clear the ring buffer"""
        if not self.redis_manager or not self.redis_manager.redis_client:
            return
        
        try:
            redis_client = self.redis_manager.redis_client
            await redis_client.delete(self.log_key, self.index_key, self.max_key)
        except Exception as e:
            print(f"Failed to clear Redis ring buffer: {e}", file=sys.stderr)


class DatabaseLogHandler(logging.Handler):
    """Custom log handler that writes to database"""
    
    def __init__(self, db_manager=None):
        super().__init__()
        self.db_manager = db_manager
    
    def emit(self, record: logging.LogRecord):
        """Emit log record to database"""
        if not self.db_manager:
            return
            
        try:
            # Format the log entry for database
            log_entry = {
                'timestamp': datetime.fromtimestamp(record.created),
                'level': record.levelname,
                'module': record.module,
                'function': getattr(record, 'funcName', 'unknown'),
                'message': record.getMessage(),
                'thread_id': record.thread,
                'process_id': os.getpid(),
            }
            
            # Add exception info if present
            if record.exc_info:
                log_entry['exception'] = self.format(record)
            
            # Write to database asynchronously (don't block logging)
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(self._write_to_db(log_entry))
            except RuntimeError:
                # No event loop, skip database logging
                pass
                
        except Exception as e:
            # Don't let logging errors crash the application
            print(f"Database logging error: {e}", file=sys.stderr)
    
    async def _write_to_db(self, log_entry: Dict[str, Any]):
        """Write log entry to database"""
        if not self.db_manager:
            return
            
        try:
            # Use the database manager to insert log entry
            await self.db_manager.log_message(
                level=log_entry['level'],
                module=log_entry['module'],
                function=log_entry['function'], 
                message=log_entry['message'],
                timestamp=log_entry['timestamp'],
                thread_id=log_entry.get('thread_id'),
                process_id=log_entry.get('process_id'),
                exception=log_entry.get('exception')
            )
        except Exception as e:
            print(f"Failed to write log to database: {e}", file=sys.stderr)


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'module': record.module,
            'function': getattr(record, 'funcName', 'unknown'),
            'line': record.lineno,
            'message': record.getMessage(),
            'thread': record.thread,
            'process': os.getpid(),
        }
        
        # Add exception info if present
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)
        
        # Add any extra fields
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 
                          'filename', 'module', 'lineno', 'funcName', 'created', 
                          'msecs', 'relativeCreated', 'thread', 'threadName', 
                          'processName', 'process', 'exc_info', 'exc_text', 'stack_info']:
                log_obj[key] = value
        
        return json.dumps(log_obj, default=str)


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    enable_database_logging: bool = True,
    enable_rich_console: bool = True,
    enable_json_format: bool = False,
    redis_manager=None,
    enable_redis_logging: bool = True,
    redis_buffer_size: int = 1000,
    log_destinations: List[str] = None
) -> logging.Logger:
    """
    Set up comprehensive logging system with flexible destinations
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path
        enable_database_logging: Whether to enable database logging
        enable_rich_console: Whether to use rich console output
        enable_json_format: Whether to use JSON formatting for file logs
        redis_manager: Redis manager instance for Redis logging
        enable_redis_logging: Whether to enable Redis ring buffer logging
        redis_buffer_size: Size of Redis ring buffer
        log_destinations: List of log destinations ['console', 'file', 'database', 'redis', 'none']
        
    Returns:
        Root logger instance
    """
    # Convert string level to logging constant
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Clear any existing handlers
    root_logger.handlers.clear()
    
    # Determine destinations - if not specified, use legacy behavior
    if log_destinations is None:
        log_destinations = []
        if enable_rich_console:
            log_destinations.append('console')
        if log_file:
            log_destinations.append('file')
        if enable_database_logging:
            log_destinations.append('database')
        if enable_redis_logging and redis_manager:
            log_destinations.append('redis')
    
    # Handle 'none' destination (no logging)
    if 'none' in log_destinations:
        # Add null handler to prevent logging
        root_logger.addHandler(logging.NullHandler())
        return root_logger
    
    # Console handler
    if 'console' in log_destinations:
        if enable_rich_console:
            console_handler = RichHandler(
                console=console,
                show_time=True,
                show_level=True,
                show_path=True,
                markup=True,
                rich_tracebacks=True
            )
        else:
            console_handler = logging.StreamHandler()
            console_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            console_handler.setFormatter(console_formatter)
        
        console_handler.setLevel(numeric_level)
        root_logger.addHandler(console_handler)
    
    # File handler
    if 'file' in log_destinations and log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Rotating file handler to prevent huge log files
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(numeric_level)
        
        if enable_json_format:
            file_handler.setFormatter(JsonFormatter())
        else:
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(funcName)s:%(lineno)d - %(message)s'
            )
            file_handler.setFormatter(file_formatter)
        
        root_logger.addHandler(file_handler)
    
    # Redis ring buffer handler
    if 'redis' in log_destinations and redis_manager:
        redis_handler = RedisRingBufferHandler(
            redis_manager=redis_manager,
            buffer_size=redis_buffer_size
        )
        redis_handler.setLevel(numeric_level)
        root_logger.addHandler(redis_handler)
        
        # Store reference to Redis handler for later use
        root_logger._redis_handler = redis_handler
    
    # Database handler will be added later when database manager is available
    
    # Set up third-party library logging levels
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific module
    
    Args:
        name: Logger name (usually __name__)
        
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def add_database_handler(logger: logging.Logger, db_manager) -> None:
    """
    Add database logging handler to an existing logger
    
    Args:
        logger: Logger to add handler to
        db_manager: Database manager instance
    """
    db_handler = DatabaseLogHandler(db_manager)
    db_handler.setLevel(logging.INFO)  # Only log INFO and above to database
    logger.addHandler(db_handler)


class ContextFilter(logging.Filter):
    """Filter to add context information to log records"""
    
    def __init__(self, context: Dict[str, Any]):
        super().__init__()
        self.context = context
    
    def filter(self, record: logging.LogRecord) -> bool:
        # Add context fields to the record
        for key, value in self.context.items():
            setattr(record, key, value)
        return True


def create_context_logger(
    name: str, 
    context: Dict[str, Any], 
    base_logger: Optional[logging.Logger] = None
) -> logging.Logger:
    """
    Create a logger with additional context information
    
    Args:
        name: Logger name
        context: Context dictionary to add to all log messages
        base_logger: Base logger to derive from
        
    Returns:
        Logger with context filter applied
    """
    if base_logger is None:
        logger = get_logger(name)
    else:
        logger = base_logger.getChild(name)
    
    context_filter = ContextFilter(context)
    logger.addFilter(context_filter)
    
    return logger


# Legacy compatibility functions (matching C++ dblog functionality)
def dblog(db_manager, module: str, level: str, message: str) -> None:
    """
    Legacy database logging function for compatibility with C++ code
    
    Args:
        db_manager: Database manager (for compatibility, not used directly)
        module: Module name
        level: Log level string
        message: Log message
    """
    logger = get_logger(module)
    
    # Map string levels to logging levels
    level_mapping = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'WARN': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL,
        'FATAL': logging.CRITICAL,
    }
    
    numeric_level = level_mapping.get(level.upper(), logging.INFO)
    logger.log(numeric_level, message)


# Performance monitoring decorator
def add_redis_handler(logger: logging.Logger, redis_manager, buffer_size: int = 1000) -> None:
    """
    Add Redis ring buffer handler to an existing logger
    
    Args:
        logger: Logger to add handler to
        redis_manager: Redis manager instance
        buffer_size: Size of the ring buffer
    """
    redis_handler = RedisRingBufferHandler(redis_manager, buffer_size)
    redis_handler.setLevel(logging.INFO)  # Only log INFO and above to Redis
    logger.addHandler(redis_handler)
    
    # Store reference for later access
    logger._redis_handler = redis_handler


async def get_redis_logs(
    logger: logging.Logger, 
    count: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve logs from Redis ring buffer
    
    Args:
        logger: Logger with Redis handler
        count: Number of logs to retrieve
        
    Returns:
        List of log entries
    """
    if hasattr(logger, '_redis_handler'):
        return await logger._redis_handler.get_logs(count)
    return []


async def clear_redis_logs(logger: logging.Logger) -> None:
    """
    Clear Redis ring buffer logs
    
    Args:
        logger: Logger with Redis handler
    """
    if hasattr(logger, '_redis_handler'):
        await logger._redis_handler.clear_logs()


class LogPollingService:
    """
    Service to poll Redis ring buffer and persist logs to file or database
    
    This class implements the requirement to poll the Redis ring buffer
    and store logs to configured destinations (file or database).
    """
    
    def __init__(
        self,
        redis_manager,
        db_manager=None,
        log_file: Optional[str] = None,
        poll_interval: int = 60,  # seconds
        batch_size: int = 100
    ):
        self.redis_manager = redis_manager
        self.db_manager = db_manager
        self.log_file = log_file
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        self.redis_handler = RedisRingBufferHandler(redis_manager)
        self._running = False
        self._poll_task: Optional[asyncio.Task] = None
        
        # Set up file handler if needed
        self.file_handler = None
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self.file_handler = logging.FileHandler(log_file)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            self.file_handler.setFormatter(formatter)
    
    async def start(self) -> None:
        """Start the log polling service"""
        if self._running:
            return
            
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        
    async def stop(self) -> None:
        """Stop the log polling service"""
        self._running = False
        
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
    
    async def _poll_loop(self) -> None:
        """Main polling loop"""
        while self._running:
            try:
                # Get logs from Redis ring buffer
                logs = await self.redis_handler.get_logs(self.batch_size)
                
                if logs:
                    await self._persist_logs(logs)
                
                # Wait for next poll
                await asyncio.sleep(self.poll_interval)
                
            except Exception as e:
                print(f"Log polling error: {e}", file=sys.stderr)
                await asyncio.sleep(10)  # Wait before retrying
    
    async def _persist_logs(self, logs: List[Dict[str, Any]]) -> None:
        """Persist logs to configured destinations"""
        # Persist to database if available
        if self.db_manager:
            await self._persist_to_database(logs)
        
        # Persist to file if configured
        if self.file_handler:
            await self._persist_to_file(logs)
    
    async def _persist_to_database(self, logs: List[Dict[str, Any]]) -> None:
        """Persist logs to database"""
        try:
            for log_entry in logs:
                await self.db_manager.log_message(
                    level=log_entry.get('level', 'INFO'),
                    module=log_entry.get('module', 'unknown'),
                    function=log_entry.get('function', 'unknown'),
                    message=log_entry.get('message', ''),
                    timestamp=datetime.fromisoformat(log_entry.get('timestamp', datetime.now().isoformat())),
                    thread_id=log_entry.get('thread'),
                    process_id=log_entry.get('process'),
                    exception=log_entry.get('exception')
                )
        except Exception as e:
            print(f"Failed to persist logs to database: {e}", file=sys.stderr)
    
    async def _persist_to_file(self, logs: List[Dict[str, Any]]) -> None:
        """Persist logs to file"""
        try:
            # Create log records and emit to file handler
            for log_entry in logs:
                # Create a mock LogRecord for file output
                record = logging.LogRecord(
                    name=log_entry.get('logger', 'migration'),
                    level=getattr(logging, log_entry.get('level', 'INFO')),
                    pathname='',
                    lineno=log_entry.get('line', 0),
                    msg=log_entry.get('message', ''),
                    args=(),
                    exc_info=None
                )
                record.created = time.mktime(
                    datetime.fromisoformat(log_entry.get('timestamp', datetime.now().isoformat())).timetuple()
                )
                record.module = log_entry.get('module', 'unknown')
                record.funcName = log_entry.get('function', 'unknown')
                record.thread = log_entry.get('thread', 0)
                record.process = log_entry.get('process', 0)
                
                # Emit to file handler
                self.file_handler.emit(record)
                
        except Exception as e:
            print(f"Failed to persist logs to file: {e}", file=sys.stderr)


def log_performance(logger: Optional[logging.Logger] = None):
    """
    Decorator to log function execution time
    
    Args:
        logger: Logger to use (defaults to function's module logger)
    """
    def decorator(func):
        import functools
        import time
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if logger is None:
                func_logger = get_logger(func.__module__)
            else:
                func_logger = logger
            
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                func_logger.debug(
                    f"Function {func.__name__} executed in {execution_time:.4f} seconds"
                )
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                func_logger.error(
                    f"Function {func.__name__} failed after {execution_time:.4f} seconds: {e}"
                )
                raise
        
        return wrapper
    return decorator


# Export commonly used functions
__all__ = [
    'setup_logging',
    'get_logger', 
    'add_database_handler',
    'add_redis_handler',
    'create_context_logger',
    'dblog',
    'log_performance',
    'get_redis_logs',
    'clear_redis_logs',
    'DatabaseLogHandler',
    'RedisRingBufferHandler',
    'JsonFormatter',
    'ContextFilter',
    'LogPollingService'
]
