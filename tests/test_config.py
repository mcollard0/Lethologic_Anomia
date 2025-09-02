#!/usr/bin/env python3

"""
Test script for the configuration management system
Tests DatabaseConfigManager functionality
"""

import asyncio
import tempfile
import os
from core.database import DatabaseManager
from core.config_manager import DatabaseConfigManager

async def test_config_system():
    """Test the configuration management system"""
    
    # Create a temporary database file for testing
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        test_db_path = f.name
    
    print(f"Testing with database: {test_db_path}")
    
    try:
        # Test 1: Initialize DatabaseManager with simple filename
        print("\n=== Test 1: DatabaseManager initialization ===")
        db_manager = DatabaseManager(test_db_path)
        await db_manager.initialize()
        print(f"✓ DatabaseManager initialized successfully")
        print(f"  Detected database type: {db_manager.db_type}")
        print(f"  Database URL: {db_manager.database_url}")
        
        # Test 2: Initialize DatabaseConfigManager
        print("\n=== Test 2: DatabaseConfigManager initialization ===")
        config_manager = DatabaseConfigManager(db_manager)
        await config_manager.initialize()
        print("✓ DatabaseConfigManager initialized successfully")
        
        # Test 3: Test basic configuration operations
        print("\n=== Test 3: Basic configuration operations ===")
        
        # Set a test configuration
        success = await config_manager.set_config("test.setting", "test_value", "Test setting for verification")
        if success:
            print("✓ Configuration set successfully")
        else:
            print("❌ Configuration set failed")
            return
        
        # Get the configuration back
        value = await config_manager.get_config("test.setting")
        print(f"✓ Configuration retrieved: {value}")
        
        # Verify the value
        assert value == "test_value", f"Expected 'test_value', got '{value}'"
        print("✓ Configuration value verification passed")
        
        # Test 4: Test with default values
        print("\n=== Test 4: Default values ===")
        
        # Get a non-existent config with default
        default_value = await config_manager.get_config("nonexistent.setting", "default_value")
        print(f"✓ Default value returned: {default_value}")
        assert default_value == "default_value"
        
        # Test 5: Test service configuration
        print("\n=== Test 5: Service configuration ===\n")
        
        # Test getting a service config (should return default)
        dicom_port = await config_manager.get_service_config_value("dicom_scp", "port", 11112)
        print(f"✓ DICOM SCP port (default): {dicom_port}")
        
        # Set a service config
        await config_manager.set_service_config_value("dicom_scp", "port", 12345)
        print("✓ DICOM SCP port configuration set")
        
        # Get it back
        dicom_port = await config_manager.get_service_config_value("dicom_scp", "port", 11112)
        print(f"✓ DICOM SCP port (configured): {dicom_port}")
        assert dicom_port == 12345
        
        # Test 6: List all configurations
        print("\n=== Test 6: List configurations ===\n")
        all_configs = await config_manager.list_all_configs()
        print(f"✓ Found {len(all_configs)} configuration entries:")
        for config in all_configs:
            print(f"  - {config['name']}: {config['value']}")
        
        print("\n=== All tests passed! ===\n")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Clean up
        try:
            await db_manager.shutdown()
            print("✓ Database manager shutdown")
        except:
            pass
        
        try:
            if os.path.exists(test_db_path):
                os.unlink(test_db_path)
                print(f"✓ Temporary database file deleted: {test_db_path}")
        except:
            pass

if __name__ == "__main__":
    asyncio.run(test_config_system())
