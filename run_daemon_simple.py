#!/usr/bin/env python3
"""
Simple Medical Imaging Migration Service Runner

This script runs the migration service in the foreground with proper
logging and configuration management, suitable for testing.
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
import time
from datetime import datetime

# Add current directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class SimpleMigrationService:
    """Simple Migration Service for testing"""
    
    def __init__(self, config_file: str, service_name: str = "migration_service"):
        self.config_file = config_file
        self.service_name = service_name
        self.running = False
        self.scp_port = None
        self.ae_title = None
        
        # Setup basic logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(f'logs/{service_name}.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(service_name)
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
    
    def load_config(self):
        """Load configuration from file"""
        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
            
            self.scp_port = config['dicom']['scp_port']
            self.ae_title = config['dicom']['our_ae_title']
            storage_dir = config['dicom']['storage_directory']
            
            # Create storage directory if it doesn't exist
            Path(storage_dir).mkdir(parents=True, exist_ok=True)
            
            self.logger.info(f"Configuration loaded: {self.ae_title} on port {self.scp_port}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            return False
    
    async def start_dicom_scp(self):
        """Start a basic DICOM SCP using dcmtk storescp"""
        try:
            # Start storescp in the background
            storage_dir = f"dicom_storage_{self.ae_title.lower()}"
            
            cmd = [
                '/usr/bin/storescp',
                '--verbose',
                '--aetitle', self.ae_title,
                '--output-directory', storage_dir,
                str(self.scp_port)
            ]
            
            self.logger.info(f"Starting DICOM SCP: {' '.join(cmd)}")
            
            # Start the process
            import subprocess
            self.scp_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True
            )
            
            self.logger.info(f"DICOM SCP started with PID {self.scp_process.pid}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start DICOM SCP: {e}")
            return False
    
    async def run(self):
        """Main service loop"""
        if not self.load_config():
            return False
        
        self.logger.info(f"Starting {self.service_name}...")
        
        # Start DICOM SCP
        if not await self.start_dicom_scp():
            return False
        
        self.running = True
        self.logger.info(f"Service {self.service_name} is running")
        
        try:
            while self.running:
                # Check if SCP process is still running
                if hasattr(self, 'scp_process') and self.scp_process.poll() is not None:
                    self.logger.error("DICOM SCP process has terminated")
                    break
                
                # Sleep for a short interval
                await asyncio.sleep(1.0)
                
        except Exception as e:
            self.logger.error(f"Error in main loop: {e}")
        finally:
            await self._cleanup()
        
        return True
    
    async def _cleanup(self):
        """Cleanup resources"""
        try:
            self.logger.info("Cleaning up resources...")
            
            # Stop SCP process
            if hasattr(self, 'scp_process'):
                self.scp_process.terminate()
                try:
                    self.scp_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.scp_process.kill()
                    self.scp_process.wait()
                
                self.logger.info("DICOM SCP process stopped")
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")


async def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='Simple Medical Imaging Migration Service')
    parser.add_argument('--config', '-c', required=True,
                       help='Configuration file path')
    parser.add_argument('--name', '-n', default='migration_service',
                       help='Service name (default: migration_service)')
    
    args = parser.parse_args()
    
    service = SimpleMigrationService(args.config, args.name)
    success = await service.run()
    
    if success:
        print(f"Service {args.name} completed successfully")
    else:
        print(f"Service {args.name} failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
