"""
DICOM File Parser Service

This is the Python equivalent of DICOMFileParser.cpp from the original C++ version.
Parses DICOM files from the filesystem and extracts metadata to store in the database.
"""

import asyncio
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Set
import concurrent.futures
from collections import defaultdict

from pydicom import dcmread, Dataset
from pydicom.errors import InvalidDicomError

from ...core.logging import get_logger
from ...core.database import DatabaseManager
from ...core.config import Settings

logger = get_logger(__name__)


class ParseStatus:
    """Parse status constants matching the C++ version"""
    DISCOVERED = "DSC"
    IN_PROGRESS = "INP" 
    COMPLETED = "OK!"
    ERROR = "ERR"


class DICOMParserService:
    """
    DICOM File Parser Service
    
    Equivalent to the C++ DICOMFileParser namespace. Provides functionality to:
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
            'batch_size': 1000,
            'max_threads': 4,
            'file_extensions': ['.dcm', '.DCM', '.dicom', '.DICOM']
        }
        
        # Statistics
        self.directories_parsed = 0
        self.files_parsed = 0
        self.files_processed = 0
        self.parsing_errors = 0
        
        # Threading and queues
        self.executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self.parsing_tasks: List[asyncio.Task] = []
        
        # Thread-safe data structures for batched database inserts
        self.studies_queue: List[Dataset] = []
        self.series_queue: List[Dataset] = []
        self.images_queue: List[Dataset] = []
        self.queue_lock = threading.Lock()
        
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
                self.config['batch_size'] = 1000
            
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
        
        if self.is_running:
            logger.warning("DICOM Parser already running")
            return True
        
        try:
            self.is_running = True
            
            # Initialize thread pool
            self.executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=self.config['max_threads'],
                thread_name_prefix="DICOMParser"
            )
            
            # Start the parsing operation
            asyncio.create_task(self._run_parsing_operations())
            
            # Start database insertion worker
            asyncio.create_task(self._database_insertion_worker())
            
            logger.info(f"DICOM Parser service started with {self.config['max_threads']} threads")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start DICOM Parser: {e}")
            return False
    
    def stop(self) -> None:
        """Stop the DICOM Parser service"""
        if not self.is_running:
            return
        
        try:
            logger.info("Stopping DICOM Parser service...")
            
            self.is_running = False
            
            # Cancel running tasks
            for task in self.parsing_tasks:
                if not task.done():
                    task.cancel()
            
            # Shutdown thread pool
            if self.executor:
                self.executor.shutdown(wait=True, timeout=30)
                self.executor = None
            
            logger.info("DICOM Parser service stopped")
            
        except Exception as e:
            logger.error(f"Error stopping DICOM Parser: {e}")
    
    async def _run_parsing_operations(self):
        """Run the main parsing operations"""
        try:
            # Get list of files to parse from database or scan directory
            files_to_parse = await self._get_files_to_parse()
            
            if not files_to_parse:
                logger.info("No files to parse found")
                return
            
            logger.info(f"Found {len(files_to_parse)} files to parse")
            
            # Process files in batches
            batch_size = max(1, len(files_to_parse) // self.config['max_threads'])
            
            # Create parsing tasks
            for i in range(0, len(files_to_parse), batch_size):
                batch = files_to_parse[i:i + batch_size]
                task = asyncio.create_task(self._parse_file_batch(batch))
                self.parsing_tasks.append(task)
            
            # Wait for all tasks to complete
            await asyncio.gather(*self.parsing_tasks, return_exceptions=True)
            
            logger.info(f"Parsing operations completed. Processed {self.files_processed} files")
            
        except Exception as e:
            logger.error(f"Error in parsing operations: {e}")
        finally:
            self.is_running = False
    
    async def _get_files_to_parse(self) -> List[Dict[str, Any]]:
        """
        Get list of files to parse from database or directory scan
        
        Returns:
            List of file information dictionaries
        """
        try:
            # First, try to get files from database (migration_files table)
            query = f"SELECT directory_id, id, filename FROM migration_files WHERE parse_status = '{ParseStatus.DISCOVERED}'"
            result = await self.db_manager.execute_query(query)
            
            if result:
                files = []
                for row in result:
                    # Get directory path
                    dir_query = "SELECT directory FROM migration_directories WHERE id = ?"
                    dir_result = await self.db_manager.execute_query(dir_query, (row['directory_id'],))\
n                    \n                    if dir_result:\n                        directory_path = dir_result[0]['directory']\n                        file_path = os.path.join(directory_path, row['filename'])\n                        \n                        files.append({\n                            'file_id': row['id'],\n                            'directory_id': row['directory_id'],\n                            'file_path': file_path\n                        })\n                \n                return files\n            else:\n                # Fall back to directory scanning\n                return await self._scan_directory_for_files()\n                \n        except Exception as e:\n            logger.warning(f\"Error getting files from database, falling back to directory scan: {e}\")\n            return await self._scan_directory_for_files()\n    \n    async def _scan_directory_for_files(self) -> List[Dict[str, Any]]:\n        \"\"\"\n        Scan directory for DICOM files\n        \n        Returns:\n            List of file information dictionaries\n        \"\"\"\n        try:\n            files = []\n            parse_dir = Path(self.config['directory_to_parse'])\n            \n            # Find all DICOM files\n            for ext in self.config['file_extensions']:\n                for file_path in parse_dir.rglob(f\"*{ext}\"):\n                    if file_path.is_file():\n                        files.append({\n                            'file_id': None,  # No database ID\n                            'directory_id': None,\n                            'file_path': str(file_path)\n                        })\n            \n            logger.info(f\"Directory scan found {len(files)} DICOM files\")\n            return files\n            \n        except Exception as e:\n            logger.error(f\"Error scanning directory: {e}\")\n            return []\n    \n    async def _parse_file_batch(self, files: List[Dict[str, Any]]):\n        \"\"\"\n        Parse a batch of files\n        \n        Args:\n            files: List of file information dictionaries\n        \"\"\"\n        try:\n            for file_info in files:\n                if not self.is_running:\n                    break\n                \n                await self._parse_single_file(file_info)\n                \n                # Small delay between files\n                await asyncio.sleep(0.01)\n                \n        except Exception as e:\n            logger.error(f\"Error in file batch parsing: {e}\")\n    \n    async def _parse_single_file(self, file_info: Dict[str, Any]):\n        \"\"\"\n        Parse a single DICOM file\n        \n        Args:\n            file_info: File information dictionary\n        \"\"\"\n        file_path = file_info['file_path']\n        file_id = file_info.get('file_id')\n        \n        try:\n            # Update status to IN_PROGRESS if we have a file ID\n            if file_id:\n                await self.db_manager.execute_query(\n                    f\"UPDATE migration_files SET parse_status = '{ParseStatus.IN_PROGRESS}' WHERE id = ?\",\n                    (file_id,)\n                )\n            \n            # Read DICOM file\n            dataset = dcmread(file_path, stop_before_pixels=True)  # Don't load pixel data\n            \n            if not dataset:\n                raise InvalidDicomError(\"Empty dataset\")\n            \n            # Extract metadata for different levels\n            study_data = self._extract_study_metadata(dataset, file_path)\n            series_data = self._extract_series_metadata(dataset, file_path)\n            image_data = self._extract_image_metadata(dataset, file_path)\n            \n            # Add to queues for batch insertion\n            with self.queue_lock:\n                if study_data:\n                    self.studies_queue.append(study_data)\n                if series_data:\n                    self.series_queue.append(series_data)\n                if image_data:\n                    self.images_queue.append(image_data)\n            \n            # Update status to COMPLETED\n            if file_id:\n                await self.db_manager.execute_query(\n                    f\"UPDATE migration_files SET parse_status = '{ParseStatus.COMPLETED}' WHERE id = ?\",\n                    (file_id,)\n                )\n            \n            self.files_processed += 1\n            logger.debug(f\"Successfully parsed file: {file_path}\")\n            \n        except InvalidDicomError as e:\n            logger.warning(f\"Invalid DICOM file {file_path}: {e}\")\n            self.parsing_errors += 1\n            \n            if file_id:\n                await self.db_manager.execute_query(\n                    f\"UPDATE migration_files SET parse_status = '{ParseStatus.ERROR}' WHERE id = ?\",\n                    (file_id,)\n                )\n                \n        except Exception as e:\n            logger.error(f\"Error parsing file {file_path}: {e}\")\n            self.parsing_errors += 1\n            \n            if file_id:\n                await self.db_manager.execute_query(\n                    f\"UPDATE migration_files SET parse_status = '{ParseStatus.ERROR}' WHERE id = ?\",\n                    (file_id,)\n                )\n    \n    def _extract_study_metadata(self, dataset: Dataset, file_path: str) -> Optional[Dict[str, Any]]:\n        \"\"\"\n        Extract study-level metadata from DICOM dataset\n        \n        Args:\n            dataset: DICOM dataset\n            file_path: Path to the DICOM file\n            \n        Returns:\n            Dictionary with study metadata or None\n        \"\"\"\n        try:\n            # Check if study-level tags are present\n            if not hasattr(dataset, 'StudyInstanceUID'):\n                return None\n            \n            return {\n                'study_instance_uid': str(getattr(dataset, 'StudyInstanceUID', '')),\n                'patient_id': str(getattr(dataset, 'PatientID', '')),\n                'patient_name': str(getattr(dataset, 'PatientName', '')),\n                'patient_birth_date': str(getattr(dataset, 'PatientBirthDate', '')),\n                'patient_sex': str(getattr(dataset, 'PatientSex', '')),\n                'study_date': str(getattr(dataset, 'StudyDate', '')),\n                'study_time': str(getattr(dataset, 'StudyTime', '')),\n                'study_description': str(getattr(dataset, 'StudyDescription', '')),\n                'study_id': str(getattr(dataset, 'StudyID', '')),\n                'accession_number': str(getattr(dataset, 'AccessionNumber', '')),\n                'referring_physician': str(getattr(dataset, 'ReferringPhysicianName', '')),\n                'institution_name': str(getattr(dataset, 'InstitutionName', '')),\n                'study_status': 'PARSED',\n                'parsed_at': datetime.now().isoformat(),\n                'source_file': file_path\n            }\n            \n        except Exception as e:\n            logger.error(f\"Error extracting study metadata: {e}\")\n            return None\n    \n    def _extract_series_metadata(self, dataset: Dataset, file_path: str) -> Optional[Dict[str, Any]]:\n        \"\"\"\n        Extract series-level metadata from DICOM dataset\n        \n        Args:\n            dataset: DICOM dataset\n            file_path: Path to the DICOM file\n            \n        Returns:\n            Dictionary with series metadata or None\n        \"\"\"\n        try:\n            # Check if series-level tags are present\n            if not hasattr(dataset, 'SeriesInstanceUID'):\n                return None\n            \n            return {\n                'series_instance_uid': str(getattr(dataset, 'SeriesInstanceUID', '')),\n                'study_instance_uid': str(getattr(dataset, 'StudyInstanceUID', '')),\n                'series_number': str(getattr(dataset, 'SeriesNumber', '')),\n                'series_description': str(getattr(dataset, 'SeriesDescription', '')),\n                'modality': str(getattr(dataset, 'Modality', '')),\n                'body_part': str(getattr(dataset, 'BodyPartExamined', '')),\n                'protocol_name': str(getattr(dataset, 'ProtocolName', '')),\n                'series_date': str(getattr(dataset, 'SeriesDate', '')),\n                'series_time': str(getattr(dataset, 'SeriesTime', '')),\n                'operator_name': str(getattr(dataset, 'OperatorsName', '')),\n                'performing_physician': str(getattr(dataset, 'PerformingPhysicianName', '')),\n                'parsed_at': datetime.now().isoformat(),\n                'source_file': file_path\n            }\n            \n        except Exception as e:\n            logger.error(f\"Error extracting series metadata: {e}\")\n            return None\n    \n    def _extract_image_metadata(self, dataset: Dataset, file_path: str) -> Optional[Dict[str, Any]]:\n        \"\"\"\n        Extract image-level metadata from DICOM dataset\n        \n        Args:\n            dataset: DICOM dataset\n            file_path: Path to the DICOM file\n            \n        Returns:\n            Dictionary with image metadata or None\n        \"\"\"\n        try:\n            # Check if image-level tags are present\n            if not hasattr(dataset, 'SOPInstanceUID'):\n                return None\n            \n            return {\n                'sop_instance_uid': str(getattr(dataset, 'SOPInstanceUID', '')),\n                'sop_class_uid': str(getattr(dataset, 'SOPClassUID', '')),\n                'series_instance_uid': str(getattr(dataset, 'SeriesInstanceUID', '')),\n                'study_instance_uid': str(getattr(dataset, 'StudyInstanceUID', '')),\n                'instance_number': str(getattr(dataset, 'InstanceNumber', '')),\n                'image_type': str(getattr(dataset, 'ImageType', '')),\n                'acquisition_number': str(getattr(dataset, 'AcquisitionNumber', '')),\n                'acquisition_date': str(getattr(dataset, 'AcquisitionDate', '')),\n                'acquisition_time': str(getattr(dataset, 'AcquisitionTime', '')),\n                'content_date': str(getattr(dataset, 'ContentDate', '')),\n                'content_time': str(getattr(dataset, 'ContentTime', '')),\n                'rows': str(getattr(dataset, 'Rows', '')),\n                'columns': str(getattr(dataset, 'Columns', '')),\n                'bits_allocated': str(getattr(dataset, 'BitsAllocated', '')),\n                'bits_stored': str(getattr(dataset, 'BitsStored', '')),\n                'pixel_spacing': str(getattr(dataset, 'PixelSpacing', '')),\n                'slice_thickness': str(getattr(dataset, 'SliceThickness', '')),\n                'window_center': str(getattr(dataset, 'WindowCenter', '')),\n                'window_width': str(getattr(dataset, 'WindowWidth', '')),\n                'parsed_at': datetime.now().isoformat(),\n                'file_path': file_path,\n                'file_size': os.path.getsize(file_path) if os.path.exists(file_path) else 0\n            }\n            \n        except Exception as e:\n            logger.error(f\"Error extracting image metadata: {e}\")\n            return None\n    \n    async def _database_insertion_worker(self):\n        \"\"\"\n        Background worker to insert parsed data into database in batches\n        \"\"\"\n        try:\n            while self.is_running or any([self.studies_queue, self.series_queue, self.images_queue]):\n                \n                # Process studies queue\n                if self.studies_queue:\n                    with self.queue_lock:\n                        batch = self.studies_queue[:self.config['batch_size']]\n                        self.studies_queue = self.studies_queue[self.config['batch_size']:]\n                    \n                    if batch:\n                        await self._insert_studies_batch(batch)\n                \n                # Process series queue\n                if self.series_queue:\n                    with self.queue_lock:\n                        batch = self.series_queue[:self.config['batch_size']]\n                        self.series_queue = self.series_queue[self.config['batch_size']:]\n                    \n                    if batch:\n                        await self._insert_series_batch(batch)\n                \n                # Process images queue\n                if self.images_queue:\n                    with self.queue_lock:\n                        batch = self.images_queue[:self.config['batch_size']]\n                        self.images_queue = self.images_queue[self.config['batch_size']:]\n                    \n                    if batch:\n                        await self._insert_images_batch(batch)\n                \n                # Wait before next check\n                await asyncio.sleep(1)\n                \n        except Exception as e:\n            logger.error(f\"Error in database insertion worker: {e}\")\n    \n    async def _insert_studies_batch(self, studies: List[Dict[str, Any]]):\n        \"\"\"Insert a batch of studies into database\"\"\"\n        try:\n            for study in studies:\n                query = \"\"\"\n                    INSERT OR REPLACE INTO parsed_studies (\n                        study_instance_uid, patient_id, patient_name, patient_birth_date, patient_sex,\n                        study_date, study_time, study_description, study_id, accession_number,\n                        referring_physician, institution_name, study_status, parsed_at, source_file\n                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n                \"\"\"\n                \n                values = tuple(study.values())\n                await self.db_manager.execute_query(query, values)\n                \n        except Exception as e:\n            logger.error(f\"Error inserting studies batch: {e}\")\n    \n    async def _insert_series_batch(self, series_list: List[Dict[str, Any]]):\n        \"\"\"Insert a batch of series into database\"\"\"\n        try:\n            for series in series_list:\n                query = \"\"\"\n                    INSERT OR REPLACE INTO parsed_series (\n                        series_instance_uid, study_instance_uid, series_number, series_description,\n                        modality, body_part, protocol_name, series_date, series_time,\n                        operator_name, performing_physician, parsed_at, source_file\n                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n                \"\"\"\n                \n                values = tuple(series.values())\n                await self.db_manager.execute_query(query, values)\n                \n        except Exception as e:\n            logger.error(f\"Error inserting series batch: {e}\")\n    \n    async def _insert_images_batch(self, images: List[Dict[str, Any]]):\n        \"\"\"Insert a batch of images into database\"\"\"\n        try:\n            for image in images:\n                query = \"\"\"\n                    INSERT OR REPLACE INTO parsed_images (\n                        sop_instance_uid, sop_class_uid, series_instance_uid, study_instance_uid,\n                        instance_number, image_type, acquisition_number, acquisition_date, acquisition_time,\n                        content_date, content_time, rows, columns, bits_allocated, bits_stored,\n                        pixel_spacing, slice_thickness, window_center, window_width,\n                        parsed_at, file_path, file_size\n                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n                \"\"\"\n                \n                values = tuple(image.values())\n                await self.db_manager.execute_query(query, values)\n                \n        except Exception as e:\n            logger.error(f\"Error inserting images batch: {e}\")\n    \n    def get_statistics(self) -> Dict[str, Any]:\n        \"\"\"\n        Get service statistics\n        \n        Returns:\n            Dictionary containing service statistics\n        \"\"\"\n        return {\n            'is_running': self.is_running,\n            'is_configured': self.is_configured,\n            'directories_parsed': self.directories_parsed,\n            'files_parsed': self.files_parsed,\n            'files_processed': self.files_processed,\n            'parsing_errors': self.parsing_errors,\n            'config': self.config.copy(),\n            'queue_sizes': {\n                'studies': len(self.studies_queue),\n                'series': len(self.series_queue),\n                'images': len(self.images_queue)\n            }\n        }\n    \n    def reset_statistics(self):\n        \"\"\"Reset service statistics\"\"\"\n        self.directories_parsed = 0\n        self.files_parsed = 0\n        self.files_processed = 0\n        self.parsing_errors = 0\n        logger.info(\"DICOM Parser statistics reset\")\n\n\n# Helper functions to create database tables for parsed DICOM data\nasync def create_parser_tables(db_manager: DatabaseManager):\n    \"\"\"\n    Create database tables for parsed DICOM data\n    \n    Args:\n        db_manager: Database manager instance\n    \"\"\"\n    # Create parsed studies table\n    studies_table = \"\"\"\n        CREATE TABLE IF NOT EXISTS parsed_studies (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            study_instance_uid TEXT UNIQUE NOT NULL,\n            patient_id TEXT,\n            patient_name TEXT,\n            patient_birth_date TEXT,\n            patient_sex TEXT,\n            study_date TEXT,\n            study_time TEXT,\n            study_description TEXT,\n            study_id TEXT,\n            accession_number TEXT,\n            referring_physician TEXT,\n            institution_name TEXT,\n            study_status TEXT,\n            parsed_at TEXT,\n            source_file TEXT,\n            created_at DATETIME DEFAULT CURRENT_TIMESTAMP\n        )\n    \"\"\"\n    \n    # Create parsed series table\n    series_table = \"\"\"\n        CREATE TABLE IF NOT EXISTS parsed_series (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            series_instance_uid TEXT UNIQUE NOT NULL,\n            study_instance_uid TEXT,\n            series_number TEXT,\n            series_description TEXT,\n            modality TEXT,\n            body_part TEXT,\n            protocol_name TEXT,\n            series_date TEXT,\n            series_time TEXT,\n            operator_name TEXT,\n            performing_physician TEXT,\n            parsed_at TEXT,\n            source_file TEXT,\n            created_at DATETIME DEFAULT CURRENT_TIMESTAMP\n        )\n    \"\"\"\n    \n    # Create parsed images table\n    images_table = \"\"\"\n        CREATE TABLE IF NOT EXISTS parsed_images (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            sop_instance_uid TEXT UNIQUE NOT NULL,\n            sop_class_uid TEXT,\n            series_instance_uid TEXT,\n            study_instance_uid TEXT,\n            instance_number TEXT,\n            image_type TEXT,\n            acquisition_number TEXT,\n            acquisition_date TEXT,\n            acquisition_time TEXT,\n            content_date TEXT,\n            content_time TEXT,\n            rows TEXT,\n            columns TEXT,\n            bits_allocated TEXT,\n            bits_stored TEXT,\n            pixel_spacing TEXT,\n            slice_thickness TEXT,\n            window_center TEXT,\n            window_width TEXT,\n            parsed_at TEXT,\n            file_path TEXT,\n            file_size INTEGER,\n            created_at DATETIME DEFAULT CURRENT_TIMESTAMP\n        )\n    \"\"\"\n    \n    # Create migration files table for tracking\n    migration_files_table = \"\"\"\n        CREATE TABLE IF NOT EXISTS migration_files (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            directory_id INTEGER,\n            filename TEXT,\n            parse_status TEXT DEFAULT 'DSC',\n            created_at DATETIME DEFAULT CURRENT_TIMESTAMP\n        )\n    \"\"\"\n    \n    # Create migration directories table\n    migration_dirs_table = \"\"\"\n        CREATE TABLE IF NOT EXISTS migration_directories (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            directory TEXT UNIQUE NOT NULL,\n            parsed TEXT DEFAULT 'DSC',\n            created_at DATETIME DEFAULT CURRENT_TIMESTAMP\n        )\n    \"\"\"\n    \n    # Execute table creation queries\n    tables = [\n        studies_table,\n        series_table,\n        images_table,\n        migration_files_table,\n        migration_dirs_table\n    ]\n    \n    for table_query in tables:\n        await db_manager.execute_query(table_query)\n    \n    # Create indexes\n    indexes = [\n        \"CREATE INDEX IF NOT EXISTS idx_parsed_studies_uid ON parsed_studies(study_instance_uid)\",\n        \"CREATE INDEX IF NOT EXISTS idx_parsed_studies_patient ON parsed_studies(patient_id)\",\n        \"CREATE INDEX IF NOT EXISTS idx_parsed_series_uid ON parsed_series(series_instance_uid)\",\n        \"CREATE INDEX IF NOT EXISTS idx_parsed_series_study ON parsed_series(study_instance_uid)\",\n        \"CREATE INDEX IF NOT EXISTS idx_parsed_images_uid ON parsed_images(sop_instance_uid)\",\n        \"CREATE INDEX IF NOT EXISTS idx_parsed_images_series ON parsed_images(series_instance_uid)\",\n        \"CREATE INDEX IF NOT EXISTS idx_migration_files_status ON migration_files(parse_status)\"\n    ]\n    \n    for index_query in indexes:\n        await db_manager.execute_query(index_query)\n\n\n__all__ = ['DICOMParserService', 'ParseStatus', 'create_parser_tables']\n"}}
</function_calls>

Now let me create the platform utilities and continue with the other services:

<function_calls>
<invoke name="run_command">
<parameter name="command">mkdir -p /mnt/4f79e4ad-b75d-46a5-af16-ca1bd092ce07/Archive/MigrationService/utils
