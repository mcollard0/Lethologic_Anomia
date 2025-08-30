"""
Logging system for the Migration Service

Provides structured logging with database integration and multiple output formats.
Equivalent to the C++ dblog functionality with enhanced features.
"""

import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union

from rich.console import Console
from rich.logging import RichHandler
from rich.traceback import install

# Install rich traceback
install()

# Global console for rich output
console = Console()


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
    enable_json_format: bool = False
) -> logging.Logger:
    """
    Set up comprehensive logging system
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path
        enable_database_logging: Whether to enable database logging
        enable_rich_console: Whether to use rich console output
        enable_json_format: Whether to use JSON formatting for file logs
        
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
    
    # Console handler with rich formatting
    if enable_rich_console:
        console_handler = RichHandler(
            console=console,
            show_time=True,
            show_level=True,
            show_path=True,
            markup=True,
            rich_tracebacks=True
        )
        console_handler.setLevel(numeric_level)
        root_logger.addHandler(console_handler)
    else:
        # Standard console handler
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(numeric_level)
        root_logger.addHandler(console_handler)
    
    # File handler if specified
    if log_file:
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
    'create_context_logger',
    'dblog',
    'log_performance',
    'DatabaseLogHandler',
    'JsonFormatter',
    'ContextFilter'
]
