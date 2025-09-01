#!/usr/bin/env python3
"""
Medical Imaging Migration Service Daemon Startup Script

This script starts the migration service as a background daemon with proper
logging, configuration management, and process control.
"""

import asyncio
import os
import sys
import signal
import argparse
import json
import logging
from pathlib import Path
from typing import Optional
import subprocess
import time
from datetime import datetime

# Add current directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import Settings
from core.database import DatabaseManager
from core.process_manager import ProcessManager
from core.custom_logging import setup_logging


class MigrationServiceDaemon:
    """Medical Imaging Migration Service Daemon"""
    
    def __init__(self, config_file: str, daemon_name: str = "migration_service"):
        self.config_file = config_file
        self.daemon_name = daemon_name
        self.pid_file = f"/tmp/{daemon_name}.pid"
        self.log_file = f"logs/{daemon_name}.log"
        self.process_manager: Optional[ProcessManager] = None
        self.settings: Optional[Settings] = None
        self.running = False
        
        # Setup logging
        os.makedirs("logs", exist_ok=True)
        setup_logging(log_file=self.log_file, log_level="INFO")
        self.logger = get_logger(f"{daemon_name}_daemon")
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
    
    async def initialize(self):
        """Initialize the daemon"""
        try:
            # Load settings from config file
            self.settings = Settings(config_file=self.config_file)
            
            # Initialize process manager
            self.process_manager = ProcessManager(self.settings)
            await self.process_manager.initialize()
            
            # Start DICOM SCP service
            await self._start_dicom_services()
            
            self.logger.info(f"Daemon {self.daemon_name} initialized successfully")
            self.logger.info(f"DICOM AE Title: {self.settings.dicom.our_ae_title}")
            self.logger.info(f"DICOM SCP Port: {self.settings.dicom.scp_port}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize daemon: {e}")
            return False
    
    async def _start_dicom_services(self):
        """Start DICOM services"""
        try:
            # Import DICOM services
            from services.dicom.scp import DICOMSCPService, create_dicom_tables
            
            # Ensure database tables exist
            await create_dicom_tables(self.process_manager.db_manager)
            
            # Create and configure SCP service
            self.scp_service = DICOMSCPService(
                self.process_manager.db_manager, 
                self.settings
            )
            
            scp_config = {
                'port': self.settings.dicom.scp_port,
                'ae_title': self.settings.dicom.our_ae_title,
                'output_directory': self.settings.dicom.storage_directory,
                'max_pdu': self.settings.dicom.max_pdu,
                'acse_timeout': self.settings.dicom.acse_timeout,
                'dimse_timeout': self.settings.dicom.dimse_timeout,
                'socket_timeout': self.settings.dicom.socket_timeout
            }
            
            if self.scp_service.configure(scp_config):
                if self.scp_service.start():
                    self.logger.info(f"DICOM SCP service started on port {self.settings.dicom.scp_port}")
                else:
                    self.logger.error("Failed to start DICOM SCP service")
            else:
                self.logger.error("Failed to configure DICOM SCP service")
                
        except Exception as e:
            self.logger.error(f"Error starting DICOM services: {e}")
    
    async def run(self):
        """Main daemon loop"""
        self.running = True
        self.logger.info(f"Daemon {self.daemon_name} starting main loop...")
        
        try:
            while self.running:
                # Perform periodic maintenance tasks
                await self._maintenance_tasks()
                
                # Sleep for a short interval
                await asyncio.sleep(1.0)
                
        except Exception as e:
            self.logger.error(f"Error in main daemon loop: {e}")
        finally:
            await self._cleanup()
    
    async def _maintenance_tasks(self):
        """Perform periodic maintenance tasks"""
        # This could include:
        # - Database cleanup
        # - Log rotation
        # - Health checks
        # - Statistics updates
        pass
    
    async def _cleanup(self):
        """Cleanup resources"""
        try:
            self.logger.info("Cleaning up daemon resources...")
            
            # Stop DICOM services
            if hasattr(self, 'scp_service'):
                self.scp_service.stop()
            
            # Close process manager
            if self.process_manager:
                await self.process_manager.cleanup()
            
            # Remove PID file
            if os.path.exists(self.pid_file):
                os.remove(self.pid_file)
                
            self.logger.info("Daemon cleanup completed")
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
    
    def write_pid_file(self):
        """Write PID to file"""
        try:
            with open(self.pid_file, 'w') as f:
                f.write(str(os.getpid()))
            self.logger.info(f"PID {os.getpid()} written to {self.pid_file}")
        except Exception as e:
            self.logger.error(f"Failed to write PID file: {e}")
    
    def is_running(self) -> bool:
        """Check if daemon is already running"""
        try:
            if os.path.exists(self.pid_file):
                with open(self.pid_file, 'r') as f:
                    pid = int(f.read().strip())
                
                # Check if process is still running
                try:
                    os.kill(pid, 0)
                    return True
                except OSError:
                    # Process not running, remove stale PID file
                    os.remove(self.pid_file)
                    return False
            return False
        except Exception:
            return False
    
    def get_status(self) -> dict:
        """Get daemon status"""
        status = {
            'daemon_name': self.daemon_name,
            'config_file': self.config_file,
            'running': self.is_running(),
            'pid': None,
            'log_file': self.log_file
        }
        
        if status['running'] and os.path.exists(self.pid_file):
            try:
                with open(self.pid_file, 'r') as f:
                    status['pid'] = int(f.read().strip())
            except:
                pass
        
        return status


def start_daemon(config_file: str, daemon_name: str):
    """Start the daemon"""
    daemon = MigrationServiceDaemon(config_file, daemon_name)
    
    if daemon.is_running():
        print(f"Daemon {daemon_name} is already running")
        return False
    
    print(f"Starting daemon {daemon_name}...")
    
    # Fork to background
    if os.fork() > 0:
        # Parent process exits
        return True
    
    # Child process continues
    os.setsid()  # Create new session
    
    if os.fork() > 0:
        # First child exits
        sys.exit(0)
    
    # Second child (daemon) continues
    os.chdir('/')
    os.umask(0)
    
    # Redirect standard file descriptors
    with open('/dev/null', 'r') as dev_null:
        os.dup2(dev_null.fileno(), sys.stdin.fileno())
    
    with open(daemon.log_file, 'a') as log_file:
        os.dup2(log_file.fileno(), sys.stdout.fileno())
        os.dup2(log_file.fileno(), sys.stderr.fileno())
    
    # Write PID file
    daemon.write_pid_file()
    
    # Run the daemon
    async def run_daemon():
        if await daemon.initialize():
            await daemon.run()
        else:
            print(f"Failed to initialize daemon {daemon_name}")
            sys.exit(1)
    
    asyncio.run(run_daemon())
    return True


def stop_daemon(daemon_name: str):
    """Stop the daemon"""
    pid_file = f"/tmp/{daemon_name}.pid"
    
    if not os.path.exists(pid_file):
        print(f"Daemon {daemon_name} is not running (no PID file)")
        return False
    
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        
        print(f"Stopping daemon {daemon_name} (PID: {pid})...")
        
        # Send TERM signal
        os.kill(pid, signal.SIGTERM)
        
        # Wait for process to terminate
        for _ in range(30):  # Wait up to 30 seconds
            try:
                os.kill(pid, 0)
                time.sleep(1)
            except OSError:
                break
        else:
            # Force kill if still running
            print(f"Force killing daemon {daemon_name}...")
            os.kill(pid, signal.SIGKILL)
        
        # Remove PID file
        if os.path.exists(pid_file):
            os.remove(pid_file)
        
        print(f"Daemon {daemon_name} stopped")
        return True
        
    except Exception as e:
        print(f"Error stopping daemon {daemon_name}: {e}")
        return False


def status_daemon(daemon_name: str):
    """Get daemon status"""
    daemon = MigrationServiceDaemon("", daemon_name)
    status = daemon.get_status()
    
    print(f"Daemon Status: {daemon_name}")
    print(f"Running: {'Yes' if status['running'] else 'No'}")
    if status['pid']:
        print(f"PID: {status['pid']}")
    print(f"Log File: {status['log_file']}")
    
    return status['running']


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='Medical Imaging Migration Service Daemon')
    parser.add_argument('action', choices=['start', 'stop', 'status', 'restart'],
                       help='Daemon action')
    parser.add_argument('--config', '-c', required=True,
                       help='Configuration file path')
    parser.add_argument('--name', '-n', default='migration_service',
                       help='Daemon name (default: migration_service)')
    
    args = parser.parse_args()
    
    if args.action == 'start':
        if start_daemon(args.config, args.name):
            print(f"Daemon {args.name} started successfully")
        else:
            print(f"Failed to start daemon {args.name}")
            sys.exit(1)
    
    elif args.action == 'stop':
        if stop_daemon(args.name):
            print(f"Daemon {args.name} stopped successfully")
        else:
            print(f"Failed to stop daemon {args.name}")
            sys.exit(1)
    
    elif args.action == 'status':
        if status_daemon(args.name):
            print(f"Daemon {args.name} is running")
        else:
            print(f"Daemon {args.name} is not running")
    
    elif args.action == 'restart':
        print(f"Restarting daemon {args.name}...")
        stop_daemon(args.name)
        time.sleep(2)
        if start_daemon(args.config, args.name):
            print(f"Daemon {args.name} restarted successfully")
        else:
            print(f"Failed to restart daemon {args.name}")
            sys.exit(1)


if __name__ == "__main__":
    main()
