"""
Platform Utilities

Cross-platform utility functions.
"""

import os
import platform
import signal
from enum import Enum
from typing import Dict, Any


class OSType(Enum):
    """Operating System Type"""
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    UNKNOWN = "unknown"


def detect_os() -> OSType:
    """Detect the current operating system"""
    system = platform.system().lower()
    if system == "windows":
        return OSType.WINDOWS
    elif system == "linux":
        return OSType.LINUX
    elif system == "darwin":
        return OSType.MACOS
    else:
        return OSType.UNKNOWN


def setup_signal_handlers(handler_func):
    """Setup signal handlers for graceful shutdown"""
    try:
        if detect_os() != OSType.WINDOWS:
            # Unix-like systems
            signal.signal(signal.SIGTERM, handler_func)
            signal.signal(signal.SIGINT, handler_func)
        else:
            # Windows
            signal.signal(signal.SIGINT, handler_func)
            signal.signal(signal.SIGBREAK, handler_func)
    except Exception:
        # Fallback - just handle SIGINT
        signal.signal(signal.SIGINT, handler_func)


def get_platform_info() -> Dict[str, Any]:
    """Get platform information"""
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version()
    }


def get_system_resources() -> Dict[str, Any]:
    """Get basic system resource information"""
    # Basic stub - can be enhanced with psutil
    return {
        "cpu_count": os.cpu_count(),
        "load_average": os.getloadavg() if hasattr(os, 'getloadavg') else None
    }


__all__ = ['OSType', 'detect_os', 'setup_signal_handlers', 'get_platform_info', 'get_system_resources']
