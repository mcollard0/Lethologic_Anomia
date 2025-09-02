#!/usr/bin/env python3
"""
Manual test for DICOM SCP functionality
Tests the storage functionality and directory structure
"""

import asyncio
import sys
import os
import time
from pathlib import Path

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from service.dicom.scp import DICOMSCPService, create_dicom_tables
from core.database import DatabaseManager
from core.config import Settings, get_settings

async def test_scp():
    """Test SCP functionality"""
    
    # Initialize components
    settings = get_settings()
    
    # Use temporary database for testing
    test_db_url = "sqlite:///:memory:"
    db_manager = DatabaseManager(test_db_url)
    await db_manager.initialize()
    
    # Create tables
    await create_dicom_tables(db_manager)
    
    # Create and configure SCP service
    scp = DICOMSCPService(db_manager, settings)
    
    config = {
        'port': 11112,  # Use non-privileged port for testing
        'ae_title': 'TESTMIGRATION',
        'output_directory': './test_dicom_storage',
        'max_pdu': 65536,
        'acse_timeout': 30,
        'dimse_timeout': 30,
        'socket_timeout': 60
    }
    
    print(f"Configuring SCP with config: {config}")
    if not scp.configure(config):
        print("❌ Failed to configure SCP")
        return False
    
    print("✅ SCP configured successfully")
    
    # Start the service
    print("Starting SCP service...")
    if not scp.start():
        print("❌ Failed to start SCP")
        return False
    
    print(f"✅ SCP started on port {config['port']}")
    print(f"AE Title: {config['ae_title']}")
    print(f"Storage Directory: {config['output_directory']}")
    
    # Let it run for a moment
    print("SCP is running... (waiting 5 seconds)")
    await asyncio.sleep(5)
    
    # Check statistics
    stats = scp.get_statistics()
    print(f"Statistics: {stats}")
    
    # Stop the service
    print("Stopping SCP...")
    scp.stop()
    print("✅ SCP stopped")
    
    # Check if directory structure was created
    output_dir = Path(config['output_directory'])
    if output_dir.exists():
        print(f"✅ Output directory created: {output_dir}")
    else:
        print(f"❌ Output directory not found: {output_dir}")
    
    return True

if __name__ == "__main__":
    print("=== DICOM SCP Manual Test ===")
    try:
        result = asyncio.run(test_scp())
        if result:
            print("✅ Test completed successfully")
        else:
            print("❌ Test failed")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
