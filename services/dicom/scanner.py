"""
DICOM Directory Scanner

Recursively scans directories for DICOM files, reads metadata, and inserts into database.
Supports DICOM, DICONDE, and DICOS file formats with comprehensive metadata extraction.
"""

import asyncio
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Generator, Tuple
import hashlib
import mimetypes

from pydicom import dcmread, errors as dicom_errors
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import UID
from pydicom.filereader import InvalidDicomError

from ...core.logging import get_logger
from ...core.database import DatabaseManager
from ...core.config import Settings

logger = get_logger(__name__)


class DICOMDirectoryScanner:
    """
    DICOM Directory Scanner
    
    Provides functionality to:
    - Recursively scan directories for DICOM files
    - Extract comprehensive metadata from DICOM, DICONDE, and DICOS files
    - Insert metadata into database with proper indexing
    - Track scanning progress and statistics
    - Handle various DICOM transfer syntaxes including DICONDE and DICOS
    """
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        """
        Initialize DICOM directory scanner
        
        Args:
            db_manager: Database manager instance
            settings: Application settings
        """
        self.db_manager = db_manager
        self.settings = settings
        
        # Configuration
        self.config = {
            'supported_extensions': ['.dcm', '.dicom', '.dic', '.ima', '.img', ''],
            'max_file_size': 2 * 1024 * 1024 * 1024,  # 2GB max file size
            'batch_size': 100,  # Process files in batches
            'verify_dicom_header': True,
            'extract_pixel_data': False,  # Don't store pixel data by default
            'calculate_checksums': True,
            'skip_duplicates': True
        }
        
        # Scanning progress
        self.scan_progress = {
            'total_files': 0,
            'scanned_files': 0,
            'dicom_files_found': 0,
            'diconde_files_found': 0,
            'dicos_files_found': 0,
            'errors': 0,
            'duplicates_skipped': 0,
            'start_time': None,
            'end_time': None,
            'current_directory': '',
            'current_file': ''
        }
        
        # Transfer syntax UIDs for DICONDE and DICOS
        self.special_transfer_syntaxes = {
            # DICONDE (Digital Imaging and Communication in Non-Destructive Evaluation)
            '1.2.840.10008.1.2.4.94': 'JPEG 2000 Image Compression (Lossless)',
            '1.2.840.10008.1.2.4.95': 'JPEG 2000 Image Compression (Lossy)',
            # DICOS (Digital Imaging and Communications in Security)
            '1.2.840.10008.1.2.4.101': 'MPEG2 Main Profile @ Main Level',
            '1.2.840.10008.1.2.4.102': 'MPEG2 Main Profile @ High Level',
            '1.2.840.10008.1.2.4.103': 'MPEG-4 AVC/H.264 High Profile / Level 4.1',
            '1.2.840.10008.1.2.4.104': 'MPEG-4 AVC/H.264 BD-compatible High Profile / Level 4.1'
        }
        
        logger.info("DICOM Directory Scanner initialized")
    
    async def scan_directory(
        self, 
        directory: str,
        recursive: bool = True,
        file_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Scan directory for DICOM files and insert metadata into database
        
        Args:
            directory: Directory path to scan
            recursive: Whether to scan subdirectories recursively
            file_patterns: List of file patterns to include (default: DICOM extensions)
            exclude_patterns: List of patterns to exclude from scanning
            
        Returns:
            Dictionary with scan results and statistics
        """
        try:
            directory_path = Path(directory)
            if not directory_path.exists():
                raise ValueError(f"Directory does not exist: {directory}")
            
            if not directory_path.is_dir():
                raise ValueError(f"Path is not a directory: {directory}")
            
            logger.info(f"Starting DICOM directory scan: {directory} (recursive={recursive})")
            
            # Initialize progress tracking
            self.scan_progress = {
                'total_files': 0,
                'scanned_files': 0,
                'dicom_files_found': 0,
                'diconde_files_found': 0,
                'dicos_files_found': 0,
                'errors': 0,
                'duplicates_skipped': 0,
                'start_time': datetime.now(),
                'end_time': None,
                'current_directory': str(directory_path),
                'current_file': ''
            }
            
            # Ensure database tables exist
            await self._ensure_dicom_tables()
            
            # Get list of all potential DICOM files
            file_list = list(self._find_dicom_files(directory_path, recursive, file_patterns, exclude_patterns))
            self.scan_progress['total_files'] = len(file_list)
            
            logger.info(f"Found {len(file_list)} potential DICOM files to process")
            
            # Process files in batches
            batch_results = []
            for i in range(0, len(file_list), self.config['batch_size']):
                batch = file_list[i:i + self.config['batch_size']]
                batch_result = await self._process_file_batch(batch)
                batch_results.append(batch_result)
                
                # Log progress
                progress_pct = (self.scan_progress['scanned_files'] / self.scan_progress['total_files']) * 100
                logger.info(f"Scan progress: {progress_pct:.1f}% ({self.scan_progress['scanned_files']}/{self.scan_progress['total_files']} files)")
            
            # Update final progress
            self.scan_progress['end_time'] = datetime.now()
            duration = self.scan_progress['end_time'] - self.scan_progress['start_time']
            
            # Compile final results
            results = {
                'directory': directory,
                'total_files_scanned': self.scan_progress['scanned_files'],
                'dicom_files_found': self.scan_progress['dicom_files_found'],
                'diconde_files_found': self.scan_progress['diconde_files_found'],
                'dicos_files_found': self.scan_progress['dicos_files_found'],
                'total_dicom_files': (self.scan_progress['dicom_files_found'] + 
                                    self.scan_progress['diconde_files_found'] + 
                                    self.scan_progress['dicos_files_found']),
                'errors': self.scan_progress['errors'],
                'duplicates_skipped': self.scan_progress['duplicates_skipped'],
                'duration_seconds': duration.total_seconds(),
                'files_per_second': self.scan_progress['scanned_files'] / duration.total_seconds() if duration.total_seconds() > 0 else 0
            }
            
            logger.info(f"Directory scan completed: {results['total_dicom_files']} DICOM files processed in {duration.total_seconds():.1f} seconds")
            return results
            
        except Exception as e:
            logger.error(f"Error during directory scan: {e}")
            raise
    
    def _find_dicom_files(
        self, 
        directory: Path, 
        recursive: bool,
        file_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None
    ) -> Generator[Path, None, None]:
        """
        Find potential DICOM files in directory
        
        Args:
            directory: Directory to search
            recursive: Whether to search recursively
            file_patterns: File patterns to include
            exclude_patterns: File patterns to exclude
            
        Yields:
            Path objects for potential DICOM files
        """
        try:
            # Use configured extensions if no patterns provided
            if file_patterns is None:
                file_patterns = self.config['supported_extensions']
            
            # Walk directory tree
            for root, dirs, files in os.walk(directory):
                self.scan_progress['current_directory'] = root
                
                for file in files:
                    file_path = Path(root) / file
                    
                    # Check file size
                    try:
                        if file_path.stat().st_size > self.config['max_file_size']:
                            logger.warning(f"Skipping large file: {file_path} ({file_path.stat().st_size} bytes)")
                            continue
                    except OSError:
                        continue
                    
                    # Check extension patterns
                    file_ext = file_path.suffix.lower()
                    if file_patterns and not any(pattern == '' or file_ext == pattern for pattern in file_patterns):\n                        continue
                    
                    # Check exclude patterns
                    if exclude_patterns and any(pattern in str(file_path).lower() for pattern in exclude_patterns):
                        continue
                    
                    yield file_path
                
                # Stop recursion if not recursive
                if not recursive:
                    dirs.clear()
                    
        except Exception as e:
            logger.error(f"Error finding DICOM files in {directory}: {e}")
    
    async def _process_file_batch(self, file_paths: List[Path]) -> Dict[str, Any]:
        """
        Process a batch of files
        
        Args:
            file_paths: List of file paths to process
            
        Returns:
            Dictionary with batch processing results
        """
        batch_results = {
            'processed': 0,
            'dicom_files': 0,
            'errors': 0,
            'duplicates': 0
        }
        
        for file_path in file_paths:
            try:
                self.scan_progress['current_file'] = str(file_path)
                result = await self._process_single_file(file_path)
                
                batch_results['processed'] += 1
                self.scan_progress['scanned_files'] += 1
                
                if result:
                    if result['file_type'] == 'DICOM':
                        batch_results['dicom_files'] += 1
                        self.scan_progress['dicom_files_found'] += 1
                    elif result['file_type'] == 'DICONDE':
                        batch_results['dicom_files'] += 1
                        self.scan_progress['diconde_files_found'] += 1
                    elif result['file_type'] == 'DICOS':
                        batch_results['dicom_files'] += 1
                        self.scan_progress['dicos_files_found'] += 1
                    
                    if result.get('duplicate', False):
                        batch_results['duplicates'] += 1
                        self.scan_progress['duplicates_skipped'] += 1
                
            except Exception as e:
                logger.debug(f"Error processing file {file_path}: {e}")
                batch_results['errors'] += 1
                self.scan_progress['errors'] += 1
                continue
        
        return batch_results
    
    async def _process_single_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        Process a single file and extract DICOM metadata
        
        Args:
            file_path: Path to the file to process
            
        Returns:
            Dictionary with extracted metadata or None if not a DICOM file
        """
        try:
            # First check if it looks like a DICOM file
            if not await self._is_dicom_file(file_path):
                return None
            
            # Read DICOM dataset
            try:
                ds = dcmread(str(file_path), force=True, stop_before_pixels=not self.config['extract_pixel_data'])
            except (InvalidDicomError, dicom_errors.InvalidDicomError) as e:
                logger.debug(f"Not a valid DICOM file: {file_path} - {e}")
                return None
            
            # Extract metadata
            metadata = await self._extract_metadata(ds, file_path)
            
            # Check for duplicate based on SOP Instance UID
            if self.config['skip_duplicates'] and await self._is_duplicate(metadata['sop_instance_uid']):
                return {'duplicate': True, 'file_type': metadata['file_type']}
            
            # Insert into database
            await self._insert_metadata(metadata)
            
            return {'duplicate': False, 'file_type': metadata['file_type']}
            
        except Exception as e:
            logger.debug(f"Error processing DICOM file {file_path}: {e}")
            raise
    
    async def _is_dicom_file(self, file_path: Path) -> bool:
        """
        Quick check if file is likely a DICOM file
        
        Args:
            file_path: Path to check
            
        Returns:
            True if likely DICOM, False otherwise
        """
        try:
            with open(file_path, 'rb') as f:
                # Check for DICM magic bytes at offset 128
                f.seek(128)
                magic = f.read(4)
                return magic == b'DICM'
        except (OSError, IOError):
            return False
    
    async def _extract_metadata(self, ds: Dataset, file_path: Path) -> Dict[str, Any]:
        """
        Extract comprehensive metadata from DICOM dataset
        
        Args:
            ds: DICOM dataset
            file_path: Original file path
            
        Returns:
            Dictionary with extracted metadata
        """
        try:
            # Determine file type based on SOP Class UID
            sop_class_uid = str(getattr(ds, 'SOPClassUID', ''))
            file_type = self._determine_file_type(sop_class_uid)
            
            # Extract transfer syntax information
            transfer_syntax = self._get_transfer_syntax_info(ds)
            
            # Calculate file checksum if enabled
            file_checksum = None
            if self.config['calculate_checksums']:
                file_checksum = await self._calculate_file_checksum(file_path)
            
            # Extract comprehensive metadata
            metadata = {
                # Core DICOM identifiers
                'sop_instance_uid': str(getattr(ds, 'SOPInstanceUID', '')),
                'sop_class_uid': sop_class_uid,
                'study_instance_uid': str(getattr(ds, 'StudyInstanceUID', '')),
                'series_instance_uid': str(getattr(ds, 'SeriesInstanceUID', '')),
                
                # Patient information
                'patient_id': str(getattr(ds, 'PatientID', '')),
                'patient_name': str(getattr(ds, 'PatientName', '')),
                'patient_birth_date': self._format_dicom_date(getattr(ds, 'PatientBirthDate', '')),
                'patient_sex': str(getattr(ds, 'PatientSex', '')),
                'patient_age': str(getattr(ds, 'PatientAge', '')),
                
                # Study information
                'study_date': self._format_dicom_date(getattr(ds, 'StudyDate', '')),
                'study_time': self._format_dicom_time(getattr(ds, 'StudyTime', '')),
                'study_description': str(getattr(ds, 'StudyDescription', '')),
                'study_id': str(getattr(ds, 'StudyID', '')),
                'accession_number': str(getattr(ds, 'AccessionNumber', '')),
                
                # Series information\n                'series_number': self._safe_int(getattr(ds, 'SeriesNumber', None)),
                'series_description': str(getattr(ds, 'SeriesDescription', '')),
                'series_date': self._format_dicom_date(getattr(ds, 'SeriesDate', '')),
                'series_time': self._format_dicom_time(getattr(ds, 'SeriesTime', '')),
                
                # Image information
                'instance_number': self._safe_int(getattr(ds, 'InstanceNumber', None)),
                'image_type': str(getattr(ds, 'ImageType', '')),
                'modality': str(getattr(ds, 'Modality', '')),
                'body_part_examined': str(getattr(ds, 'BodyPartExamined', '')),
                
                # Technical parameters
                'rows': self._safe_int(getattr(ds, 'Rows', None)),
                'columns': self._safe_int(getattr(ds, 'Columns', None)),
                'pixel_spacing': str(getattr(ds, 'PixelSpacing', '')),
                'slice_thickness': self._safe_float(getattr(ds, 'SliceThickness', None)),
                'spacing_between_slices': self._safe_float(getattr(ds, 'SpacingBetweenSlices', None)),
                
                # Acquisition information
                'acquisition_date': self._format_dicom_date(getattr(ds, 'AcquisitionDate', '')),
                'acquisition_time': self._format_dicom_time(getattr(ds, 'AcquisitionTime', '')),
                'content_date': self._format_dicom_date(getattr(ds, 'ContentDate', '')),
                'content_time': self._format_dicom_time(getattr(ds, 'ContentTime', '')),
                
                # Equipment information
                'manufacturer': str(getattr(ds, 'Manufacturer', '')),
                'manufacturer_model_name': str(getattr(ds, 'ManufacturerModelName', '')),
                'device_serial_number': str(getattr(ds, 'DeviceSerialNumber', '')),
                'software_versions': str(getattr(ds, 'SoftwareVersions', '')),
                'station_name': str(getattr(ds, 'StationName', '')),
                
                # Institution information
                'institution_name': str(getattr(ds, 'InstitutionName', '')),
                'institution_address': str(getattr(ds, 'InstitutionAddress', '')),
                'institutional_department_name': str(getattr(ds, 'InstitutionalDepartmentName', '')),
                
                # Transfer syntax and technical info
                'transfer_syntax_uid': transfer_syntax['uid'],
                'transfer_syntax_name': transfer_syntax['name'],
                'file_type': file_type,
                
                # File system information
                'file_path': str(file_path),
                'file_name': file_path.name,
                'file_size': file_path.stat().st_size,
                'file_checksum': file_checksum,
                'file_modified_date': datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                
                # Processing metadata
                'processed_at': datetime.now().isoformat(),
                'scanner_version': '1.0'
            }
            
            return metadata
            
        except Exception as e:
            logger.error(f"Error extracting metadata from {file_path}: {e}")
            raise
    
    def _determine_file_type(self, sop_class_uid: str) -> str:
        """
        Determine file type based on SOP Class UID
        
        Args:
            sop_class_uid: SOP Class UID
            
        Returns:
            File type string (DICOM, DICONDE, or DICOS)
        """
        # DICONDE SOP Classes (Non-Destructive Evaluation)
        diconde_classes = [
            '1.2.840.10008.5.1.4.1.1.501.1',  # DICONDE CT Image Storage
            '1.2.840.10008.5.1.4.1.1.501.2',  # DICONDE Digital X-Ray Image Storage
            '1.2.840.10008.5.1.4.1.1.501.3',  # DICONDE Digital Radiography Image Storage
        ]
        
        # DICOS SOP Classes (Security)
        dicos_classes = [
            '1.2.840.10008.5.1.4.1.1.601.1',  # DICOS CT Image Storage
            '1.2.840.10008.5.1.4.1.1.601.2',  # DICOS Digital X-Ray Image Storage
        ]
        
        if sop_class_uid in diconde_classes:
            return 'DICONDE'
        elif sop_class_uid in dicos_classes:
            return 'DICOS'
        else:
            return 'DICOM'
    
    def _get_transfer_syntax_info(self, ds: Dataset) -> Dict[str, str]:
        """
        Get transfer syntax information from dataset
        
        Args:
            ds: DICOM dataset
            
        Returns:
            Dictionary with transfer syntax UID and name
        """
        try:
            # Try to get transfer syntax from file meta information
            if hasattr(ds, 'file_meta') and hasattr(ds.file_meta, 'TransferSyntaxUID'):
                ts_uid = str(ds.file_meta.TransferSyntaxUID)
            else:
                ts_uid = '1.2.840.10008.1.2'  # Implicit VR Little Endian (default)
            
            # Get human-readable name
            ts_name = self.special_transfer_syntaxes.get(ts_uid, 'Unknown Transfer Syntax')
            
            # Try to get name from pydicom if not in our special list
            if ts_name == 'Unknown Transfer Syntax':
                try:
                    from pydicom.uid import UID
                    uid_obj = UID(ts_uid)
                    ts_name = uid_obj.name if hasattr(uid_obj, 'name') else f'Transfer Syntax {ts_uid}'
                except:
                    ts_name = f'Transfer Syntax {ts_uid}'
            
            return {'uid': ts_uid, 'name': ts_name}
            
        except Exception:
            return {'uid': '1.2.840.10008.1.2', 'name': 'Implicit VR Little Endian'}
    
    async def _calculate_file_checksum(self, file_path: Path) -> str:
        """
        Calculate SHA-256 checksum of file
        
        Args:
            file_path: Path to file
            
        Returns:
            SHA-256 checksum as hex string
        """
        try:
            hash_sha256 = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()
        except Exception:
            return ''
    
    def _format_dicom_date(self, dicom_date: Any) -> Optional[str]:
        """Format DICOM date to ISO format"""
        try:
            if not dicom_date:
                return None
            date_str = str(dicom_date)
            if len(date_str) == 8:  # YYYYMMDD
                return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            return date_str
        except:
            return None
    
    def _format_dicom_time(self, dicom_time: Any) -> Optional[str]:
        """Format DICOM time to ISO format"""
        try:
            if not dicom_time:
                return None
            time_str = str(dicom_time)
            if len(time_str) >= 6:  # HHMMSS or HHMMSS.ffffff
                return f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:]}"
            return time_str
        except:
            return None
    
    def _safe_int(self, value: Any) -> Optional[int]:
        """Safely convert value to int"""
        try:
            return int(value) if value is not None else None
        except:
            return None
    
    def _safe_float(self, value: Any) -> Optional[float]:
        """Safely convert value to float"""
        try:
            return float(value) if value is not None else None
        except:
            return None
    
    async def _is_duplicate(self, sop_instance_uid: str) -> bool:
        """
        Check if SOP Instance UID already exists in database
        
        Args:
            sop_instance_uid: SOP Instance UID to check
            
        Returns:
            True if duplicate exists, False otherwise
        """
        try:
            if not sop_instance_uid:
                return False
                
            query = "SELECT COUNT(*) as count FROM dicom_metadata WHERE sop_instance_uid = ?"
            result = await self.db_manager.execute_query(query, (sop_instance_uid,))
            
            if result and len(result) > 0:
                count = result[0].get('count', 0)
                return count > 0
            
            return False
            
        except Exception:
            return False
    
    async def _insert_metadata(self, metadata: Dict[str, Any]):
        """
        Insert metadata into database
        
        Args:
            metadata: Metadata dictionary to insert
        """
        try:
            query = """
                INSERT OR REPLACE INTO dicom_metadata (
                    sop_instance_uid, sop_class_uid, study_instance_uid, series_instance_uid,
                    patient_id, patient_name, patient_birth_date, patient_sex, patient_age,
                    study_date, study_time, study_description, study_id, accession_number,
                    series_number, series_description, series_date, series_time,
                    instance_number, image_type, modality, body_part_examined,
                    rows, columns, pixel_spacing, slice_thickness, spacing_between_slices,
                    acquisition_date, acquisition_time, content_date, content_time,
                    manufacturer, manufacturer_model_name, device_serial_number, 
                    software_versions, station_name,
                    institution_name, institution_address, institutional_department_name,
                    transfer_syntax_uid, transfer_syntax_name, file_type,
                    file_path, file_name, file_size, file_checksum, file_modified_date,
                    processed_at, scanner_version
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """
            
            values = tuple(metadata.values())
            await self.db_manager.execute_query(query, values)
            
        except Exception as e:
            logger.error(f"Error inserting metadata: {e}")
            raise
    
    async def _ensure_dicom_tables(self):
        """Ensure DICOM metadata tables exist"""
        create_table_query = """
            CREATE TABLE IF NOT EXISTS dicom_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                -- Core DICOM identifiers
                sop_instance_uid TEXT UNIQUE NOT NULL,
                sop_class_uid TEXT,
                study_instance_uid TEXT,
                series_instance_uid TEXT,
                -- Patient information
                patient_id TEXT,
                patient_name TEXT,
                patient_birth_date TEXT,
                patient_sex TEXT,
                patient_age TEXT,
                -- Study information
                study_date TEXT,
                study_time TEXT,
                study_description TEXT,
                study_id TEXT,
                accession_number TEXT,
                -- Series information
                series_number INTEGER,
                series_description TEXT,
                series_date TEXT,
                series_time TEXT,
                -- Image information
                instance_number INTEGER,
                image_type TEXT,
                modality TEXT,
                body_part_examined TEXT,
                -- Technical parameters
                rows INTEGER,
                columns INTEGER,
                pixel_spacing TEXT,
                slice_thickness REAL,
                spacing_between_slices REAL,
                -- Acquisition information
                acquisition_date TEXT,
                acquisition_time TEXT,
                content_date TEXT,
                content_time TEXT,
                -- Equipment information
                manufacturer TEXT,
                manufacturer_model_name TEXT,
                device_serial_number TEXT,
                software_versions TEXT,
                station_name TEXT,
                -- Institution information
                institution_name TEXT,
                institution_address TEXT,
                institutional_department_name TEXT,
                -- Transfer syntax and file type
                transfer_syntax_uid TEXT,
                transfer_syntax_name TEXT,
                file_type TEXT,
                -- File system information
                file_path TEXT NOT NULL,
                file_name TEXT,
                file_size INTEGER,
                file_checksum TEXT,
                file_modified_date TEXT,
                -- Processing metadata
                processed_at TEXT,
                scanner_version TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """
        
        await self.db_manager.execute_query(create_table_query)
        
        # Create indexes for common queries
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_sop_instance_uid ON dicom_metadata(sop_instance_uid)",
            "CREATE INDEX IF NOT EXISTS idx_patient_id ON dicom_metadata(patient_id)",
            "CREATE INDEX IF NOT EXISTS idx_study_instance_uid ON dicom_metadata(study_instance_uid)",
            "CREATE INDEX IF NOT EXISTS idx_series_instance_uid ON dicom_metadata(series_instance_uid)",
            "CREATE INDEX IF NOT EXISTS idx_study_date ON dicom_metadata(study_date)",
            "CREATE INDEX IF NOT EXISTS idx_modality ON dicom_metadata(modality)",
            "CREATE INDEX IF NOT EXISTS idx_file_type ON dicom_metadata(file_type)",
            "CREATE INDEX IF NOT EXISTS idx_institution_name ON dicom_metadata(institution_name)"
        ]
        
        for index_query in indexes:
            await self.db_manager.execute_query(index_query)
    
    def get_scan_progress(self) -> Dict[str, Any]:
        """Get current scan progress"""
        progress = self.scan_progress.copy()
        
        if progress['start_time'] and progress['end_time']:
            duration = progress['end_time'] - progress['start_time']
            progress['duration_seconds'] = duration.total_seconds()
        elif progress['start_time']:
            duration = datetime.now() - progress['start_time']
            progress['duration_seconds'] = duration.total_seconds()
        
        # Calculate percentage
        if progress['total_files'] > 0:
            progress['percentage_complete'] = (progress['scanned_files'] / progress['total_files']) * 100
        else:
            progress['percentage_complete'] = 0
        
        return progress


__all__ = ['DICOMDirectoryScanner']
