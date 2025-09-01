#!/usr/bin/env python3
"""
Simple test to verify core imports work
"""

import sys
import os
sys.path.insert(0, '.')

print("Testing imports...")

try:
    print("1. Testing core.config...")
    from core.config import Settings
    settings = Settings()
    print(f"   ✓ Config loaded, web_port: {settings.web_port}")
except Exception as e:
    print(f"   ✗ Error: {e}")

try:
    print("2. Testing core.logging...")
    from core.custom_logging import get_logger
    logger = get_logger(__name__)
    print("   ✓ Logger loaded")
except Exception as e:
    print(f"   ✗ Error: {e}")

try:
    print("3. Testing basic AI loop...")
    from core.ai_loop import AIService
    print("   ✓ AI service loaded")
except Exception as e:
    print(f"   ✗ Error: {e}")

try:
    print("4. Testing DICOM services...")
    from services.dicom.scp import DICOMSCPService
    from services.dicom.scu import DICOMSCUService
    print("   ✓ DICOM services loaded")
except Exception as e:
    print(f"   ✗ Error: {e}")

print("Basic import tests completed!")
