"""
Platform Utilities

Cross-platform utilities for detecting OS, setting up signal handlers,
and managing platform-specific functionality.
"""

import os
import platform
import signal
import sys
from typing import Callable, Optional
from enum import Enum

from ..core.logging import get_logger

logger = get_logger(__name__)


class OSType(Enum):
    """Operating system types"""
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    UNKNOWN = "unknown"


def detect_os() -> OSType:
    """
    Detect the current operating system
    
    Returns:
        OSType enum value
    """
    system = platform.system().lower()
    
    if system == "windows":
        return OSType.WINDOWS
    elif system == "linux":
        return OSType.LINUX
    elif system == "darwin":
        return OSType.MACOS
    else:
        logger.warning(f"Unknown operating system: {system}")
        return OSType.UNKNOWN


def get_platform_info() -> dict:
    """
    Get detailed platform information
    
    Returns:
        Dictionary with platform details
    """
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "architecture": platform.architecture(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation()
    }


def setup_signal_handlers(handler: Callable):
    """
    Setup signal handlers for graceful shutdown
    
    Args:
        handler: Signal handler function
    """
    try:
        os_type = detect_os()
        
        if os_type == OSType.WINDOWS:
            # Windows signal handling
            signal.signal(signal.SIGINT, handler)
            signal.signal(signal.SIGTERM, handler)
            
            # Windows-specific signals
            if hasattr(signal, 'SIGBREAK'):
                signal.signal(signal.SIGBREAK, handler)
                
        else:
            # Unix-like signal handling
            signal.signal(signal.SIGINT, handler)
            signal.signal(signal.SIGTERM, handler)
            signal.signal(signal.SIGHUP, handler)
            
            # Additional Unix signals
            if hasattr(signal, 'SIGUSR1'):
                signal.signal(signal.SIGUSR1, handler)
            if hasattr(signal, 'SIGUSR2'):
                signal.signal(signal.SIGUSR2, handler)
        
        logger.info(f"Signal handlers configured for {os_type.value}")
        
    except Exception as e:
        logger.error(f"Failed to setup signal handlers: {e}")


def get_default_config_paths() -> list:
    """
    Get default configuration file paths for the current platform
    
    Returns:
        List of potential configuration file paths
    """
    os_type = detect_os()
    
    if os_type == OSType.WINDOWS:
        # Windows configuration paths
        paths = [
            os.path.join(os.environ.get('APPDATA', ''), 'MigrationService', 'config.yaml'),
            os.path.join(os.environ.get('PROGRAMDATA', ''), 'MigrationService', 'config.yaml'),
            os.path.join(os.getcwd(), 'config.yaml'),
            os.path.join(os.getcwd(), 'migration_service.yaml')
        ]
    else:
        # Unix-like configuration paths
        home_dir = os.path.expanduser('~')
        paths = [
            os.path.join(home_dir, '.config', 'migration-service', 'config.yaml'),
            os.path.join(home_dir, '.migration-service.yaml'),
            '/etc/migration-service/config.yaml',
            '/usr/local/etc/migration-service/config.yaml',
            os.path.join(os.getcwd(), 'config.yaml'),
            os.path.join(os.getcwd(), 'migration_service.yaml')
        ]
    
    return paths


def get_default_data_directory() -> str:
    """
    Get default data directory for the current platform
    
    Returns:
        Default data directory path
    """
    os_type = detect_os()
    
    if os_type == OSType.WINDOWS:
        # Windows data directory
        return os.path.join(os.environ.get('APPDATA', ''), 'MigrationService')
    else:
        # Unix-like data directory
        home_dir = os.path.expanduser('~')
        return os.path.join(home_dir, '.local', 'share', 'migration-service')


def get_default_log_directory() -> str:
    """
    Get default log directory for the current platform
    
    Returns:
        Default log directory path
    """
    os_type = detect_os()
    
    if os_type == OSType.WINDOWS:
        # Windows log directory
        return os.path.join(os.environ.get('APPDATA', ''), 'MigrationService', 'logs')
    else:
        # Unix-like log directory
        home_dir = os.path.expanduser('~')
        return os.path.join(home_dir, '.local', 'share', 'migration-service', 'logs')


def ensure_directory_exists(directory_path: str) -> bool:
    """
    Ensure a directory exists, create if necessary
    
    Args:
        directory_path: Path to directory
        
    Returns:
        True if directory exists or was created successfully
    """
    try:
        os.makedirs(directory_path, exist_ok=True)
        return True
    except Exception as e:
        logger.error(f"Failed to create directory {directory_path}: {e}")
        return False


def is_admin() -> bool:
    """
    Check if running with administrator/root privileges
    
    Returns:
        True if running as admin/root
    """
    try:
        os_type = detect_os()
        
        if os_type == OSType.WINDOWS:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            return os.geteuid() == 0
            
    except Exception as e:
        logger.warning(f"Failed to check admin status: {e}")
        return False


def get_service_executable_path() -> str:
    """
    Get the path to the current executable
    
    Returns:
        Path to current executable
    """
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle
        return sys.executable
    else:
        # Running as Python script
        return sys.argv[0]


def normalize_path(path: str) -> str:
    """
    Normalize a file path for the current platform
    
    Args:
        path: File path to normalize
        
    Returns:
        Normalized path
    """
    return os.path.normpath(os.path.expanduser(path))


def get_available_ports(start_port: int = 1024, end_port: int = 65535, count: int = 5) -> list:
    """
    Get a list of available ports on the system
    
    Args:
        start_port: Starting port number
        end_port: Ending port number
        count: Number of ports to return
        
    Returns:
        List of available port numbers
    """
    import socket
    
    available_ports = []
    
    for port in range(start_port, end_port + 1):
        if len(available_ports) >= count:
            break
            
        try:
            # Test TCP port
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(('localhost', port))
                available_ports.append(port)
                
        except OSError:
            # Port is in use
            continue
    
    return available_ports


def check_port_available(port: int, host: str = 'localhost') -> bool:
    """
    Check if a port is available
    
    Args:
        port: Port number to check
        host: Host to check on
        
    Returns:
        True if port is available
    """
    import socket
    
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
            return True
    except OSError:
        return False


def get_system_resources() -> dict:
    """
    Get system resource information
    
    Returns:
        Dictionary with system resource info
    """
    import psutil
    
    try:
        return {
            "cpu_count": psutil.cpu_count(),
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_total": psutil.virtual_memory().total,
            "memory_available": psutil.virtual_memory().available,
            "memory_percent": psutil.virtual_memory().percent,
            "disk_usage": {
                path: {
                    "total": psutil.disk_usage(path).total,
                    "free": psutil.disk_usage(path).free,
                    "used": psutil.disk_usage(path).used
                }
                for path in ["/"] if detect_os() != OSType.WINDOWS else ["C:\\"]
            }
        }
    except ImportError:
        logger.warning("psutil not available, returning basic info")
        return {
            "cpu_count": os.cpu_count(),
            "memory_info": "psutil required for detailed memory info"
        }
    except Exception as e:
        logger.error(f"Error getting system resources: {e}")
        return {}


__all__ = [
    'OSType',
    'detect_os',
    'get_platform_info',
    'setup_signal_handlers',
    'get_default_config_paths',
    'get_default_data_directory',
    'get_default_log_directory',
    'ensure_directory_exists',
    'is_admin',
    'get_service_executable_path',
    'normalize_path',
    'get_available_ports',
    'check_port_available',
    'get_system_resources'
]
