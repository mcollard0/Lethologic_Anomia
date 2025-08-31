"""
DICOM File Parser Service

Parses DICOM files from the filesystem and extracts metadata to store in the database.
"""

import asyncio
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
import concurrent.futures

from pydicom import dcmread, Dataset
from pydicom.errors import InvalidDicomError

from ...core.logging import get_logger
from ...core.database import DatabaseManager
from ...core.config import Settings

logger = get_logger(__name__)


class ParseStatus:
    """Parse status constants"""
    DISCOVERED = "DSC"
    IN_PROGRESS = "INP" 
    COMPLETED = "OK!"
    ERROR = "ERR"


class DICOMParserService:
    """
    DICOM File Parser Service
    
    Provides functionality to:
    - Parse DICOM files from filesystem directories
    - Extract metadata and store in database
    - Handle multiple threads for improved performance
    - Track parsing progress and status
    """
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        """
        Initialize DICOM Parser service
        
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
            'directory_to_parse': '.',
            'batch_size': 100,
            'max_threads': 4,
            'file_extensions': ['.dcm', '.DCM', '.dicom', '.DICOM']
        }
        
        # Statistics
        self.directories_parsed = 0
        self.files_parsed = 0
        self.files_processed = 0
        self.parsing_errors = 0
        
        logger.info("DICOM Parser Service initialized")
    
    def configure(self, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Configure the DICOM Parser service
        
        Args:
            config: Configuration dictionary with parser parameters
            
        Returns:
            True if configuration successful, False otherwise
        """
        try:
            if config:
                self.config.update(config)
            
            # Validate directory path
            parse_dir = Path(self.config['directory_to_parse'])
            if not parse_dir.exists():
                logger.error(f"Directory to parse does not exist: {parse_dir}")
                return False
            
            if not parse_dir.is_dir():
                logger.error(f"Path is not a directory: {parse_dir}")
                return False
            
            # Validate numeric parameters
            if self.config['batch_size'] <= 0:
                self.config['batch_size'] = 100
            
            if self.config['max_threads'] <= 0:
                self.config['max_threads'] = 4
            
            self.is_configured = True
            logger.info(f"DICOM Parser configured: Directory={self.config['directory_to_parse']}, Batch={self.config['batch_size']}, Threads={self.config['max_threads']}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to configure DICOM Parser: {e}")
            return False
    
    def start(self) -> bool:
        """
        Start the DICOM Parser service
        
        Returns:
            True if started successfully, False otherwise
        """
        if not self.is_configured:
            logger.error("DICOM Parser not configured. Call configure() first.")
            return False
        
        try:
            self.is_running = True            
            logger.info(f"DICOM Parser service started")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start DICOM Parser: {e}")
            return False
    
    def stop(self) -> None:
        """Stop the DICOM Parser service"""
        self.is_running = False
        logger.info("DICOM Parser service stopped")
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get service statistics
        
        Returns:
            Dictionary containing service statistics
        """
        return {
            'is_running': self.is_running,
            'is_configured': self.is_configured,
            'directories_parsed': self.directories_parsed,
            'files_parsed': self.files_parsed,
            'files_processed': self.files_processed,
            'parsing_errors': self.parsing_errors,
            'config': self.config.copy()
        }
    
    def reset_statistics(self):
        """Reset service statistics"""
        self.directories_parsed = 0
        self.files_parsed = 0
        self.files_processed = 0
        self.parsing_errors = 0
        logger.info("DICOM Parser statistics reset")


__all__ = ['DICOMParserService', 'ParseStatus']
