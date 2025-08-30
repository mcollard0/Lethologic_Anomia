"""
DICOM SCU Service

This is the Python equivalent of DICOMSCU.cpp from the original C++ version.
Implements a DICOM Service Class User (SCU) that can perform:
- C-FIND: Search for studies, series, and images
- C-STORE: Send DICOM images to other systems
- C-MOVE: Request images to be moved from remote systems
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, Callable
import uuid

from pynetdicom import AE, debug_logger
from pynetdicom.sop_class import *
from pydicom import Dataset
from pydicom.uid import generate_uid

from ...core.logging import get_logger
from ...core.database import DatabaseManager
from ...core.config import Settings

logger = get_logger(__name__)


class DICOMSCUService:
    """
    DICOM Service Class User (SCU) Service
    
    Equivalent to the C++ DICOMSCU class. Provides functionality to:
    - Connect to remote DICOM servers
    - Perform C-FIND operations (search)
    - Perform C-STORE operations (send)
    - Perform C-MOVE operations (retrieve)
    """
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        """
        Initialize DICOM SCU service
        
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
            'ae_title': 'MIGRATIONSERVICE',
            'target_ip': '',
            'target_port': 104,
            'target_ae_title': '',
            'max_pdu': 65536,
            'acse_timeout': 30,
            'dimse_timeout': 30,
            'network_timeout': 60
        }
        
        # Statistics
        self.queries_performed = 0
        self.images_sent = 0
        self.images_retrieved = 0
        self.errors_occurred = 0
        
        # Application Entity
        self.ae: Optional[AE] = None
        
        logger.info("DICOM SCU Service initialized")
    
    def configure(self, config: Dict[str, Any]) -> bool:
        """
        Configure the DICOM SCU service
        
        Args:
            config: Configuration dictionary with SCU parameters
            
        Returns:
            True if configuration successful, False otherwise
        """
        try:
            # Update configuration with provided values
            self.config.update(config)
            
            # Validate required parameters
            if not self.config['target_ip']:
                logger.error("Target IP address is required")
                return False
            
            if not isinstance(self.config['target_port'], int) or self.config['target_port'] <= 0:
                logger.error(f"Invalid target port: {self.config['target_port']}")
                return False
            
            if not self.config['target_ae_title']:
                logger.error("Target AE Title is required")
                return False
            
            # Initialize Application Entity
            self.ae = AE(ae_title=self.config['ae_title'])
            
            # Add supported query/retrieve SOP classes
            self._add_supported_contexts()
            
            # Configure network options
            self.ae.maximum_pdu_size = self.config['max_pdu']
            self.ae.acse_timeout = self.config['acse_timeout']
            self.ae.dimse_timeout = self.config['dimse_timeout']
            self.ae.network_timeout = self.config['network_timeout']
            
            self.is_configured = True
            logger.info(f"DICOM SCU configured: Target={self.config['target_ip']}:{self.config['target_port']} (AE={self.config['target_ae_title']})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to configure DICOM SCU: {e}")
            return False
    
    def _add_supported_contexts(self):
        """Add supported presentation contexts for SCU operations"""
        
        # Query/Retrieve contexts
        query_retrieve_contexts = [
            PatientRootQueryRetrieveInformationModelFind,
            PatientRootQueryRetrieveInformationModelMove,
            StudyRootQueryRetrieveInformationModelFind,
            StudyRootQueryRetrieveInformationModelMove,
            PatientStudyOnlyQueryRetrieveInformationModelFind,
            PatientStudyOnlyQueryRetrieveInformationModelMove
        ]
        
        for context in query_retrieve_contexts:
            self.ae.add_requested_context(context)
        
        # Storage contexts (for C-STORE)
        storage_contexts = [
            ComputedRadiographyImageStorage,
            CTImageStorage,
            EnhancedCTImageStorage,
            MRImageStorage,
            EnhancedMRImageStorage,
            UltrasoundImageStorage,
            UltrasoundMultiframeImageStorage,
            SecondaryCaptureImageStorage,
            XRayAngiographicImageStorage,
            XRayRadiofluoroscopicImageStorage,
            NuclearMedicineImageStorage,
            PositronEmissionTomographyImageStorage,
            RTImageStorage,
            RTDoseStorage,
            RTStructureSetStorage,
            RTPlanStorage
        ]
        
        for context in storage_contexts:
            self.ae.add_requested_context(context)
    
    def configured(self) -> bool:
        """Check if SCU is configured"""
        return self.is_configured
    
    def start(self) -> bool:
        """
        Start the DICOM SCU service
        
        Returns:
            True if started successfully, False otherwise
        """
        if not self.is_configured:
            logger.error("DICOM SCU not configured. Call configure() first.")
            return False
        
        try:
            self.is_running = True
            logger.info(f"DICOM SCU service started and ready for operations")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start DICOM SCU: {e}")
            return False
    
    def stop(self) -> bool:
        """
        Stop the DICOM SCU service
        
        Returns:
            True if stopped successfully, False otherwise
        """
        try:
            self.is_running = False
            logger.info("DICOM SCU service stopped")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping DICOM SCU: {e}")
            return False
    
    async def find_studies(
        self, 
        patient_id: Optional[str] = None,
        study_date: Optional[str] = None,
        modality: Optional[str] = None,
        study_description: Optional[str] = None
    ) -> List[Dataset]:
        """
        Perform C-FIND operation to search for studies
        
        Args:
            patient_id: Patient ID to search for
            study_date: Study date (YYYYMMDD format)
            modality: Modality to search for
            study_description: Study description pattern
            
        Returns:
            List of found study datasets
        """
        if not self.is_configured:
            logger.error("SCU not configured")
            return []
        
        try:
            # Create query dataset
            ds = Dataset()
            ds.QueryRetrieveLevel = 'STUDY'
            
            # Add search criteria
            ds.PatientID = patient_id or ''
            ds.StudyDate = study_date or ''
            ds.Modality = modality or ''
            ds.StudyDescription = study_description or ''
            
            # Required return attributes
            ds.StudyInstanceUID = ''
            ds.PatientName = ''
            ds.StudyID = ''
            ds.StudyTime = ''
            ds.AccessionNumber = ''
            ds.NumberOfStudyRelatedSeries = ''
            ds.NumberOfStudyRelatedInstances = ''
            
            # Perform C-FIND
            assoc = self.ae.associate(
                self.config['target_ip'],
                self.config['target_port'],
                ae_title=self.config['target_ae_title']
            )
            
            if assoc.is_established:
                logger.info("Association established for C-FIND")
                
                responses = assoc.send_c_find(
                    ds,
                    StudyRootQueryRetrieveInformationModelFind
                )
                
                results = []
                for status, identifier in responses:
                    if status.Status == 0xFF00:  # Pending
                        if identifier:
                            results.append(identifier)
                    elif status.Status == 0x0000:  # Success
                        break
                    else:
                        logger.warning(f"C-FIND failed with status: {status}")
                        break
                
                assoc.release()
                
                self.queries_performed += 1
                logger.info(f"C-FIND completed: {len(results)} studies found")
                
                # Store query results in database
                await self._store_query_results(results, 'STUDY')
                
                return results
            else:
                logger.error("Failed to establish association for C-FIND")
                return []
                
        except Exception as e:
            logger.error(f"Error during C-FIND: {e}")
            self.errors_occurred += 1
            return []
    
    async def find_series(self, study_instance_uid: str) -> List[Dataset]:
        """
        Perform C-FIND operation to search for series within a study
        
        Args:
            study_instance_uid: Study instance UID to search within
            
        Returns:
            List of found series datasets
        """
        if not self.is_configured:
            logger.error("SCU not configured")
            return []
        
        try:
            # Create query dataset
            ds = Dataset()
            ds.QueryRetrieveLevel = 'SERIES'
            ds.StudyInstanceUID = study_instance_uid
            
            # Required return attributes
            ds.SeriesInstanceUID = ''
            ds.SeriesNumber = ''
            ds.SeriesDescription = ''
            ds.Modality = ''
            ds.NumberOfSeriesRelatedInstances = ''
            
            # Perform C-FIND
            assoc = self.ae.associate(
                self.config['target_ip'],
                self.config['target_port'],
                ae_title=self.config['target_ae_title']
            )
            
            if assoc.is_established:
                responses = assoc.send_c_find(
                    ds,
                    StudyRootQueryRetrieveInformationModelFind
                )
                
                results = []
                for status, identifier in responses:
                    if status.Status == 0xFF00:  # Pending
                        if identifier:
                            results.append(identifier)
                    elif status.Status == 0x0000:  # Success
                        break
                
                assoc.release()
                
                logger.info(f"C-FIND series completed: {len(results)} series found")
                await self._store_query_results(results, 'SERIES')
                
                return results
            else:
                logger.error("Failed to establish association for series C-FIND")
                return []
                
        except Exception as e:
            logger.error(f"Error during series C-FIND: {e}")
            self.errors_occurred += 1
            return []
    
    async def store_image(self, file_path: str, target_ip: Optional[str] = None, 
                         target_port: Optional[int] = None, target_ae: Optional[str] = None) -> bool:
        """
        Perform C-STORE operation to send a DICOM image
        
        Args:
            file_path: Path to DICOM file to send
            target_ip: Override target IP
            target_port: Override target port  
            target_ae: Override target AE title
            
        Returns:
            True if store successful, False otherwise
        """
        if not self.is_configured:
            logger.error("SCU not configured")
            return False
        
        # Use provided targets or fall back to configured ones
        ip = target_ip or self.config['target_ip']
        port = target_port or self.config['target_port']
        ae_title = target_ae or self.config['target_ae_title']
        
        try:
            # Read DICOM file
            ds = dcmread(file_path)
            
            # Establish association
            assoc = self.ae.associate(ip, port, ae_title=ae_title)
            
            if assoc.is_established:
                logger.debug(f"Association established for C-STORE to {ip}:{port}")
                
                # Send C-STORE
                status = assoc.send_c_store(ds)
                
                if status.Status == 0x0000:  # Success
                    logger.info(f"C-STORE successful for file: {file_path}")
                    self.images_sent += 1
                    result = True
                else:
                    logger.error(f"C-STORE failed with status: {status}")
                    self.errors_occurred += 1
                    result = False
                
                assoc.release()
                return result
            else:
                logger.error(f"Failed to establish association for C-STORE to {ip}:{port}")
                self.errors_occurred += 1
                return False
                
        except Exception as e:
            logger.error(f"Error during C-STORE: {e}")
            self.errors_occurred += 1
            return False
    
    async def move_study(self, study_instance_uid: str, destination_ae: str) -> bool:
        """
        Perform C-MOVE operation to retrieve a study
        
        Args:
            study_instance_uid: Study instance UID to retrieve
            destination_ae: AE title where images should be sent
            
        Returns:
            True if move initiated successfully, False otherwise
        """
        if not self.is_configured:
            logger.error("SCU not configured")
            return False
        
        try:
            # Create move dataset
            ds = Dataset()
            ds.QueryRetrieveLevel = 'STUDY'
            ds.StudyInstanceUID = study_instance_uid
            
            # Establish association
            assoc = self.ae.associate(
                self.config['target_ip'],
                self.config['target_port'],
                ae_title=self.config['target_ae_title']
            )
            
            if assoc.is_established:
                logger.info(f"Association established for C-MOVE")
                
                # Send C-MOVE request
                responses = assoc.send_c_move(
                    ds,
                    destination_ae,
                    StudyRootQueryRetrieveInformationModelMove
                )
                
                success = False
                for status, identifier in responses:
                    if status.Status == 0xFF00:  # Pending
                        logger.debug(f"C-MOVE pending: {status}")
                    elif status.Status == 0x0000:  # Success
                        logger.info(f"C-MOVE completed successfully")
                        success = True
                        break
                    else:
                        logger.error(f"C-MOVE failed with status: {status}")
                        break
                
                assoc.release()
                
                if success:
                    self.images_retrieved += 1
                else:
                    self.errors_occurred += 1
                
                return success
            else:
                logger.error("Failed to establish association for C-MOVE")
                self.errors_occurred += 1
                return False
                
        except Exception as e:
            logger.error(f"Error during C-MOVE: {e}")
            self.errors_occurred += 1
            return False
    
    async def move_series(self, study_instance_uid: str, series_instance_uid: str, 
                         destination_ae: str) -> bool:
        """
        Perform C-MOVE operation to retrieve a series
        
        Args:
            study_instance_uid: Study instance UID
            series_instance_uid: Series instance UID to retrieve
            destination_ae: AE title where images should be sent
            
        Returns:
            True if move initiated successfully, False otherwise
        """
        try:
            # Create move dataset
            ds = Dataset()
            ds.QueryRetrieveLevel = 'SERIES'
            ds.StudyInstanceUID = study_instance_uid
            ds.SeriesInstanceUID = series_instance_uid
            
            # Establish association
            assoc = self.ae.associate(
                self.config['target_ip'],
                self.config['target_port'],
                ae_title=self.config['target_ae_title']
            )
            
            if assoc.is_established:
                # Send C-MOVE request
                responses = assoc.send_c_move(
                    ds,
                    destination_ae,
                    StudyRootQueryRetrieveInformationModelMove
                )
                
                success = False
                for status, identifier in responses:
                    if status.Status == 0x0000:  # Success
                        success = True
                        break
                    elif status.Status != 0xFF00:  # Not pending
                        logger.error(f"C-MOVE series failed: {status}")
                        break
                
                assoc.release()
                return success
            else:
                logger.error("Failed to establish association for series C-MOVE")
                return False
                
        except Exception as e:
            logger.error(f"Error during series C-MOVE: {e}")
            return False
    
    async def verify_connection(self) -> bool:
        """
        Verify connection to target DICOM server using C-ECHO
        
        Returns:
            True if connection successful, False otherwise
        """
        if not self.is_configured:
            logger.error("SCU not configured")
            return False
        
        try:
            # Add verification context
            if VerificationSOPClass not in [ctx.abstract_syntax for ctx in self.ae.requested_contexts]:
                self.ae.add_requested_context(VerificationSOPClass)
            
            # Establish association
            assoc = self.ae.associate(
                self.config['target_ip'],
                self.config['target_port'],
                ae_title=self.config['target_ae_title']
            )
            
            if assoc.is_established:
                # Send C-ECHO
                status = assoc.send_c_echo()
                
                if status.Status == 0x0000:
                    logger.info(f"C-ECHO successful to {self.config['target_ip']}:{self.config['target_port']}")
                    result = True
                else:
                    logger.error(f"C-ECHO failed with status: {status}")
                    result = False
                
                assoc.release()
                return result
            else:
                logger.error(f"Failed to establish association for C-ECHO")
                return False
                
        except Exception as e:
            logger.error(f"Error during C-ECHO: {e}")
            return False
    
    async def _store_query_results(self, results: List[Dataset], level: str):
        """
        Store query results in database
        
        Args:
            results: List of DICOM datasets from query
            level: Query level (STUDY, SERIES, IMAGE)
        """
        try:
            for ds in results:
                metadata = {
                    'query_level': level,
                    'study_instance_uid': str(getattr(ds, 'StudyInstanceUID', '')),
                    'series_instance_uid': str(getattr(ds, 'SeriesInstanceUID', '')),
                    'sop_instance_uid': str(getattr(ds, 'SOPInstanceUID', '')),
                    'patient_id': str(getattr(ds, 'PatientID', '')),
                    'patient_name': str(getattr(ds, 'PatientName', '')),
                    'study_date': str(getattr(ds, 'StudyDate', '')),
                    'study_time': str(getattr(ds, 'StudyTime', '')),
                    'modality': str(getattr(ds, 'Modality', '')),
                    'study_description': str(getattr(ds, 'StudyDescription', '')),
                    'series_description': str(getattr(ds, 'SeriesDescription', '')),
                    'number_of_instances': str(getattr(ds, 'NumberOfStudyRelatedInstances', '') or 
                                             getattr(ds, 'NumberOfSeriesRelatedInstances', '')),
                    'queried_at': datetime.now().isoformat(),
                    'source_ae': self.config['target_ae_title'],
                    'source_ip': self.config['target_ip']
                }
                
                # Insert into database
                query = """
                    INSERT OR REPLACE INTO dicom_query_results (
                        query_level, study_instance_uid, series_instance_uid, sop_instance_uid,
                        patient_id, patient_name, study_date, study_time, modality,
                        study_description, series_description, number_of_instances,
                        queried_at, source_ae, source_ip
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                
                values = tuple(metadata.values())
                await self.db_manager.execute_query(query, values)
                
        except Exception as e:
            logger.error(f"Failed to store query results: {e}")
    
    async def batch_store_directory(self, directory_path: str, 
                                  target_ip: Optional[str] = None,
                                  target_port: Optional[int] = None,
                                  target_ae: Optional[str] = None) -> Dict[str, int]:
        """
        Send all DICOM files in a directory using C-STORE
        
        Args:
            directory_path: Directory containing DICOM files
            target_ip: Override target IP
            target_port: Override target port
            target_ae: Override target AE title
            
        Returns:
            Dictionary with statistics (sent, failed)
        """
        stats = {'sent': 0, 'failed': 0}
        
        try:
            directory = Path(directory_path)
            if not directory.exists():
                logger.error(f"Directory does not exist: {directory_path}")
                return stats
            
            # Find all DICOM files
            dicom_files = []
            for ext in ['*.dcm', '*.DCM', '*.dicom', '*.DICOM']:
                dicom_files.extend(directory.rglob(ext))
            
            logger.info(f"Found {len(dicom_files)} DICOM files to send")
            
            # Send each file
            for file_path in dicom_files:
                success = await self.store_image(str(file_path), target_ip, target_port, target_ae)
                if success:
                    stats['sent'] += 1
                else:
                    stats['failed'] += 1
                
                # Small delay to prevent overwhelming the target
                await asyncio.sleep(0.1)
            
            logger.info(f"Batch C-STORE completed: {stats['sent']} sent, {stats['failed']} failed")
            return stats
            
        except Exception as e:
            logger.error(f"Error during batch C-STORE: {e}")
            return stats
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get service statistics
        
        Returns:
            Dictionary containing service statistics
        """
        return {
            'is_running': self.is_running,
            'is_configured': self.is_configured,
            'queries_performed': self.queries_performed,
            'images_sent': self.images_sent,
            'images_retrieved': self.images_retrieved,
            'errors_occurred': self.errors_occurred,
            'config': self.config.copy()
        }
    
    def reset_statistics(self):
        """Reset service statistics"""
        self.queries_performed = 0
        self.images_sent = 0
        self.images_retrieved = 0
        self.errors_occurred = 0
        logger.info("DICOM SCU statistics reset")


# Helper function to create database table for query results
async def create_dicom_query_tables(db_manager: DatabaseManager):
    """
    Create database tables for DICOM query results
    
    Args:
        db_manager: Database manager instance
    """
    create_table_query = """
        CREATE TABLE IF NOT EXISTS dicom_query_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_level TEXT,
            study_instance_uid TEXT,
            series_instance_uid TEXT,
            sop_instance_uid TEXT,
            patient_id TEXT,
            patient_name TEXT,
            study_date TEXT,
            study_time TEXT,
            modality TEXT,
            study_description TEXT,
            series_description TEXT,
            number_of_instances TEXT,
            queried_at TEXT,
            source_ae TEXT,
            source_ip TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """
    
    await db_manager.execute_query(create_table_query)
    
    # Create indexes
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_query_study_uid ON dicom_query_results(study_instance_uid)",
        "CREATE INDEX IF NOT EXISTS idx_query_patient_id ON dicom_query_results(patient_id)",
        "CREATE INDEX IF NOT EXISTS idx_query_date ON dicom_query_results(study_date)",
        "CREATE INDEX IF NOT EXISTS idx_query_modality ON dicom_query_results(modality)"
    ]
    
    for index_query in indexes:
        await db_manager.execute_query(index_query)


__all__ = ['DICOMSCUService', 'create_dicom_query_tables']
