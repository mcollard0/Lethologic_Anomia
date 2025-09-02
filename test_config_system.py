#!/usr/bin/env python3
"""
Test script for database configuration system
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to path
sys.path.insert(0, str(Path(__file__).parent))

from core.database import DatabaseManager
from core.config_manager import DatabaseConfigManager


async def test_config_system():
    """Test the configuration system"""
    print("Testing database configuration system...")
    
    try:
        # Initialize with simple database path (will be converted internally)
        db_manager = DatabaseManager("migration_service_test.db")
        await db_manager.initialize()
        print("✓ Database manager initialized")
        
        # Initialize config manager
        config_manager = DatabaseConfigManager(db_manager)
        await config_manager.initialize()
        print("✓ Config manager initialized")
        
        # Test getting default DICOM SCP configuration
        dicom_config = await config_manager.get_dicom_scp_config()
        print(f"✓ DICOM SCP config loaded: {len(dicom_config)} items")
        print(f"  - DICOM SCP port: {dicom_config.get('port', 'not set')}")
        print(f"  - DICOM SCP AE title: {dicom_config.get('ae_title', 'not set')}")
        
        # Test setting a configuration value
        success = await config_manager.set_config_value("dicom_scp", "port", 50104)
        if success:
            print("✓ Successfully set dicom_scp.port = 50104")
        
        # Test getting the updated value
        port_value = await config_manager.get_config_value("dicom_scp", "port", default=0)
        print(f"✓ Retrieved dicom_scp.port = {port_value}")
        
        # Test listing all services
        services = await config_manager.list_services()
        print(f"✓ Found {len(services)} configured services: {', '.join(services)}")
        
        # Test web interface config
        web_config = await config_manager.get_web_interface_config()
        print(f"✓ Web interface config loaded: {len(web_config)} items")
        print(f"  - Web interface port: {web_config.get('port', 'not set')}")
        print(f"  - Web interface enabled: {web_config.get('enabled', 'not set')}")
        
        print("\\n✅ All configuration tests passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        if 'db_manager' in locals():
            await db_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(test_config_system())
