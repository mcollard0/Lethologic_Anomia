#!/usr/bin/env python3
"""
Simple DICOM Test Runner

Tests basic DICOM functionality without complex service imports.
Focuses on testing the core infrastructure we've built.
"""

import asyncio
import json
import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

import pydicom
from pydicom.dataset import Dataset
from pydicom.uid import generate_uid
from pynetdicom import AE
from pynetdicom.sop_class import Verification
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

class SimpleDICOMTester:
    """Simple DICOM tester for basic functionality"""
    
    def __init__(self):
        """Initialize the tester"""
        self.test_results = {
            'tests_run': 0,
            'tests_passed': 0,
            'tests_failed': 0,
            'test_details': []
        }
        
        # Test configuration
        self.config = {
            'scp1_host': '127.0.0.1',
            'scp1_port': 11112,
            'scp1_ae': 'MIGRATION_SCP1',
            'scp2_host': '127.0.0.1',
            'scp2_port': 11114,
            'scp2_ae': 'MIGRATION_SCP2',
            'qrscp_host': '127.0.0.1',
            'qrscp_port': 11116,
            'qrscp_ae': 'LETHOLOGIC_QR',
            'test_data_dir': Path('./test_dicom_simple')
        }
        
        # Test AE
        self.test_ae = AE(ae_title='SIMPLE_TEST_SCU')
        self.test_ae.add_requested_context(Verification)
    
    def record_test(self, name: str, success: bool, details: str, duration: float = 0.0):
        """Record test result"""
        self.test_results['tests_run'] += 1
        
        if success:
            self.test_results['tests_passed'] += 1
            status = "[green]PASS[/green]"
        else:
            self.test_results['tests_failed'] += 1
            status = "[red]FAIL[/red]"
        
        self.test_results['test_details'].append({
            'name': name,
            'success': success,
            'details': details,
            'duration': duration
        })
        
        console.print(f"{status} {name} ({duration:.2f}s): {details}")
    
    def test_dicom_services_running(self):
        """Test that DICOM services are running"""
        console.print("\n[bold blue]Testing DICOM Service Status[/bold blue]")
        
        services = [
            ('SCP1', self.config['scp1_host'], self.config['scp1_port'], self.config['scp1_ae']),
            ('SCP2', self.config['scp2_host'], self.config['scp2_port'], self.config['scp2_ae']),
            ('QRSCP', self.config['qrscp_host'], self.config['qrscp_port'], self.config['qrscp_ae'])
        ]
        
        for service_name, host, port, ae_title in services:
            start_time = time.time()
            
            try:
                # Test C-ECHO
                assoc = self.test_ae.associate(host, port, ae_title=ae_title)
                
                if assoc.is_established:
                    status = assoc.send_c_echo()
                    assoc.release()
                    
                    duration = time.time() - start_time
                    
                    if status.Status == 0x0000:
                        self.record_test(
                            f"C-ECHO {service_name}",
                            True,
                            f"Successfully connected to {host}:{port}",
                            duration
                        )
                    else:
                        self.record_test(
                            f"C-ECHO {service_name}",
                            False,
                            f"C-ECHO failed with status: {status.Status}",
                            duration
                        )
                else:
                    duration = time.time() - start_time
                    self.record_test(
                        f"C-ECHO {service_name}",
                        False,
                        f"Failed to establish association",
                        duration
                    )
                    
            except Exception as e:
                duration = time.time() - start_time
                self.record_test(
                    f"C-ECHO {service_name}",
                    False,
                    f"Exception: {e}",
                    duration
                )
    
    def test_dcmtk_tools(self):
        """Test dcmtk command line tools"""
        console.print("\n[bold blue]Testing DCMTK Tools[/bold blue]")
        
        # Test echoscu
        start_time = time.time()
        try:
            cmd = [
                '/usr/bin/echoscu',
                '-aet', 'SIMPLE_TEST_SCU',
                '-aec', self.config['scp1_ae'],
                self.config['scp1_host'],
                str(self.config['scp1_port'])
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            duration = time.time() - start_time
            
            if result.returncode == 0:
                self.record_test(
                    "DCMTK echoscu",
                    True,
                    "echoscu command successful",
                    duration
                )
            else:
                self.record_test(
                    "DCMTK echoscu",
                    False,
                    f"echoscu failed: {result.stderr}",
                    duration
                )
                
        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            self.record_test(
                "DCMTK echoscu",
                False,
                "echoscu timed out",
                duration
            )
        except Exception as e:
            duration = time.time() - start_time
            self.record_test(
                "DCMTK echoscu",
                False,
                f"Exception: {e}",
                duration
            )
        
        # Test findscu
        start_time = time.time()
        try:
            cmd = [
                '/usr/bin/findscu',
                '-aet', 'SIMPLE_TEST_SCU',
                '-aec', self.config['qrscp_ae'],
                '-S',  # Study level
                '-k', 'QueryRetrieveLevel=STUDY',
                '-k', 'PatientName=',
                '-k', 'StudyDate=',
                self.config['qrscp_host'],
                str(self.config['qrscp_port'])
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            duration = time.time() - start_time
            
            if result.returncode == 0:
                study_count = result.stdout.count('# Dicom-Data-Set')
                self.record_test(
                    "DCMTK findscu",
                    True,
                    f"findscu successful, found {study_count} studies",
                    duration
                )
            else:
                self.record_test(
                    "DCMTK findscu",
                    False,
                    f"findscu failed: {result.stderr}",
                    duration
                )
                
        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            self.record_test(
                "DCMTK findscu",
                False,
                "findscu timed out",
                duration
            )
        except Exception as e:
            duration = time.time() - start_time
            self.record_test(
                "DCMTK findscu",
                False,
                f"Exception: {e}",
                duration
            )
    
    def generate_test_dicom(self, count: int = 5) -> List[Path]:
        """Generate simple test DICOM files"""
        console.print(f"\n[bold blue]Generating {count} Test DICOM Files[/bold blue]")
        
        self.config['test_data_dir'].mkdir(exist_ok=True)
        generated_files = []
        
        start_time = time.time()
        
        try:
            for i in range(count):
                # Create basic DICOM dataset
                ds = Dataset()
                ds.SOPClassUID = '1.2.840.10008.5.1.4.1.1.2'  # CT Image Storage
                ds.SOPInstanceUID = generate_uid()
                ds.StudyInstanceUID = generate_uid()
                ds.SeriesInstanceUID = generate_uid()
                ds.StudyID = f'STU{i:03d}'
                ds.SeriesNumber = 1
                ds.InstanceNumber = 1
                
                # Patient info
                ds.PatientName = f'TestPatient^{i:03d}'
                ds.PatientID = f'PID{i:05d}'
                ds.PatientSex = 'M' if i % 2 == 0 else 'F'
                
                # Study info
                ds.StudyDate = datetime.now().strftime('%Y%m%d')
                ds.StudyTime = datetime.now().strftime('%H%M%S')
                ds.StudyDescription = f'Simple Test Study {i:03d}'
                ds.Modality = 'CT'
                
                # Basic image attributes
                ds.Rows = 64
                ds.Columns = 64
                ds.BitsAllocated = 16
                ds.BitsStored = 16
                ds.HighBit = 15
                ds.PixelRepresentation = 0
                ds.SamplesPerPixel = 1
                ds.PhotometricInterpretation = 'MONOCHROME2'
                
                # Minimal pixel data
                ds.PixelData = bytes([i % 256] * 64 * 64 * 2)  # 16-bit data
                
                # File meta
                ds.file_meta = pydicom.dataset.FileMetaDataset()
                ds.file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
                ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
                ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
                ds.file_meta.ImplementationClassUID = generate_uid()
                ds.file_meta.ImplementationVersionName = 'SIMPLE_TEST_1.0'
                
                # Save file
                filename = f'simple_test_{i:03d}.dcm'
                filepath = self.config['test_data_dir'] / filename
                ds.save_as(str(filepath))
                generated_files.append(filepath)
            
            duration = time.time() - start_time
            self.record_test(
                "Generate Test Files",
                True,
                f"Generated {count} DICOM files",
                duration
            )
            
        except Exception as e:
            duration = time.time() - start_time
            self.record_test(
                "Generate Test Files",
                False,
                f"Failed to generate files: {e}",
                duration
            )
        
        return generated_files
    
    def test_c_store(self, test_files: List[Path]):
        """Test C-STORE operations"""
        console.print("\n[bold blue]Testing C-STORE Operations[/bold blue]")
        
        if not test_files:
            self.record_test("C-STORE", False, "No test files available", 0.0)
            return
        
        # Test storing to SCP1
        start_time = time.time()
        stored_count = 0
        
        try:
            assoc = self.test_ae.associate(
                self.config['scp1_host'],
                self.config['scp1_port'],
                ae_title=self.config['scp1_ae']
            )
            
            if assoc.is_established:
                for file_path in test_files:
                    try:
                        ds = pydicom.dcmread(str(file_path))
                        status = assoc.send_c_store(ds)
                        
                        if status.Status == 0x0000:
                            stored_count += 1
                            
                    except Exception as file_error:
                        console.print(f"[yellow]Warning[/yellow]: Failed to store {file_path.name}: {file_error}")
                
                assoc.release()
                
                duration = time.time() - start_time
                
                if stored_count == len(test_files):
                    self.record_test(
                        "C-STORE to SCP1",
                        True,
                        f"Stored {stored_count}/{len(test_files)} files",
                        duration
                    )
                else:
                    self.record_test(
                        "C-STORE to SCP1",
                        stored_count > 0,
                        f"Stored {stored_count}/{len(test_files)} files",
                        duration
                    )
            else:
                duration = time.time() - start_time
                self.record_test(
                    "C-STORE to SCP1",
                    False,
                    "Failed to establish association",
                    duration
                )
                
        except Exception as e:
            duration = time.time() - start_time
            self.record_test(
                "C-STORE to SCP1",
                False,
                f"Exception: {e}",
                duration
            )
    
    def test_ssl_infrastructure(self):
        """Test SSL key infrastructure"""
        console.print("\n[bold blue]Testing SSL Infrastructure[/bold blue]")
        
        key_dir = Path('./etc/key')
        private_key = key_dir / 'private.key'
        public_key = key_dir / 'public.key'
        
        start_time = time.time()
        
        # Check if SSL keys exist
        if private_key.exists() and public_key.exists():
            duration = time.time() - start_time
            self.record_test(
                "SSL Key Infrastructure",
                True,
                "SSL key files found",
                duration
            )
        else:
            duration = time.time() - start_time
            self.record_test(
                "SSL Key Infrastructure",
                False,
                "SSL key files not found",
                duration
            )
    
    def check_daemon_processes(self):
        """Check if DICOM daemon processes are running"""
        console.print("\n[bold blue]Checking DICOM Daemon Processes[/bold blue]")
        
        start_time = time.time()
        
        try:
            # Check for storescp processes
            cmd = ['pgrep', '-f', 'storescp']
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            duration = time.time() - start_time
            
            if result.returncode == 0:
                pids = result.stdout.strip().split('\n')
                self.record_test(
                    "DICOM Daemon Processes",
                    True,
                    f"Found {len(pids)} storescp processes running",
                    duration
                )
            else:
                self.record_test(
                    "DICOM Daemon Processes",
                    False,
                    "No storescp processes found running",
                    duration
                )
                
        except Exception as e:
            duration = time.time() - start_time
            self.record_test(
                "DICOM Daemon Processes",
                False,
                f"Exception: {e}",
                duration
            )
        
        # Check for dcmqrscp
        start_time = time.time()
        
        try:
            cmd = ['pgrep', '-f', 'dcmqrscp']
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            duration = time.time() - start_time
            
            if result.returncode == 0:
                pids = result.stdout.strip().split('\n')
                self.record_test(
                    "DCMQRSCP Process",
                    True,
                    f"Found {len(pids)} dcmqrscp processes running",
                    duration
                )
            else:
                self.record_test(
                    "DCMQRSCP Process",
                    False,
                    "No dcmqrscp processes found running",
                    duration
                )
                
        except Exception as e:
            duration = time.time() - start_time
            self.record_test(
                "DCMQRSCP Process",
                False,
                f"Exception: {e}",
                duration
            )
    
    def display_results(self):
        """Display test results summary"""
        console.print("\n" + "="*80)
        console.print("[bold cyan]SIMPLE DICOM TEST RESULTS[/bold cyan]")
        console.print("="*80)
        
        # Summary table
        table = Table(title="Test Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Total Tests", str(self.test_results['tests_run']))
        table.add_row("Passed", str(self.test_results['tests_passed']))
        table.add_row("Failed", str(self.test_results['tests_failed']))
        
        if self.test_results['tests_run'] > 0:
            success_rate = (self.test_results['tests_passed'] / self.test_results['tests_run']) * 100
            table.add_row("Success Rate", f"{success_rate:.1f}%")
        
        console.print(table)
        
        # Detailed results
        if self.test_results['test_details']:
            console.print(f"\n[bold blue]Detailed Results[/bold blue]")
            
            details_table = Table()
            details_table.add_column("Test", style="cyan")
            details_table.add_column("Status", style="bold")
            details_table.add_column("Duration", style="yellow")
            details_table.add_column("Details", style="white")
            
            for test in self.test_results['test_details']:
                status = "[green]PASS[/green]" if test['success'] else "[red]FAIL[/red]"
                details_table.add_row(
                    test['name'],
                    status,
                    f"{test['duration']:.2f}s",
                    test['details']
                )
            
            console.print(details_table)
        
        # Final verdict
        if self.test_results['tests_failed'] == 0:
            console.print(f"\n[bold green]🎉 ALL TESTS PASSED! 🎉[/bold green]")
        else:
            console.print(f"\n[bold red]❌ {self.test_results['tests_failed']} TESTS FAILED[/bold red]")
    
    def run_all_tests(self):
        """Run all tests"""
        console.print(Panel.fit(
            "[bold green]Simple DICOM Test Suite[/bold green]\n\n"
            "Testing basic DICOM infrastructure and functionality.",
            title="[bold blue]Lethologic Anomia - DICOM Testing[/bold blue]"
        ))
        
        # Check daemon processes first
        self.check_daemon_processes()
        
        # Test basic connectivity
        self.test_dicom_services_running()
        
        # Test DCMTK tools
        self.test_dcmtk_tools()
        
        # Generate and test with DICOM files
        test_files = self.generate_test_dicom(5)
        self.test_c_store(test_files)
        
        # Test SSL infrastructure
        self.test_ssl_infrastructure()
        
        # Display results
        self.display_results()


if __name__ == "__main__":
    # Setup basic logging
    logging.basicConfig(level=logging.WARNING)  # Reduce log noise
    
    # Run tests
    tester = SimpleDICOMTester()
    tester.run_all_tests()
