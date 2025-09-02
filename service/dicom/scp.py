"""
DICOM SCP Service

Implements a DICOM Storage Service Class Provider (SCP) that can receive
DICOM images and store them in the database and filesystem.
"""

import asyncio
import os
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
import uuid

from pynetdicom import AE, evt, debug_logger
from pynetdicom.sop_class import *
from pydicom import dcmread
from pydicom.dataset import Dataset

from core.custom_logging import get_logger
from core.database import DatabaseManager
from core.config import Settings

logger = get_logger(__name__)

# Enable pynetdicom debug logging if needed
# debug_logger()


class DICOMSCPService:
    """
    DICOM Storage SCP Service
    
    Provides a DICOM listener that can:
    - Accept associations from DICOM SCUs
    - Store received DICOM images to filesystem
    - Store DICOM metadata to database
    - Support multiple storage SOP classes
    """
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        """
        Initialize DICOM SCP service
        
        Args:
            db_manager: Database manager instance
            settings: Application settings
        """
        self.db_manager = db_manager
        self.settings = settings
        
        # Configuration
        self.is_configured = False
        self.is_running = False
        self.stop_requested = False
        
        # Default configuration
        self.config = {
            'port': 104,
            'ae_title': 'MIGRATIONSERVICE',
            'output_directory': './Archive',
            'max_pdu': 65536,
            'acse_timeout': 30,
            'dimse_timeout': 30,
            'socket_timeout': 60,
            'write_meta_header': True,
            'file_extension': 'dcm'
        }
        
        # Statistics
        self.associations_processed = 0
        self.files_stored = 0
        self.errors_occurred = 0
        
        # Application Entity
        self.ae: Optional[AE] = None
        self.server_thread: Optional[threading.Thread] = None
        
        # Storage handlers
        self.storage_handlers = {}
        
        logger.info("DICOM SCP Service initialized")
    
    def configure(self, config: Dict[str, Any]) -> bool:
        """
        Configure the DICOM SCP service
        
        Args:
            config: Configuration dictionary with SCP parameters
            
        Returns:
            True if configuration successful, False otherwise
        """
        try:
            # Update configuration with provided values
            self.config.update(config)
            
            # Validate required parameters
            if not isinstance(self.config['port'], int) or self.config['port'] <= 0:
                logger.error(f"Invalid port: {self.config['port']}")
                return False
            
            if not self.config['ae_title']:
                logger.error("AE Title is required")
                return False
            
            # Create output directory if it doesn't exist
            output_dir = Path(self.config['output_directory'])
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Initialize Application Entity
            self.ae = AE(ae_title=self.config['ae_title'])
            
            # Add supported storage SOP classes
            storage_sops = self._get_supported_storage_sops()
            for sop_class in storage_sops:
                self.ae.add_supported_context(sop_class)
            
            # Add Query/Retrieve SOP classes for C-MOVE support
            qr_sops = self._get_supported_qr_sops()
            for sop_class in qr_sops:
                self.ae.add_supported_context(sop_class)
            
            # Configure network options
            self.ae.maximum_pdu_size = self.config['max_pdu']
            self.ae.acse_timeout = self.config['acse_timeout']
            self.ae.dimse_timeout = self.config['dimse_timeout']
            self.ae.network_timeout = self.config['socket_timeout']
            
            # Set up event handlers
            self._setup_event_handlers()
            
            self.is_configured = True
            logger.info(f"DICOM SCP configured: AE={self.config['ae_title']}, Port={self.config['port']}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to configure DICOM SCP: {e}")
            return False
    
    def _get_supported_storage_sops(self) -> List:
        """Get list of supported storage SOP classes"""
        # Use a try/except approach to only include available SOP classes
        sop_classes = []
        
        # Essential classes that should always be available
        essential_classes = [
            ('Verification', Verification),
            ('CTImageStorage', CTImageStorage),
            ('MRImageStorage', MRImageStorage),
            ('UltrasoundImageStorage', UltrasoundImageStorage),
            ('SecondaryCaptureImageStorage', SecondaryCaptureImageStorage),
        ]
        
        # Additional classes that may or may not be available
        optional_classes = [
            ('ComputedRadiographyImageStorage', 'ComputedRadiographyImageStorage'),
            ('DigitalXRayImageStorageForPresentation', 'DigitalXRayImageStorageForPresentation'),
            ('DigitalXRayImageStorageForProcessing', 'DigitalXRayImageStorageForProcessing'),
            ('EnhancedCTImageStorage', 'EnhancedCTImageStorage'),
            ('EnhancedMRImageStorage', 'EnhancedMRImageStorage'),
            ('UltrasoundMultiFrameImageStorage', 'UltrasoundMultiFrameImageStorage'),
            ('NuclearMedicineImageStorage', 'NuclearMedicineImageStorage'),
            ('PositronEmissionTomographyImageStorage', 'PositronEmissionTomographyImageStorage'),
            ('RTImageStorage', 'RTImageStorage'),
            ('BasicTextSRStorage', 'BasicTextSRStorage'),
            ('XRayAngiographicImageStorage', 'XRayAngiographicImageStorage'),
        ]
        
        # Add essential classes
        for name, sop_class in essential_classes:
            try:
                sop_classes.append(sop_class)
            except NameError:
                logger.warning(f"Essential SOP class not available: {name}")
        
        # Add optional classes if available
        for name, class_name in optional_classes:
            try:
                sop_class = globals().get(class_name)
                if sop_class:
                    sop_classes.append(sop_class)
            except (NameError, AttributeError):
                logger.debug(f"Optional SOP class not available: {name}")
        
        logger.info(f"Configured {len(sop_classes)} DICOM SOP classes")
        return sop_classes
    
    def _get_supported_qr_sops(self) -> List:
        """Get list of supported Query/Retrieve SOP classes"""
        qr_classes = []
        
        # Query/Retrieve SOP classes for C-MOVE support
        qr_sop_classes = [
            ('StudyRootQueryRetrieveInformationModelMove', 'StudyRootQueryRetrieveInformationModelMove'),
            ('PatientRootQueryRetrieveInformationModelMove', 'PatientRootQueryRetrieveInformationModelMove'),
            ('PatientStudyOnlyQueryRetrieveInformationModelMove', 'PatientStudyOnlyQueryRetrieveInformationModelMove')
        ]
        
        for name, class_name in qr_sop_classes:
            try:
                sop_class = globals().get(class_name)
                if sop_class:
                    qr_classes.append(sop_class)
                    logger.debug(f"Added Q/R SOP class: {name}")
            except (NameError, AttributeError):
                logger.debug(f"Q/R SOP class not available: {name}")
        
        logger.info(f"Configured {len(qr_classes)} Query/Retrieve SOP classes")
        return qr_classes
    
    def _setup_event_handlers(self):
        """Setup event handlers for the DICOM AE"""
        
        # Create handlers list for use in start_server
        self.handlers = [
            (evt.EVT_C_STORE, self._handle_store),
            (evt.EVT_C_MOVE, self._handle_move),
            (evt.EVT_CONN_OPEN, self._handle_conn_open),
            (evt.EVT_CONN_CLOSE, self._handle_conn_close),
            (evt.EVT_ACCEPTED, self._handle_accepted),
            (evt.EVT_RELEASED, self._handle_released)
        ]
    
    def _handle_conn_open(self, event):
        """Handle connection opened event"""
        logger.debug(f"Connection opened from {event.address}")
    
    def _handle_conn_close(self, event):
        """Handle connection closed event"""
        logger.debug(f"Connection closed from {event.address}")
    
    def _handle_accepted(self, event):
        """Handle association accepted event"""
        self.associations_processed += 1
        logger.info(f"Association accepted from {event.assoc.requestor.ae_title} at {event.assoc.requestor.address}")
    
    def _handle_released(self, event):
        """Handle association released event"""
        logger.debug(f"Association released")
    
    def _handle_move(self, event):
        """
        Handle C-MOVE request - move images to another DICOM node
        
        Args:
            event: PyNetDICOM move event
            
        Returns:
            Generator yielding (status, dataset) tuples for move progress
        """
        try:
            # Get the move destination AE title from the request
            move_destination = event.move_destination
            if not move_destination:
                logger.error("C-MOVE request missing destination AE title")
                yield (0xC000, None)  # Cannot understand
                return
            
            # Get the query dataset
            ds = event.identifier
            
            # Extract query parameters
            query_level = getattr(ds, 'QueryRetrieveLevel', 'STUDY')
            
            logger.info(f"C-MOVE request: Level={query_level}, Destination={move_destination}")
            
            # Get destination device info from database
            destination_info = self._get_destination_device_info(move_destination)
            if not destination_info:
                logger.error(f"Destination AE title not found in database: {move_destination}")
                yield (0xA801, None)  # Move destination unknown
                return
            
            # Find images to move based on query level
            images_to_move = self._find_images_for_move(ds, query_level)
            if not images_to_move:
                logger.warning("No images found matching C-MOVE criteria")
                yield (0xA702, None)  # Out of resources - no images found
                return
            
            logger.info(f"Found {len(images_to_move)} images to move to {move_destination}")
            
            # Perform the actual C-MOVE operation
            yield from self._perform_move_operation(
                images_to_move, 
                destination_info, 
                move_destination
            )
            
        except Exception as e:
            logger.error(f"Error handling C-MOVE: {e}")
            self.errors_occurred += 1
            yield (0xC000, None)  # Cannot understand
    
    def _get_destination_device_info(self, ae_title: str) -> Optional[Dict[str, Any]]:
        """
        Get destination device information from database
        
        Args:
            ae_title: AE title of destination device
            
        Returns:
            Dict with device info (ip_address, port, ae_title) or None if not found
        """
        try:
            # Query the device table for the AE title
            # Run in thread to avoid blocking the event handler
            import threading
            
            result = {'device_info': None, 'error': None}
            
            def query_db():
                try:
                    # This runs a sync database query in a thread
                    import sqlite3
                    db_path = self.settings.database_url.replace('sqlite:///', '')
                    
                    with sqlite3.connect(db_path) as conn:
                        conn.row_factory = sqlite3.Row
                        cursor = conn.cursor()
                        
                        cursor.execute(
                            "SELECT ip_address, port, ae_title, device_name FROM device WHERE ae_title = ? AND enabled = 1",
                            (ae_title,)
                        )
                        
                        row = cursor.fetchone()
                        if row:
                            result['device_info'] = {
                                'ip_address': row['ip_address'],
                                'port': row['port'],
                                'ae_title': row['ae_title'],
                                'device_name': row['device_name']
                            }
                except Exception as e:
                    result['error'] = str(e)
            
            # Run query in thread
            thread = threading.Thread(target=query_db)
            thread.start()
            thread.join(timeout=5)  # Wait up to 5 seconds
            
            if result['error']:
                logger.error(f"Database query error: {result['error']}")
                return None
            
            return result['device_info']
            
        except Exception as e:
            logger.error(f"Error getting destination device info: {e}")
            return None
    
    def _find_images_for_move(self, query_ds: Dataset, query_level: str) -> List[str]:
        """
        Find images that match the C-MOVE query criteria
        
        Args:
            query_ds: Query dataset with search criteria
            query_level: Query level (STUDY, SERIES, IMAGE)
            
        Returns:
            List of file paths for images to move
        """
        try:
            import threading
            import sqlite3
            
            result = {'file_paths': [], 'error': None}
            
            def query_images():
                try:
                    db_path = self.settings.database_url.replace('sqlite:///', '')
                    
                    with sqlite3.connect(db_path) as conn:
                        conn.row_factory = sqlite3.Row
                        cursor = conn.cursor()
                        
                        # Build query based on level and criteria
                        if query_level == 'STUDY':
                            study_uid = getattr(query_ds, 'StudyInstanceUID', '')
                            if study_uid:
                                cursor.execute(
                                    "SELECT file_path FROM dicom_files WHERE study_instance_uid = ?",
                                    (study_uid,)
                                )
                            else:
                                # Search by patient ID if no study UID
                                patient_id = getattr(query_ds, 'PatientID', '')
                                if patient_id:
                                    cursor.execute(
                                        "SELECT file_path FROM dicom_files WHERE patient_id = ?",
                                        (patient_id,)
                                    )
                                else:
                                    logger.warning("C-MOVE query has no useful criteria")
                                    return
                        
                        elif query_level == 'SERIES':
                            series_uid = getattr(query_ds, 'SeriesInstanceUID', '')
                            if series_uid:
                                cursor.execute(
                                    "SELECT file_path FROM dicom_files WHERE series_instance_uid = ?",
                                    (series_uid,)
                                )
                        
                        elif query_level == 'IMAGE':
                            sop_uid = getattr(query_ds, 'SOPInstanceUID', '')
                            if sop_uid:
                                cursor.execute(
                                    "SELECT file_path FROM dicom_files WHERE sop_instance_uid = ?",
                                    (sop_uid,)
                                )
                        
                        rows = cursor.fetchall()
                        result['file_paths'] = [row['file_path'] for row in rows if row['file_path']]
                        
                except Exception as e:
                    result['error'] = str(e)
            
            # Run query in thread
            thread = threading.Thread(target=query_images)
            thread.start()
            thread.join(timeout=10)  # Wait up to 10 seconds
            
            if result['error']:
                logger.error(f"Error finding images for move: {result['error']}")
                return []
            
            return result['file_paths']
            
        except Exception as e:
            logger.error(f"Error finding images for move: {e}")
            return []
    
    def _perform_move_operation(self, image_paths: List[str], destination_info: Dict[str, Any], 
                               destination_ae: str) -> Any:
        """
        Perform the actual C-MOVE operation by sending images to destination
        
        Args:
            image_paths: List of file paths to move
            destination_info: Destination device information
            destination_ae: Destination AE title
            
        Yields:
            Status and dataset tuples for move progress
        """
        try:
            total_images = len(image_paths)
            moved_count = 0
            failed_count = 0
            
            logger.info(f"Starting C-MOVE operation: {total_images} images to {destination_ae}")
            
            # Create SCU AE for sending images to destination
            scu_ae = AE(ae_title=self.config['ae_title'])
            
            # Add all storage contexts we support
            storage_sops = self._get_supported_storage_sops()
            for sop_class in storage_sops:
                scu_ae.add_requested_context(sop_class)
            
            # Process each image
            for i, image_path in enumerate(image_paths):
                try:
                    # Read the DICOM file
                    if not os.path.exists(image_path):
                        logger.warning(f"File not found: {image_path}")
                        failed_count += 1
                        continue
                    
                    ds = dcmread(image_path)
                    
                    # Establish association with destination
                    assoc = scu_ae.associate(
                        destination_info['ip_address'],
                        destination_info['port'],
                        ae_title=destination_info['ae_title']
                    )
                    
                    if assoc.is_established:
                        # Send C-STORE to destination
                        status = assoc.send_c_store(ds)
                        assoc.release()
                        
                        if status and status.Status == 0x0000:
                            moved_count += 1
                            logger.debug(f"Successfully moved image {i+1}/{total_images}: {os.path.basename(image_path)}")
                        else:
                            failed_count += 1
                            logger.warning(f"Failed to store image at destination: status={status.Status if status else 'None'}")
                    else:
                        failed_count += 1
                        logger.error(f"Failed to establish association with destination {destination_info['ip_address']}:{destination_info['port']}")
                    
                    # Yield progress status
                    if (i + 1) % 10 == 0 or i == total_images - 1:
                        # Create status dataset with progress information
                        status_ds = Dataset()
                        status_ds.NumberOfRemainingSuboperations = total_images - (i + 1)
                        status_ds.NumberOfCompletedSuboperations = moved_count
                        status_ds.NumberOfFailedSuboperations = failed_count
                        status_ds.NumberOfWarningSuboperations = 0
                        
                        # Yield pending status with progress
                        yield (0xFF00, status_ds)  # Pending with progress
                        
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Error processing image {image_path}: {e}")
                    continue
            
            # Final status
            final_status_ds = Dataset()
            final_status_ds.NumberOfRemainingSuboperations = 0
            final_status_ds.NumberOfCompletedSuboperations = moved_count
            final_status_ds.NumberOfFailedSuboperations = failed_count
            final_status_ds.NumberOfWarningSuboperations = 0
            
            if failed_count == 0:
                # All successful
                yield (0x0000, final_status_ds)  # Success
                logger.info(f"C-MOVE completed successfully: {moved_count}/{total_images} images moved to {destination_ae}")
            elif moved_count > 0:
                # Partial success
                yield (0xB000, final_status_ds)  # Warning - some failures
                logger.warning(f"C-MOVE partially successful: {moved_count}/{total_images} images moved, {failed_count} failed")
            else:
                # Complete failure
                yield (0xC000, final_status_ds)  # Failure
                logger.error(f"C-MOVE failed: {failed_count}/{total_images} images failed to move")
            
        except Exception as e:
            logger.error(f"Error in C-MOVE operation: {e}")
            yield (0xC000, None)  # Cannot understand
    
    def _handle_store(self, event):
        """
        Handle C-STORE request (equivalent to storeSCPCallback in C++)
        
        Args:
            event: PyNetDICOM store event
            
        Returns:
            Status code for the store operation
        """
        try:
            # Get the dataset
            ds = event.dataset
            
            # Extract required DICOM tags (matching C++ implementation)
            try:
                sop_instance_uid = str(ds.SOPInstanceUID)
                study_instance_uid = str(ds.StudyInstanceUID) 
                study_date = str(ds.StudyDate)
            except AttributeError as e:
                logger.error(f"Missing required DICOM tags: {e}")
                return 0xC000  # Cannot understand - missing required tags
            
            # Validate we have minimum required data (matching C++ validation)
            if not sop_instance_uid or not study_instance_uid or not study_date:
                logger.error("Required DICOM tags are empty")
                return 0xC000  # Cannot understand
            
            # Create directory structure: YYYY/MM/DD/SUID (matching C++ line 366-367)
            try:
                year = study_date[:4]
                month = study_date[4:6] 
                day = study_date[6:8]
                
                # Build path: output_directory/YYYY/MM/DD/StudyInstanceUID
                subdir_path = Path(self.config['output_directory']) / year / month / day / study_instance_uid
                subdir_path.mkdir(parents=True, exist_ok=True)
                
                # Create filename using SOP Instance UID + .DCM (matching C++ line 389-390)
                filename = f"{sop_instance_uid}.DCM"
                file_path = subdir_path / filename
                
            except (ValueError, IndexError) as e:
                logger.error(f"Invalid study date format '{study_date}': {e}")
                return 0xC000  # Cannot understand
            
            # Add File Meta Information if requested
            if self.config['write_meta_header']:
                # Create file meta information
                file_meta = Dataset()
                file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
                file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
                file_meta.ImplementationClassUID = "1.2.826.0.1.3680043.9.7433.1.1"  # Migration Service UID
                file_meta.ImplementationVersionName = "MigrationService_v1"
                
                ds.file_meta = file_meta
            
            # Save the DICOM file
            ds.save_as(str(file_path), write_like_original=False)
            
            # Store metadata in database (sync call for now)
            # TODO: Make this async in a proper event loop context
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Schedule for later execution
                    asyncio.create_task(self._store_metadata_in_database(ds, str(file_path)))
                else:
                    # Run in new event loop
                    asyncio.run(self._store_metadata_in_database(ds, str(file_path)))
            except Exception as db_error:
                logger.warning(f"Failed to store metadata: {db_error}")
            
            self.files_stored += 1
            logger.info(f"Stored DICOM file: {file_path}")
            
            # Return success status
            return 0x0000  # Success
            
        except Exception as e:
            logger.error(f"Error handling C-STORE: {e}")
            self.errors_occurred += 1
            return 0xC000  # Error - Cannot understand
    
    async def _store_metadata_in_database(self, ds: Dataset, file_path: str):
        """
        Store DICOM metadata in database
        
        Args:
            ds: DICOM dataset
            file_path: Path where file was stored
        """
        try:
            # Extract key DICOM tags
            metadata = {
                'sop_instance_uid': str(getattr(ds, 'SOPInstanceUID', '')),
                'sop_class_uid': str(getattr(ds, 'SOPClassUID', '')),
                'study_instance_uid': str(getattr(ds, 'StudyInstanceUID', '')),
                'series_instance_uid': str(getattr(ds, 'SeriesInstanceUID', '')),
                'patient_id': str(getattr(ds, 'PatientID', '')),
                'patient_name': str(getattr(ds, 'PatientName', '')),
                'study_date': str(getattr(ds, 'StudyDate', '')),
                'study_time': str(getattr(ds, 'StudyTime', '')),
                'modality': str(getattr(ds, 'Modality', '')),
                'institution_name': str(getattr(ds, 'InstitutionName', '')),
                'file_path': file_path,
                'received_at': datetime.now().isoformat()
            }
            
            # Insert into database
            query = """
                INSERT INTO dicom_files (
                    sop_instance_uid, sop_class_uid, study_instance_uid, 
                    series_instance_uid, patient_id, patient_name,
                    study_date, study_time, modality, institution_name,
                    file_path, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            values = tuple(metadata.values())
            await self.db_manager.execute_query(query, values)
            
            logger.debug(f"Stored metadata for SOP Instance: {metadata['sop_instance_uid']}")
            
        except Exception as e:
            logger.error(f"Failed to store metadata in database: {e}")
    
    def start(self) -> bool:
        """
        Start the DICOM SCP service
        
        Returns:
            True if started successfully, False otherwise
        """
        if not self.is_configured:
            logger.error("DICOM SCP not configured. Call configure() first.")
            return False
        
        if self.is_running:
            logger.warning("DICOM SCP already running")
            return True
        
        try:
            logger.info(f"Starting DICOM SCP on port {self.config['port']}")
            
            # Start the SCP server in a separate thread
            self.stop_requested = False
            self.server_thread = threading.Thread(
                target=self._run_server,
                daemon=True,
                name=f"DICOMSCPServer-{self.config['port']}"
            )
            self.server_thread.start()
            
            self.is_running = True
            logger.info(f"DICOM SCP started successfully on port {self.config['port']}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start DICOM SCP: {e}")
            return False
    
    def _run_server(self):
        """Run the DICOM SCP server"""
        try:
            # Start listening for incoming associations
            self.ae.start_server(
                ('', self.config['port']),
                block=True,
                evt_handlers=self.handlers
            )
            
        except Exception as e:
            logger.error(f"DICOM SCP server error: {e}")
        finally:
            self.is_running = False
    
    def stop(self) -> bool:
        """
        Stop the DICOM SCP service
        
        Returns:
            True if stopped successfully, False otherwise
        """
        if not self.is_running:
            logger.warning("DICOM SCP not running")
            return True
        
        try:
            logger.info("Stopping DICOM SCP service...")
            
            self.stop_requested = True
            
            # Stop the Application Entity
            if self.ae:
                self.ae.shutdown()
            
            # Wait for server thread to finish
            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=10)
            
            self.is_running = False
            logger.info("DICOM SCP stopped successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping DICOM SCP: {e}")
            return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get service statistics
        
        Returns:
            Dictionary containing service statistics
        """
        return {
            'is_running': self.is_running,
            'is_configured': self.is_configured,
            'associations_processed': self.associations_processed,
            'files_stored': self.files_stored,
            'errors_occurred': self.errors_occurred,
            'config': self.config.copy()
        }
    
    def reset_statistics(self):
        """Reset service statistics"""
        self.associations_processed = 0
        self.files_stored = 0
        self.errors_occurred = 0
        logger.info("DICOM SCP statistics reset")


# Helper function to create database table for DICOM files
async def create_dicom_tables(db_manager: DatabaseManager):
    """
    Create database tables for DICOM storage
    
    Args:
        db_manager: Database manager instance
    """
    create_table_query = """
        CREATE TABLE IF NOT EXISTS dicom_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sop_instance_uid TEXT UNIQUE NOT NULL,
            sop_class_uid TEXT,
            study_instance_uid TEXT,
            series_instance_uid TEXT,
            patient_id TEXT,
            patient_name TEXT,
            study_date TEXT,
            study_time TEXT,
            modality TEXT,
            institution_name TEXT,
            file_path TEXT,
            received_at TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """
    
    await db_manager.execute_query(create_table_query)
    
    # Create indexes for common queries
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_patient_id ON dicom_files(patient_id)",
        "CREATE INDEX IF NOT EXISTS idx_study_instance_uid ON dicom_files(study_instance_uid)",
        "CREATE INDEX IF NOT EXISTS idx_series_instance_uid ON dicom_files(series_instance_uid)",
        "CREATE INDEX IF NOT EXISTS idx_study_date ON dicom_files(study_date)",
        "CREATE INDEX IF NOT EXISTS idx_modality ON dicom_files(modality)"
    ]
    
    for index_query in indexes:
        await db_manager.execute_query(index_query)


__all__ = ['DICOMSCPService', 'create_dicom_tables']
