#!/usr/bin/env python3
"""
DICOM Operations Test Script

This script performs comprehensive testing of DICOM operations including:
- C-STORE: Send DICOM images to SCP
- C-GET: Retrieve DICOM images from SCP
- C-MOVE: Move DICOM images between SCPs
- C-FIND: Query DICOM studies and series

Supports both pynetdicom (if available) and dcmtk command-line tools.
"""

import asyncio
import os
import sys
import json
import time
import socket
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import subprocess
import tempfile
import uuid
import random

# Try to import pydicom for DICOM file creation
try:
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import generate_uid, ExplicitVRLittleEndian
    from pydicom.filewriter import dcmwrite
    import numpy as np
    PYDICOM_AVAILABLE = True
except ImportError:
    PYDICOM_AVAILABLE = False
    print("⚠️  pydicom not available - will use dcmtk tools only")

# Try to import pynetdicom for network operations
try:
    from pynetdicom import AE, debug_logger
    from pynetdicom.sop_class import *
    PYNETDICOM_AVAILABLE = True
except ImportError:
    PYNETDICOM_AVAILABLE = False
    print("⚠️  pynetdicom not available - will use dcmtk tools only")


class DICOMTestSuite:
    """DICOM Operations Test Suite"""
    
    def __init__(self):
        self.test_data_dir = Path("test_dicom_data")
        self.test_data_dir.mkdir(exist_ok=True)
        
        # SCP configurations
        self.scp1_config = {
            'ae_title': 'MIGRATION_SCP1',
            'host': 'localhost',
            'port': 11112
        }
        
        self.scp2_config = {
            'ae_title': 'MIGRATION_SCP2',
            'host': 'localhost',
            'port': 11114
        }
        
        self.test_results = []
    
    def log_result(self, operation: str, success: bool, message: str, duration: float = 0.0):
        """Log test result"""
        status = "✅" if success else "❌"
        result = {
            'operation': operation,
            'success': success,
            'message': message,
            'duration': duration,
            'timestamp': datetime.now().isoformat()
        }
        self.test_results.append(result)
        print(f"{status} {operation}: {message} ({duration:.2f}s)")
    
    def create_test_dicom_files(self, count: int = 5) -> List[Path]:
        """Create test DICOM files"""
        if not PYDICOM_AVAILABLE:
            print("⚠️  Cannot create test DICOM files without pydicom")
            return []
        
        print(f"📄 Creating {count} test DICOM files...")
        
        files = []
        base_study_uid = generate_uid()
        base_series_uid = generate_uid()
        
        for i in range(count):
            try:
                # Create basic DICOM dataset
                ds = Dataset()
                
                # Patient information
                ds.PatientName = f"Test^Patient^{i+1}"
                ds.PatientID = f"TEST{i+1:03d}"
                ds.PatientBirthDate = "19900101"
                ds.PatientSex = "O"
                
                # Study information
                ds.StudyInstanceUID = base_study_uid
                ds.StudyID = "TEST001"
                ds.StudyDate = datetime.now().strftime("%Y%m%d")
                ds.StudyTime = datetime.now().strftime("%H%M%S")
                ds.StudyDescription = "Test Study"
                ds.AccessionNumber = f"ACC{i+1:03d}"
                
                # Series information
                ds.SeriesInstanceUID = base_series_uid
                ds.SeriesNumber = str(i + 1)
                ds.SeriesDescription = f"Test Series {i+1}"
                ds.SeriesDate = datetime.now().strftime("%Y%m%d")
                ds.SeriesTime = datetime.now().strftime("%H%M%S")
                
                # Instance information
                ds.SOPInstanceUID = generate_uid()
                ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"  # CT Image Storage
                ds.InstanceNumber = str(i + 1)
                ds.ImageType = ["ORIGINAL", "PRIMARY", "AXIAL"]
                ds.Modality = "CT"
                
                # Image data (minimal)
                ds.Rows = 64
                ds.Columns = 64
                ds.BitsAllocated = 16
                ds.BitsStored = 16
                ds.HighBit = 15
                ds.PixelRepresentation = 0
                ds.SamplesPerPixel = 1
                ds.PhotometricInterpretation = "MONOCHROME2"
                
                # Create simple image data
                pixel_array = np.random.randint(0, 4096, (64, 64), dtype=np.uint16)
                ds.PixelData = pixel_array.tobytes()
                
                # Equipment information
                ds.Manufacturer = "Test Equipment"
                ds.ManufacturerModelName = "Test Model"
                ds.SoftwareVersions = "1.0"
                ds.StationName = "TEST_STATION"
                
                # Create FileDataset
                file_meta = Dataset()
                file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
                file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
                file_meta.ImplementationClassUID = generate_uid()
                file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
                
                filename = self.test_data_dir / f"test_image_{i+1:03d}.dcm"
                file_ds = FileDataset(str(filename), ds, file_meta=file_meta, preamble=b"\0" * 128)
                
                dcmwrite(filename, file_ds)
                files.append(filename)
                
            except Exception as e:
                print(f"❌ Failed to create test file {i+1}: {e}")
                continue
        
        print(f"✅ Created {len(files)} test DICOM files")
        return files
    
    def check_scp_connectivity(self, config: Dict[str, Any]) -> bool:
        """Check if SCP is reachable"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((config['host'], config['port']))
            sock.close()
            return result == 0
        except Exception:
            return False
    
    async def test_c_echo_pynetdicom(self, config: Dict[str, Any]) -> bool:
        """Test C-ECHO using pynetdicom"""
        if not PYNETDICOM_AVAILABLE:
            return False
        
        try:
            start_time = time.time()
            
            # Create Application Entity
            ae = AE()
            ae.add_requested_context('1.2.840.10008.1.1')  # Verification SOP Class
            
            # Associate with SCP
            assoc = ae.associate(config['host'], config['port'], ae_title=config['ae_title'])
            
            if assoc.is_established:
                # Send C-ECHO
                status = assoc.send_c_echo()
                assoc.release()
                
                duration = time.time() - start_time
                success = status.Status == 0x0000
                
                self.log_result(
                    f"C-ECHO to {config['ae_title']}", 
                    success, 
                    f"Status: 0x{status.Status:04X}" if success else "Failed",
                    duration
                )
                return success
            else:
                duration = time.time() - start_time
                self.log_result(
                    f"C-ECHO to {config['ae_title']}", 
                    False, 
                    "Association failed",
                    duration
                )
                return False
                
        except Exception as e:
            duration = time.time() - start_time
            self.log_result(f"C-ECHO to {config['ae_title']}", False, str(e), duration)
            return False
    
    def test_c_echo_dcmtk(self, config: Dict[str, Any]) -> bool:
        """Test C-ECHO using dcmtk echoscu"""
        try:
            start_time = time.time()
            
            cmd = [
                'echoscu',
                '-aet', 'TEST_CLIENT',
                '-aec', config['ae_title'],
                config['host'],
                str(config['port'])
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            duration = time.time() - start_time
            success = result.returncode == 0
            
            self.log_result(
                f"C-ECHO to {config['ae_title']} (dcmtk)", 
                success, 
                "Success" if success else f"Error: {result.stderr}",
                duration
            )
            return success
            
        except FileNotFoundError:
            self.log_result(f"C-ECHO to {config['ae_title']} (dcmtk)", False, "echoscu not found", 0)
            return False
        except Exception as e:
            duration = time.time() - start_time
            self.log_result(f"C-ECHO to {config['ae_title']} (dcmtk)", False, str(e), duration)
            return False
    
    async def test_c_store_pynetdicom(self, config: Dict[str, Any], files: List[Path]) -> bool:
        """Test C-STORE using pynetdicom"""
        if not PYNETDICOM_AVAILABLE or not files:
            return False
        
        try:
            start_time = time.time()
            
            # Create Application Entity
            ae = AE()
            ae.add_requested_context('1.2.840.10008.5.1.4.1.1.2')  # CT Image Storage
            
            # Associate with SCP
            assoc = ae.associate(config['host'], config['port'], ae_title=config['ae_title'])
            
            if assoc.is_established:
                success_count = 0
                
                for file_path in files:
                    try:
                        from pydicom import dcmread
                        ds = dcmread(str(file_path))
                        status = assoc.send_c_store(ds)
                        
                        if status.Status == 0x0000:
                            success_count += 1
                        
                    except Exception as e:
                        print(f"  ❌ Failed to store {file_path.name}: {e}")
                        continue
                
                assoc.release()
                
                duration = time.time() - start_time
                success = success_count == len(files)
                
                self.log_result(
                    f"C-STORE to {config['ae_title']}", 
                    success, 
                    f"Stored {success_count}/{len(files)} files",
                    duration
                )
                return success
            else:
                duration = time.time() - start_time
                self.log_result(
                    f"C-STORE to {config['ae_title']}", 
                    False, 
                    "Association failed",
                    duration
                )
                return False
                
        except Exception as e:
            duration = time.time() - start_time
            self.log_result(f"C-STORE to {config['ae_title']}", False, str(e), duration)
            return False
    
    def test_c_store_dcmtk(self, config: Dict[str, Any], files: List[Path]) -> bool:
        """Test C-STORE using dcmtk storescu"""
        if not files:
            return False
        
        try:
            start_time = time.time()
            
            cmd = [
                'storescu',
                '-aet', 'TEST_CLIENT',
                '-aec', config['ae_title'],
                config['host'],
                str(config['port'])
            ] + [str(f) for f in files]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            duration = time.time() - start_time
            success = result.returncode == 0
            
            self.log_result(
                f"C-STORE to {config['ae_title']} (dcmtk)", 
                success, 
                f"Stored {len(files)} files" if success else f"Error: {result.stderr}",
                duration
            )
            return success
            
        except FileNotFoundError:
            self.log_result(f"C-STORE to {config['ae_title']} (dcmtk)", False, "storescu not found", 0)
            return False
        except Exception as e:
            duration = time.time() - start_time
            self.log_result(f"C-STORE to {config['ae_title']} (dcmtk)", False, str(e), duration)
            return False
    
    def test_c_find_dcmtk(self, config: Dict[str, Any]) -> bool:
        """Test C-FIND using dcmtk findscu"""
        try:
            start_time = time.time()
            
            cmd = [
                'findscu',
                '-aet', 'TEST_CLIENT',
                '-aec', config['ae_title'],
                '-S',  # Study level query
                '-k', 'QueryRetrieveLevel=STUDY',
                '-k', 'PatientName=',
                '-k', 'StudyInstanceUID=',
                '-k', 'StudyDescription=',
                config['host'],
                str(config['port'])
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            duration = time.time() - start_time
            success = result.returncode == 0
            
            # Count results
            studies_found = result.stdout.count('# Dicom-Data-Set')
            
            self.log_result(
                f"C-FIND to {config['ae_title']} (dcmtk)", 
                success, 
                f"Found {studies_found} studies" if success else f"Error: {result.stderr}",
                duration
            )
            return success
            
        except FileNotFoundError:
            self.log_result(f"C-FIND to {config['ae_title']} (dcmtk)", False, "findscu not found", 0)
            return False
        except Exception as e:
            duration = time.time() - start_time
            self.log_result(f"C-FIND to {config['ae_title']} (dcmtk)", False, str(e), duration)
            return False
    
    def test_c_move_dcmtk(self, src_config: Dict[str, Any], dest_config: Dict[str, Any]) -> bool:
        """Test C-MOVE using dcmtk movescu"""
        try:
            start_time = time.time()
            
            cmd = [
                'movescu',
                '-aet', 'TEST_CLIENT',
                '-aec', src_config['ae_title'],
                '-aem', dest_config['ae_title'],
                '-S',  # Study level move
                '-k', 'QueryRetrieveLevel=STUDY',
                '-k', 'PatientName=Test*',
                src_config['host'],
                str(src_config['port'])
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            duration = time.time() - start_time
            success = result.returncode == 0
            
            self.log_result(
                f"C-MOVE from {src_config['ae_title']} to {dest_config['ae_title']} (dcmtk)", 
                success, 
                "Move completed" if success else f"Error: {result.stderr}",
                duration
            )
            return success
            
        except FileNotFoundError:
            self.log_result(f"C-MOVE (dcmtk)", False, "movescu not found", 0)
            return False
        except Exception as e:
            duration = time.time() - start_time
            self.log_result(f"C-MOVE (dcmtk)", False, str(e), duration)
            return False
    
    def test_c_get_dcmtk(self, config: Dict[str, Any], output_dir: Path) -> bool:
        """Test C-GET using dcmtk getscu"""
        try:
            start_time = time.time()
            output_dir.mkdir(exist_ok=True)
            
            cmd = [
                'getscu',
                '-aet', 'TEST_CLIENT',
                '-aec', config['ae_title'],
                '-od', str(output_dir),
                '-S',  # Study level get
                '-k', 'QueryRetrieveLevel=STUDY',
                '-k', 'PatientName=Test*',
                config['host'],
                str(config['port'])
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            duration = time.time() - start_time
            success = result.returncode == 0
            
            # Count retrieved files
            retrieved_files = len(list(output_dir.glob('*.dcm')))
            
            self.log_result(
                f"C-GET from {config['ae_title']} (dcmtk)", 
                success, 
                f"Retrieved {retrieved_files} files" if success else f"Error: {result.stderr}",
                duration
            )
            return success
            
        except FileNotFoundError:
            self.log_result(f"C-GET from {config['ae_title']} (dcmtk)", False, "getscu not found", 0)
            return False
        except Exception as e:
            duration = time.time() - start_time
            self.log_result(f"C-GET from {config['ae_title']} (dcmtk)", False, str(e), duration)
            return False
    
    def check_dcmtk_tools(self) -> Dict[str, bool]:
        """Check availability of dcmtk tools"""
        tools = ['echoscu', 'storescu', 'findscu', 'movescu', 'getscu']
        availability = {}
        
        print("🔧 Checking dcmtk tools availability:")
        for tool in tools:
            try:
                result = subprocess.run([tool, '--version'], 
                                      capture_output=True, text=True, timeout=5)
                available = result.returncode == 0
                availability[tool] = available
                status = "✅" if available else "❌"
                print(f"  {status} {tool}")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                availability[tool] = False
                print(f"  ❌ {tool}")
        
        return availability
    
    async def run_comprehensive_test(self):
        """Run comprehensive DICOM test suite"""
        print("🏥 DICOM Operations Test Suite")
        print("=" * 50)
        
        # Check tool availability
        dcmtk_tools = self.check_dcmtk_tools()
        has_dcmtk = any(dcmtk_tools.values())
        
        print(f"\n📊 Available tools:")
        print(f"  pydicom: {'✅' if PYDICOM_AVAILABLE else '❌'}")
        print(f"  pynetdicom: {'✅' if PYNETDICOM_AVAILABLE else '❌'}")
        print(f"  dcmtk: {'✅' if has_dcmtk else '❌'}")
        
        if not (PYDICOM_AVAILABLE or PYNETDICOM_AVAILABLE or has_dcmtk):
            print("\n❌ No DICOM tools available. Please install pydicom/pynetdicom or dcmtk")
            return
        
        # Check SCP connectivity
        print(f"\n🔌 Checking SCP connectivity:")
        scp1_available = self.check_scp_connectivity(self.scp1_config)
        scp2_available = self.check_scp_connectivity(self.scp2_config)
        
        print(f"  {self.scp1_config['ae_title']} ({self.scp1_config['host']}:{self.scp1_config['port']}): {'✅' if scp1_available else '❌'}")
        print(f"  {self.scp2_config['ae_title']} ({self.scp2_config['host']}:{self.scp2_config['port']}): {'✅' if scp2_available else '❌'}")
        
        if not (scp1_available or scp2_available):
            print("\n❌ No SCPs are available. Please start the daemons first.")
            return
        
        # Create test data
        test_files = []
        if PYDICOM_AVAILABLE:
            test_files = self.create_test_dicom_files(5)
        
        print(f"\n🧪 Running DICOM Tests:")
        print("-" * 30)
        
        # Test C-ECHO
        if scp1_available:
            if PYNETDICOM_AVAILABLE:
                await self.test_c_echo_pynetdicom(self.scp1_config)
            if dcmtk_tools.get('echoscu', False):
                self.test_c_echo_dcmtk(self.scp1_config)
        
        if scp2_available:
            if PYNETDICOM_AVAILABLE:
                await self.test_c_echo_pynetdicom(self.scp2_config)
            if dcmtk_tools.get('echoscu', False):
                self.test_c_echo_dcmtk(self.scp2_config)
        
        # Test C-STORE
        if test_files and scp1_available:
            if PYNETDICOM_AVAILABLE:
                await self.test_c_store_pynetdicom(self.scp1_config, test_files)
            if dcmtk_tools.get('storescu', False):
                self.test_c_store_dcmtk(self.scp1_config, test_files)
        
        # Test C-FIND
        if scp1_available and dcmtk_tools.get('findscu', False):
            time.sleep(2)  # Allow time for storage to complete
            self.test_c_find_dcmtk(self.scp1_config)
        
        # Test C-GET
        if scp1_available and dcmtk_tools.get('getscu', False):
            output_dir = Path("retrieved_files")
            self.test_c_get_dcmtk(self.scp1_config, output_dir)
        
        # Test C-MOVE (if both SCPs available)
        if scp1_available and scp2_available and dcmtk_tools.get('movescu', False):
            self.test_c_move_dcmtk(self.scp1_config, self.scp2_config)
        
        # Print test summary
        self.print_test_summary()
    
    def print_test_summary(self):
        """Print test results summary"""
        print(f"\n📋 Test Summary:")
        print("=" * 50)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for r in self.test_results if r['success'])
        failed_tests = total_tests - passed_tests
        
        print(f"Total Tests: {total_tests}")
        print(f"✅ Passed: {passed_tests}")
        print(f"❌ Failed: {failed_tests}")
        print(f"Success Rate: {(passed_tests/total_tests*100):.1f}%" if total_tests > 0 else "N/A")
        
        if failed_tests > 0:
            print(f"\n❌ Failed Tests:")
            for result in self.test_results:
                if not result['success']:
                    print(f"  - {result['operation']}: {result['message']}")
        
        # Save detailed results
        results_file = Path("dicom_test_results.json")
        with open(results_file, 'w') as f:
            json.dump(self.test_results, f, indent=2)
        print(f"\n📄 Detailed results saved to: {results_file}")


async def main():
    """Main function"""
    print("🏥 Medical Imaging Migration Service - DICOM Operations Test")
    
    test_suite = DICOMTestSuite()
    await test_suite.run_comprehensive_test()


if __name__ == "__main__":
    asyncio.run(main())
