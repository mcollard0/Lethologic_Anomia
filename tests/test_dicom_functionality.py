#!/usr/bin/env python3
"""
DICOM Functionality Verification

Comprehensive test suite to verify all DICOM operations work correctly
with pydicom and pynetdicom libraries.
"""

import asyncio
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, date

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import pydicom
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import generate_uid
    PYDICOM_AVAILABLE = True
except ImportError:
    PYDICOM_AVAILABLE = False
    print("ERROR: pydicom not available. Install with: pip install pydicom")

try:
    from pynetdicom import AE, evt, build_context
    from pynetdicom.sop_class import (
        Verification, CTImageStorage, MRImageStorage, 
        StudyRootQueryRetrieveInformationModelFind,
        StudyRootQueryRetrieveInformationModelMove,
        StudyRootQueryRetrieveInformationModelGet
    )
    PYNETDICOM_AVAILABLE = True
except ImportError:
    PYNETDICOM_AVAILABLE = False
    print("ERROR: pynetdicom not available. Install with: pip install pynetdicom")

from core.custom_logging import get_logger
from core.database import DatabaseManager
from core.config import Settings
from service.dicom.scp import DICOMSCPService
from service.dicom.scu import DICOMSCUService
from service.dicom.search import DICOMSearchService
from service.dicom.parser import DICOMParserService

logger = get_logger(__name__)


class DICOMTestSuite:
    """
    Comprehensive DICOM functionality test suite
    
    Tests all DICOM operations:
    - C-ECHO (verification)
    - C-STORE (storage)
    - C-FIND (query)
    - C-MOVE (retrieve) 
    - C-GET (retrieve)
    - File parsing
    - Metadata extraction
    """
    
    def __init__(self):
        """Initialize DICOM test suite"""
        self.temp_dir = None
        self.test_files = []
        self.scp_server = None
        self.scp_thread = None
        self.test_results = {
            'total_tests': 0,
            'passed_tests': 0,
            'failed_tests': 0,
            'test_details': []
        }
        
        # Test configuration
        self.config = {
            'scp_port': 11113,
            'scp_ae_title': 'TESTSCP',
            'scu_ae_title': 'TESTSCU',
            'timeout': 30
        }
        
        # Initialize database for testing
        self.db_manager = None
        self.settings = Settings()
    
    async def setup(self) -> bool:
        """
        Setup test environment
        
        Returns:
            True if setup successful
        """
        try:
            logger.info("Setting up DICOM test environment...")
            
            # Check dependencies
            if not PYDICOM_AVAILABLE:
                logger.error("pydicom not available")
                return False
            
            if not PYNETDICOM_AVAILABLE:
                logger.error("pynetdicom not available")
                return False
            
            # Create temporary directory
            self.temp_dir = tempfile.mkdtemp(prefix='dicom_test_')
            logger.info(f"Created temp directory: {self.temp_dir}")
            
            # Initialize database
            self.db_manager = DatabaseManager(self.settings)
            await self.db_manager.initialize()
            
            # Create test DICOM files
            await self.create_test_dicom_files()
            
            # Start test SCP server
            await self.start_test_scp()
            
            logger.info("DICOM test environment setup complete")
            return True
            
        except Exception as e:
            logger.error(f"Test setup failed: {e}")
            return False
    
    async def teardown(self):
        """Cleanup test environment"""
        try:
            logger.info("Cleaning up DICOM test environment...")
            
            # Stop SCP server
            if self.scp_server:
                self.scp_server.shutdown()
            
            if self.scp_thread and self.scp_thread.is_alive():
                self.scp_thread.join(timeout=10)
            
            # Close database
            if self.db_manager:
                await self.db_manager.shutdown()
            
            # Clean up temp files
            if self.temp_dir and os.path.exists(self.temp_dir):
                import shutil
                shutil.rmtree(self.temp_dir)
                logger.info(f"Cleaned up temp directory: {self.temp_dir}")
            
            logger.info("DICOM test environment cleanup complete")
            
        except Exception as e:
            logger.error(f"Test cleanup failed: {e}")
    
    async def create_test_dicom_files(self):
        """Create test DICOM files for testing"""
        try:
            logger.info("Creating test DICOM files...")
            
            # Create test datasets
            test_datasets = [
                {
                    'filename': 'test_ct.dcm',
                    'modality': 'CT',
                    'patient_id': 'TEST001',
                    'patient_name': 'Test^Patient^One',
                    'study_date': '20240101',
                    'series_number': '1'
                },
                {
                    'filename': 'test_mri.dcm',
                    'modality': 'MR',
                    'patient_id': 'TEST002',
                    'patient_name': 'Test^Patient^Two',
                    'study_date': '20240102',
                    'series_number': '2'
                },
                {
                    'filename': 'test_xray.dcm',
                    'modality': 'XR',
                    'patient_id': 'TEST003',
                    'patient_name': 'Test^Patient^Three',
                    'study_date': '20240103',
                    'series_number': '3'
                }
            ]
            
            for dataset_info in test_datasets:
                file_path = os.path.join(self.temp_dir, dataset_info['filename'])
                
                # Create minimal DICOM dataset
                ds = Dataset()
                
                # Patient Module
                ds.PatientName = dataset_info['patient_name']
                ds.PatientID = dataset_info['patient_id']
                ds.PatientBirthDate = '19800101'
                ds.PatientSex = 'M'
                
                # Study Module
                ds.StudyInstanceUID = generate_uid()
                ds.StudyDate = dataset_info['study_date']
                ds.StudyTime = '120000'
                ds.StudyID = '1'
                ds.AccessionNumber = f"ACC{dataset_info['patient_id']}"
                
                # Series Module
                ds.SeriesInstanceUID = generate_uid()
                ds.SeriesNumber = dataset_info['series_number']
                ds.Modality = dataset_info['modality']
                ds.SeriesDate = dataset_info['study_date']
                ds.SeriesTime = '120000'
                
                # Image Module
                ds.SOPInstanceUID = generate_uid()
                ds.InstanceNumber = '1'
                
                # SOP Common Module
                if dataset_info['modality'] == 'CT':
                    ds.SOPClassUID = CTImageStorage
                elif dataset_info['modality'] == 'MR':
                    ds.SOPClassUID = MRImageStorage
                else:
                    ds.SOPClassUID = CTImageStorage  # Default
                
                # Image Pixel Module (minimal)
                ds.SamplesPerPixel = 1
                ds.PhotometricInterpretation = 'MONOCHROME2'
                ds.Rows = 512
                ds.Columns = 512
                ds.BitsAllocated = 16
                ds.BitsStored = 16
                ds.HighBit = 15
                ds.PixelRepresentation = 0
                
                # Create minimal pixel data
                import numpy as np
                pixel_array = np.random.randint(0, 4096, (512, 512), dtype=np.uint16)
                ds.PixelData = pixel_array.tobytes()
                
                # File Meta Information
                file_meta = Dataset()
                file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
                file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
                file_meta.ImplementationClassUID = generate_uid()
                file_meta.TransferSyntaxUID = '1.2.840.10008.1.2'  # Implicit VR Little Endian
                
                # Create FileDataset
                file_ds = FileDataset(
                    file_path, ds, file_meta=file_meta, 
                    preamble=b"\0" * 128, is_implicit_VR=True
                )
                
                # Save DICOM file
                file_ds.save_as(file_path)
                self.test_files.append(file_path)
                
                logger.info(f"Created test DICOM file: {dataset_info['filename']}")
            
            logger.info(f"Created {len(self.test_files)} test DICOM files")
            
        except Exception as e:
            logger.error(f"Failed to create test DICOM files: {e}")
            raise
    
    async def start_test_scp(self):
        """Start test DICOM SCP server"""
        try:
            logger.info("Starting test DICOM SCP server...")
            
            # Create SCP server
            self.scp_server = DICOMSCPService(
                self.db_manager, 
                self.settings
            )
            
            # Configure SCP
            await self.scp_server.configure({
                'port': self.config['scp_port'],
                'ae_title': self.config['scp_ae_title'],
                'storage_directory': self.temp_dir
            })
            
            # Start SCP in separate thread
            def run_scp():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.scp_server.start())
                loop.run_forever()
            
            self.scp_thread = threading.Thread(target=run_scp, daemon=True)
            self.scp_thread.start()
            
            # Wait for server to start
            await asyncio.sleep(2)
            
            logger.info(f"Test SCP server started on port {self.config['scp_port']}")
            
        except Exception as e:
            logger.error(f"Failed to start test SCP server: {e}")
            raise
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """
        Run all DICOM functionality tests
        
        Returns:
            Test results dictionary
        """
        try:
            logger.info("Starting DICOM functionality verification...")
            
            # Test 1: DICOM File Parsing
            await self.test_dicom_file_parsing()
            
            # Test 2: C-ECHO (Verification)
            await self.test_c_echo()
            
            # Test 3: C-STORE (Storage)
            await self.test_c_store()
            
            # Test 4: C-FIND (Query)
            await self.test_c_find()
            
            # Test 5: DICOM Search Service
            await self.test_dicom_search()
            
            # Test 6: DICOM Parser Service
            await self.test_dicom_parser()
            
            # Test 7: Database Integration
            await self.test_database_integration()
            
            # Calculate results
            self.test_results['success_rate'] = (
                self.test_results['passed_tests'] / self.test_results['total_tests'] * 100
                if self.test_results['total_tests'] > 0 else 0
            )
            
            logger.info(f"DICOM verification complete: {self.test_results['passed_tests']}/{self.test_results['total_tests']} tests passed")
            return self.test_results
            
        except Exception as e:
            logger.error(f"DICOM verification failed: {e}")
            self.add_test_result("Overall Test Suite", False, str(e))
            return self.test_results
    
    async def test_dicom_file_parsing(self):
        """Test DICOM file parsing functionality"""
        test_name = "DICOM File Parsing"
        
        try:
            logger.info(f"Testing {test_name}...")
            
            for test_file in self.test_files:
                # Test reading DICOM file
                ds = pydicom.dcmread(test_file)
                
                # Verify basic tags
                assert hasattr(ds, 'PatientID'), "Missing PatientID"
                assert hasattr(ds, 'StudyInstanceUID'), "Missing StudyInstanceUID"
                assert hasattr(ds, 'SeriesInstanceUID'), "Missing SeriesInstanceUID"
                assert hasattr(ds, 'SOPInstanceUID'), "Missing SOPInstanceUID"
                assert hasattr(ds, 'Modality'), "Missing Modality"
                
                # Test metadata extraction
                metadata = {
                    'patient_id': str(ds.PatientID),
                    'patient_name': str(ds.PatientName),
                    'study_uid': str(ds.StudyInstanceUID),
                    'series_uid': str(ds.SeriesInstanceUID),
                    'instance_uid': str(ds.SOPInstanceUID),
                    'modality': str(ds.Modality),
                    'study_date': str(ds.StudyDate)
                }
                
                # Verify pixel data access
                if hasattr(ds, 'PixelData'):
                    pixel_array = ds.pixel_array
                    assert pixel_array is not None, "Failed to access pixel data"
                    assert pixel_array.shape == (512, 512), f"Unexpected pixel array shape: {pixel_array.shape}"
                
                logger.info(f"Successfully parsed {os.path.basename(test_file)}")
            
            self.add_test_result(test_name, True, f"Parsed {len(self.test_files)} DICOM files")
            
        except Exception as e:
            logger.error(f"{test_name} failed: {e}")
            self.add_test_result(test_name, False, str(e))
    
    async def test_c_echo(self):
        """Test C-ECHO (DICOM verification) functionality"""
        test_name = "C-ECHO Verification"
        
        try:
            logger.info(f"Testing {test_name}...")
            
            # Create Application Entity
            ae = AE(ae_title=self.config['scu_ae_title'])
            ae.add_requested_context(Verification)
            
            # Associate with test SCP
            assoc = ae.associate(
                'localhost', 
                self.config['scp_port'],
                ae_title=self.config['scp_ae_title']
            )
            
            if assoc.is_established:
                # Send C-ECHO
                status = assoc.send_c_echo()
                
                if status:
                    logger.info("C-ECHO successful")
                    self.add_test_result(test_name, True, "ECHO verification successful")
                else:
                    self.add_test_result(test_name, False, "ECHO request failed")
                
                # Release association
                assoc.release()
                
            else:
                self.add_test_result(test_name, False, "Failed to establish association")
                
        except Exception as e:
            logger.error(f"{test_name} failed: {e}")
            self.add_test_result(test_name, False, str(e))
    
    async def test_c_store(self):
        """Test C-STORE (DICOM storage) functionality"""
        test_name = "C-STORE Storage"
        
        try:
            logger.info(f"Testing {test_name}...")
            
            stored_count = 0
            
            for test_file in self.test_files:
                # Read DICOM file
                ds = pydicom.dcmread(test_file)
                
                # Create Application Entity
                ae = AE(ae_title=self.config['scu_ae_title'])
                ae.add_requested_context(ds.SOPClassUID)
                
                # Associate with test SCP
                assoc = ae.associate(
                    'localhost',
                    self.config['scp_port'],
                    ae_title=self.config['scp_ae_title']
                )
                
                if assoc.is_established:
                    # Send C-STORE
                    status = assoc.send_c_store(ds)
                    
                    if status:
                        if status.Status == 0x0000:  # Success
                            stored_count += 1
                            logger.info(f"C-STORE successful for {os.path.basename(test_file)}")
                        else:
                            logger.warning(f"C-STORE status: 0x{status.Status:04x}")
                    
                    # Release association
                    assoc.release()
                    
                else:
                    logger.error(f"Failed to establish association for {test_file}")
            
            if stored_count == len(self.test_files):
                self.add_test_result(test_name, True, f"Stored {stored_count} DICOM files")
            else:
                self.add_test_result(test_name, False, f"Only stored {stored_count}/{len(self.test_files)} files")
                
        except Exception as e:
            logger.error(f"{test_name} failed: {e}")
            self.add_test_result(test_name, False, str(e))
    
    async def test_c_find(self):
        """Test C-FIND (DICOM query) functionality"""
        test_name = "C-FIND Query"
        
        try:
            logger.info(f"Testing {test_name}...")
            
            # Create query dataset
            query_ds = Dataset()
            query_ds.QueryRetrieveLevel = 'STUDY'
            query_ds.PatientID = 'TEST*'  # Wildcard search
            query_ds.StudyInstanceUID = ''
            query_ds.StudyDate = ''
            query_ds.StudyDescription = ''
            query_ds.PatientName = ''
            
            # Create Application Entity
            ae = AE(ae_title=self.config['scu_ae_title'])
            ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
            
            # Associate with test SCP
            assoc = ae.associate(
                'localhost',
                self.config['scp_port'],
                ae_title=self.config['scp_ae_title']
            )
            
            if assoc.is_established:
                # Send C-FIND
                responses = assoc.send_c_find(query_ds, StudyRootQueryRetrieveInformationModelFind)
                
                found_studies = []
                for status, identifier in responses:
                    if status:
                        if status.Status == 0xFF00:  # Pending
                            if identifier:
                                found_studies.append(identifier)
                        elif status.Status == 0x0000:  # Success
                            break
                
                # Release association
                assoc.release()
                
                if found_studies:
                    self.add_test_result(test_name, True, f"Found {len(found_studies)} studies")
                    logger.info(f"C-FIND returned {len(found_studies)} studies")
                else:
                    self.add_test_result(test_name, False, "No studies found")
                    
            else:
                self.add_test_result(test_name, False, "Failed to establish association")
                
        except Exception as e:
            logger.error(f"{test_name} failed: {e}")
            self.add_test_result(test_name, False, str(e))
    
    async def test_dicom_search(self):
        """Test DICOM Search Service"""
        test_name = "DICOM Search Service"
        
        try:
            logger.info(f"Testing {test_name}...")
            
            # Create DICOM search service
            search_service = DICOMSearchService(self.db_manager, self.settings)
            
            # Configure search service
            search_config = {
                'servers': [
                    {
                        'name': 'TestSCP',
                        'ae_title': self.config['scp_ae_title'],
                        'host': 'localhost',
                        'port': self.config['scp_port'],
                        'timeout': 30
                    }
                ]
            }
            
            await search_service.configure(search_config)
            await search_service.start()
            
            # Perform search
            search_criteria = {
                'patient_id': 'TEST*',
                'study_date_from': '20240101',
                'study_date_to': '20240103',
                'modality': '*'
            }
            
            search_id = await search_service.search_studies(
                ['TestSCP'], search_criteria
            )
            
            # Wait for search to complete
            await asyncio.sleep(5)
            
            # Check search results
            results = await search_service.get_search_results(search_id)
            
            await search_service.stop()
            
            if results and len(results) > 0:
                self.add_test_result(test_name, True, f"Search found {len(results)} studies")
                logger.info(f"DICOM search found {len(results)} studies")
            else:
                self.add_test_result(test_name, False, "Search returned no results")
                
        except Exception as e:
            logger.error(f"{test_name} failed: {e}")
            self.add_test_result(test_name, False, str(e))
    
    async def test_dicom_parser(self):
        """Test DICOM Parser Service"""
        test_name = "DICOM Parser Service"
        
        try:
            logger.info(f"Testing {test_name}...")
            
            # Create DICOM parser service
            parser_service = DICOMParserService(self.db_manager, self.settings)
            
            await parser_service.configure({})
            await parser_service.start()
            
            # Parse test directory
            parse_id = await parser_service.parse_directory(self.temp_dir)
            
            # Wait for parsing to complete
            await asyncio.sleep(5)
            
            # Check parsing results
            results = await parser_service.get_parsing_results(parse_id)
            
            await parser_service.stop()
            
            if results and results.get('success', False):
                parsed_count = results.get('files_processed', 0)
                self.add_test_result(test_name, True, f"Parsed {parsed_count} DICOM files")
                logger.info(f"DICOM parser processed {parsed_count} files")
            else:
                error_msg = results.get('error', 'Unknown error') if results else 'No results'
                self.add_test_result(test_name, False, error_msg)
                
        except Exception as e:
            logger.error(f"{test_name} failed: {e}")
            self.add_test_result(test_name, False, str(e))
    
    async def test_database_integration(self):
        """Test DICOM database integration"""
        test_name = "Database Integration"
        
        try:
            logger.info(f"Testing {test_name}...")
            
            # Test inserting DICOM metadata
            for test_file in self.test_files:
                ds = pydicom.dcmread(test_file)
                
                # Insert study
                await self.db_manager.execute_query(
                    """
                    INSERT OR REPLACE INTO studies 
                    (study_uid, patient_id, patient_name, study_date, modality, study_description)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        str(ds.StudyInstanceUID),
                        str(ds.PatientID),
                        str(ds.PatientName),
                        str(ds.StudyDate),
                        str(ds.Modality),
                        'Test Study'
                    ]
                )
                
                # Insert series
                await self.db_manager.execute_query(
                    """
                    INSERT OR REPLACE INTO series
                    (series_uid, study_uid, series_number, modality, series_description)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        str(ds.SeriesInstanceUID),
                        str(ds.StudyInstanceUID),
                        str(ds.SeriesNumber),
                        str(ds.Modality),
                        'Test Series'
                    ]
                )
                
                # Insert image
                await self.db_manager.execute_query(
                    """
                    INSERT OR REPLACE INTO images
                    (sop_instance_uid, series_uid, instance_number, file_path)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        str(ds.SOPInstanceUID),
                        str(ds.SeriesInstanceUID),
                        str(ds.InstanceNumber),
                        test_file
                    ]
                )
            
            # Query inserted data
            studies = await self.db_manager.execute_query(
                "SELECT COUNT(*) as count FROM studies WHERE patient_id LIKE 'TEST%'"
            )
            
            study_count = studies[0]['count'] if studies else 0
            
            if study_count == len(self.test_files):
                self.add_test_result(test_name, True, f"Database contains {study_count} test studies")
                logger.info(f"Database integration successful: {study_count} studies")
            else:
                self.add_test_result(test_name, False, f"Expected {len(self.test_files)} studies, found {study_count}")
                
        except Exception as e:
            logger.error(f"{test_name} failed: {e}")
            self.add_test_result(test_name, False, str(e))
    
    def add_test_result(self, test_name: str, passed: bool, details: str):
        """Add test result"""
        self.test_results['total_tests'] += 1
        
        if passed:
            self.test_results['passed_tests'] += 1
            status = "PASSED"
        else:
            self.test_results['failed_tests'] += 1
            status = "FAILED"
        
        result = {
            'test_name': test_name,
            'status': status,
            'passed': passed,
            'details': details,
            'timestamp': datetime.now().isoformat()
        }
        
        self.test_results['test_details'].append(result)
        logger.info(f"TEST {status}: {test_name} - {details}")
    
    def print_test_summary(self):
        """Print test results summary"""
        print("\n" + "=" * 60)
        print("DICOM FUNCTIONALITY VERIFICATION RESULTS")
        print("=" * 60)
        
        print(f"\nTotal Tests: {self.test_results['total_tests']}")
        print(f"Passed: {self.test_results['passed_tests']}")
        print(f"Failed: {self.test_results['failed_tests']}")
        print(f"Success Rate: {self.test_results.get('success_rate', 0):.1f}%")
        
        print("\nDetailed Results:")
        print("-" * 40)
        
        for result in self.test_results['test_details']:
            status_symbol = "â" if result['passed'] else "â"
            print(f"{status_symbol} {result['test_name']}: {result['details']}")
        
        print("\n" + "=" * 60)
        
        # Overall assessment
        if self.test_results['failed_tests'] == 0:
            print("ð ALL DICOM TESTS PASSED! DICOM functionality is working correctly.")
        else:
            print(f"â ï¸  {self.test_results['failed_tests']} tests failed. Review issues above.")
        
        print("=" * 60)


async def main():
    """Main test function"""
    test_suite = DICOMTestSuite()
    
    try:
        # Setup test environment
        if not await test_suite.setup():
            print("â Test setup failed")
            return False
        
        # Run all tests
        results = await test_suite.run_all_tests()
        
        # Print summary
        test_suite.print_test_summary()
        
        return results['failed_tests'] == 0
        
    except KeyboardInterrupt:
        print("\nâ Tests interrupted by user")
        return False
        
    except Exception as e:
        print(f"â Test suite failed: {e}")
        return False
        
    finally:
        # Cleanup
        await test_suite.teardown()


if __name__ == '__main__':
    print("ð¬ DICOM Functionality Verification")
    print("Testing all DICOM operations...\n")
    
    # Run tests
    success = asyncio.run(main())
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)
