#!/usr/bin/env python3
"""
DICOM Verification Script

Simple script to verify that DICOM functionality is working correctly.
Checks dependencies and basic DICOM operations.
"""

import sys
from pathlib import Path

# Check Python version
if sys.version_info < (3, 8):
    print("❌ Python 3.8 or higher required")
    sys.exit(1)

print("🔬 DICOM Functionality Verification")
print("=" * 50)

# Check dependencies
print("\\n📋 Checking Dependencies...")

# Check pydicom
try:
    import pydicom
    print(f"✓ pydicom: {pydicom.__version__}")
    PYDICOM_OK = True
except ImportError:
    print("❌ pydicom: NOT INSTALLED")
    print("   Install with: pip install pydicom")
    PYDICOM_OK = False

# Check pynetdicom
try:
    import pynetdicom
    print(f"✓ pynetdicom: {pynetdicom.__version__}")
    PYNETDICOM_OK = True
except ImportError:
    print("❌ pynetdicom: NOT INSTALLED")
    print("   Install with: pip install pynetdicom")
    PYNETDICOM_OK = False

# Check numpy (required for pixel data)
try:
    import numpy as np
    print(f"✓ numpy: {np.__version__}")
    NUMPY_OK = True
except ImportError:
    print("❌ numpy: NOT INSTALLED")
    print("   Install with: pip install numpy")
    NUMPY_OK = False

# Check if all dependencies are available
if not all([PYDICOM_OK, PYNETDICOM_OK, NUMPY_OK]):
    print("\\n❌ Missing required dependencies. Please install them and try again.")
    sys.exit(1)

print("\\n✅ All dependencies available!")

# Test basic DICOM functionality
print("\\n🧪 Testing Basic DICOM Operations...")

try:
    # Test 1: Create a simple DICOM dataset
    print("  Testing dataset creation...", end=" ")
    from pydicom.dataset import Dataset
    from pydicom.uid import generate_uid
    
    ds = Dataset()
    ds.PatientName = "Test^Patient"
    ds.PatientID = "TEST001"
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = generate_uid()
    ds.Modality = "CT"
    print("✓")
    
    # Test 2: Test DICOM file I/O
    print("  Testing file I/O...", end=" ")
    import tempfile
    import os
    
    with tempfile.NamedTemporaryFile(suffix='.dcm', delete=False) as tmp:
        temp_file = tmp.name
    
    try:
        # Add minimal required tags for file saving
        from pydicom.dataset import FileDataset
        # Handle different versions of pydicom
        try:
            from pydicom.sop_class import CTImageStorage
        except ImportError:
            from pydicom.uid import CTImageStorage
        
        ds.SOPClassUID = CTImageStorage
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = 'MONOCHROME2'
        ds.Rows = 256
        ds.Columns = 256
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        
        # Create minimal pixel data
        pixel_array = np.zeros((256, 256), dtype=np.uint16)
        ds.PixelData = pixel_array.tobytes()
        
        # Create file meta information
        file_meta = Dataset()
        file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
        file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
        file_meta.ImplementationClassUID = generate_uid()
        file_meta.TransferSyntaxUID = '1.2.840.10008.1.2'
        
        # Create and save FileDataset
        file_ds = FileDataset(
            temp_file, ds, file_meta=file_meta,
            preamble=b"\0" * 128, is_implicit_VR=True
        )
        file_ds.save_as(temp_file)
        
        # Read back the file
        read_ds = pydicom.dcmread(temp_file)
        assert str(read_ds.PatientID) == "TEST001"
        
        print("✓")
        
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)
    
    # Test 3: Test Application Entity creation
    print("  Testing AE creation...", end=" ")
    from pynetdicom import AE
    from pynetdicom.sop_class import Verification
    
    ae = AE(ae_title='TESTAE')
    ae.add_requested_context(Verification)
    print("✓")
    
    # Test 4: Test pixel data access
    print("  Testing pixel data access...", end=" ")
    pixel_array = read_ds.pixel_array if 'read_ds' in locals() else ds.pixel_array
    assert pixel_array.shape == (256, 256)
    print("✓")
    
    print("\\n✅ Basic DICOM operations working correctly!")
    
except Exception as e:
    print(f"\\n❌ Basic DICOM test failed: {e}")
    sys.exit(1)

# Offer to run comprehensive tests
print("\\n🚀 Ready for Comprehensive Testing")
print("-" * 35)
print("\\nBasic DICOM functionality verified successfully!")
print("\\nTo run comprehensive DICOM tests including network operations:")
print("  python tests/test_dicom_functionality.py")
print("\\nTo test individual DICOM services:")
print("  python -m services.dicom.scp --test")
print("  python -m services.dicom.scu --test")
print("  python -m services.dicom.search --test")
print("  python -m services.dicom.parser --test")

print("\\n✅ DICOM verification complete - all systems ready!")
print("🏥 Medical image migration service is ready for use.")
