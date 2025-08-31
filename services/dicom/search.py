"""
DICOM Search Service

Implements multi-threaded DICOM study discovery and search operations.
"""

import asyncio
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import concurrent.futures

from pynetdicom import AE
from pynetdicom.sop_class import *
from pydicom import Dataset

from ...core.logging import get_logger
from ...core.database import DatabaseManager
from ...core.config import Settings

logger = get_logger(__name__)


class DICOMSearchService:
    """
    DICOM Search Service (Multi-threaded)
    
    Provides functionality to:
    - Search for studies across multiple days/date ranges
    - Perform multi-threaded queries for improved performance
    - Store discovered studies for later processing
    """
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        """
        Initialize DICOM Search service
        
        Args:
            db_manager: Database manager instance
            settings: Application settings
        """
        self.db_manager = db_manager
        self.settings = settings
        
        # Configuration
        self.is_configured = False
        self.is_running = False
        
        # Default configuration
        self.config = {
            'our_ae_title': 'MIGRATIONSERVICE',
            'peer_ae_title': '',
            'peer_ip': '',
            'peer_port': 104,
            'years_back': 30,
            'max_threads': 8,
            'watch_mode': True,
            'max_pdu': 65536
        }
        
        # Statistics
        self.studies_discovered = 0
        self.queries_performed = 0
        self.errors_occurred = 0
        
        # Threading
        self.executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self.running_tasks: List[asyncio.Task] = []
        
        logger.info("DICOM Search Service initialized")
    
    def configure(self, config: Dict[str, Any]) -> bool:
        """
        Configure the DICOM Search service
        
        Args:
            config: Configuration dictionary with search parameters
            
        Returns:
            True if configuration successful, False otherwise
        """
        try:
            # Update configuration with provided values
            self.config.update(config)
            
            # Validate required parameters
            if not self.config['peer_ip']:
                logger.error("Peer IP address is required")
                return False
            
            if not self.config['peer_ae_title']:
                logger.error("Peer AE Title is required")
                return False
            
            # Validate numeric parameters
            if self.config['peer_port'] <= 0:
                logger.error(f"Invalid peer port: {self.config['peer_port']}")
                return False
            
            if self.config['years_back'] <= 0:
                logger.error(f"Invalid years_back: {self.config['years_back']}")
                return False
            
            if self.config['max_threads'] <= 0:
                self.config['max_threads'] = 1
            
            self.is_configured = True
            logger.info(f"DICOM Search configured: Peer={self.config['peer_ip']}:{self.config['peer_port']} (AE={self.config['peer_ae_title']}), Years={self.config['years_back']}, Threads={self.config['max_threads']}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to configure DICOM Search: {e}")
            return False
    
    def start(self) -> bool:
        """
        Start the DICOM Search service
        
        Returns:
            True if started successfully, False otherwise
        """
        if not self.is_configured:
            logger.error("DICOM Search not configured. Call configure() first.")
            return False
        
        if self.is_running:
            logger.warning("DICOM Search already running")
            return True
        
        try:
            self.is_running = True
            
            # Initialize thread pool
            self.executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=self.config['max_threads'],
                thread_name_prefix="DICOMSearch"
            )
            
            # Start the search operation
            asyncio.create_task(self._run_search_operations())
            
            logger.info(f"DICOM Search service started with {self.config['max_threads']} threads")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start DICOM Search: {e}")
            return False
    
    def stop(self) -> None:
        """Stop the DICOM Search service"""
        if not self.is_running:
            return
        
        try:
            logger.info("Stopping DICOM Search service...")
            
            self.is_running = False
            
            # Cancel running tasks
            for task in self.running_tasks:
                if not task.done():
                    task.cancel()
            
            # Shutdown thread pool
            if self.executor:
                self.executor.shutdown(wait=True, timeout=30)
                self.executor = None
            
            logger.info("DICOM Search service stopped")
            
        except Exception as e:
            logger.error(f"Error stopping DICOM Search: {e}")
    
    def is_running_status(self) -> bool:
        """Check if service is running"""
        return self.is_running


# Helper function to create database table for discovered studies
async def create_discovered_studies_table(db_manager: DatabaseManager):
    """
    Create database table for discovered studies
    
    Args:
        db_manager: Database manager instance
    """
    create_table_query = """
        CREATE TABLE IF NOT EXISTS discovered_studies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_instance_uid TEXT UNIQUE NOT NULL,
            patient_id TEXT,
            patient_name TEXT,
            study_date TEXT,
            study_time TEXT,
            study_description TEXT,
            study_id TEXT,
            accession_number TEXT,
            modality TEXT,
            number_of_series TEXT,
            number_of_instances TEXT,
            discovered_at TEXT,
            processed_at TEXT,
            search_date TEXT,
            source_ae TEXT,
            source_ip TEXT,
            status TEXT DEFAULT 'DISCOVERED',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """
    
    await db_manager.execute_query(create_table_query)
    
    # Create indexes
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_discovered_study_uid ON discovered_studies(study_instance_uid)",
        "CREATE INDEX IF NOT EXISTS idx_discovered_patient_id ON discovered_studies(patient_id)",
        "CREATE INDEX IF NOT EXISTS idx_discovered_date ON discovered_studies(study_date)",
        "CREATE INDEX IF NOT EXISTS idx_discovered_status ON discovered_studies(status)"
    ]
    
    for index_query in indexes:
        await db_manager.execute_query(index_query)


__all__ = ['DICOMSearchService', 'create_discovered_studies_table']
