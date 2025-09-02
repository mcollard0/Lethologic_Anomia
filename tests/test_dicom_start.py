#!/usr/bin/env python3
"""
Test script to manually start DICOM SCP service
"""

import asyncio
import sys
from pathlib import Path

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from core.config import get_settings
from core.database import DatabaseManager
from service.dicom.scp import DICOMSCPService, create_dicom_tables

async def test_dicom_scp():
    """Test DICOM SCP service startup"""
    try:
        print("Testing DICOM SCP service...")
        
        # Initialize settings
        settings = get_settings()
        print(f"DICOM SCP port: {settings.dicom.scp_port}")
        print(f"AE Title: {settings.dicom.our_ae_title}")
        
        # Initialize database
        db_manager = DatabaseManager(settings.database_url)
        await db_manager.initialize()
        print("Database initialized")
        
        # Create DICOM tables
        await create_dicom_tables(db_manager)
        print("DICOM tables created")
        
        # Create and configure SCP service
        scp_service = DICOMSCPService(db_manager, settings)
        
        config = {
            'port': settings.dicom.scp_port,
            'ae_title': settings.dicom.our_ae_title,
            'output_directory': settings.dicom.storage_directory,
            'max_pdu': settings.dicom.max_pdu,
            'acse_timeout': settings.dicom.acse_timeout,
            'dimse_timeout': settings.dicom.dimse_timeout,
            'socket_timeout': settings.dicom.socket_timeout
        }
        
        print(f"Configuring DICOM SCP with: {config}")
        
        if not scp_service.configure(config):
            print("❌ Failed to configure DICOM SCP service")
            return False
        
        print("✅ DICOM SCP configured successfully")
        
        if not scp_service.start():
            print("❌ Failed to start DICOM SCP service")
            return False
        
        print(f"✅ DICOM SCP started successfully on port {config['port']}")
        
        # Let it run for a few seconds
        await asyncio.sleep(5)
        
        print("Stopping DICOM SCP...")
        scp_service.stop()
        print("✅ DICOM SCP stopped")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_dicom_scp())
    if not success:
        sys.exit(1)
    print("🎉 DICOM SCP test completed successfully!")
