"""
Bulk DICOM Image Generation Tool

Supports generation of 1-10,000 test DICOM images across 1-100,000 patients
and 1-100,000 studies for the 20 most common modalities.
"""

import os
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
from pydicom import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from pydicom.dataset import FileDataset

from core.custom_logging import get_logger

logger = get_logger(__name__)

# 20 Most Common DICOM Modalities
MODALITIES = {
    'CT': {
        'name': 'Computed Tomography',
        'matrix_size': (512, 512),
        'bits_allocated': 16,
        'photometric_interpretation': 'MONOCHROME2'
    },
    'MR': {
        'name': 'Magnetic Resonance',
        'matrix_size': (256, 256),
        'bits_allocated': 16,
        'photometric_interpretation': 'MONOCHROME2'
    },
    'XR': {
        'name': 'X-Ray',
        'matrix_size': (2048, 2048),
        'bits_allocated': 16,
        'photometric_interpretation': 'MONOCHROME2'
    },
    'CR': {
        'name': 'Computed Radiography',
        'matrix_size': (2048, 2048),
        'bits_allocated': 16,
        'photometric_interpretation': 'MONOCHROME2'
    },
    'US': {
        'name': 'Ultrasound',
        'matrix_size': (640, 480),
        'bits_allocated': 8,
        'photometric_interpretation': 'YBR_FULL_422'
    },
    'MG': {
        'name': 'Mammography',
        'matrix_size': (4096, 3328),
        'bits_allocated': 16,
        'photometric_interpretation': 'MONOCHROME2'
    },
    'NM': {
        'name': 'Nuclear Medicine',
        'matrix_size': (128, 128),
        'bits_allocated': 16,
        'photometric_interpretation': 'MONOCHROME2'
    },
    'PET': {
        'name': 'Positron Emission Tomography',
        'matrix_size': (128, 128),
        'bits_allocated': 16,
        'photometric_interpretation': 'MONOCHROME2'
    },
    'RF': {
        'name': 'Radio Fluoroscopy',
        'matrix_size': (1024, 1024),
        'bits_allocated': 16,
        'photometric_interpretation': 'MONOCHROME2'
    },
    'SC': {
        'name': 'Secondary Capture',
        'matrix_size': (1024, 768),
        'bits_allocated': 8,
        'photometric_interpretation': 'RGB'
    },
    'OT': {
        'name': 'Other',
        'matrix_size': (512, 512),
        'bits_allocated': 16,
        'photometric_interpretation': 'MONOCHROME2'
    },
    'DX': {
        'name': 'Digital Radiography',
        'matrix_size': (3000, 3000),
        'bits_allocated': 16,
        'photometric_interpretation': 'MONOCHROME2'
    },
    'ES': {
        'name': 'Endoscopy',
        'matrix_size': (720, 576),
        'bits_allocated': 8,
        'photometric_interpretation': 'YBR_FULL_422'
    },
    'XA': {
        'name': 'X-Ray Angiography',
        'matrix_size': (1024, 1024),
        'bits_allocated': 16,
        'photometric_interpretation': 'MONOCHROME2'
    },
    'OP': {
        'name': 'Ophthalmic Photography',
        'matrix_size': (1024, 1024),
        'bits_allocated': 8,
        'photometric_interpretation': 'RGB'
    },
    'OPT': {
        'name': 'Ophthalmic Tomography',
        'matrix_size': (512, 512),
        'bits_allocated': 16,
        'photometric_interpretation': 'MONOCHROME2'
    },
    'GM': {
        'name': 'General Microscopy',
        'matrix_size': (2048, 2048),
        'bits_allocated': 8,
        'photometric_interpretation': 'RGB'
    },
    'SM': {
        'name': 'Slide Microscopy',
        'matrix_size': (40000, 30000),  # High-resolution slide
        'bits_allocated': 8,
        'photometric_interpretation': 'RGB'
    },
    'IO': {
        'name': 'Intra-Oral Radiography',
        'matrix_size': (1760, 2140),
        'bits_allocated': 16,
        'photometric_interpretation': 'MONOCHROME2'
    },
    'RTSTRUCT': {
        'name': 'RT Structure Set',
        'matrix_size': None,  # No image data
        'bits_allocated': None,
        'photometric_interpretation': None
    }
}

# Sample patient names for test data
SAMPLE_NAMES = [
    "ANONYMOUS^PATIENT", "DOE^JOHN", "SMITH^JANE", "JOHNSON^ROBERT", "WILLIAMS^MARY",
    "BROWN^MICHAEL", "JONES^PATRICIA", "GARCIA^CHRISTOPHER", "MILLER^JENNIFER", "DAVIS^MATTHEW",
    "RODRIGUEZ^LINDA", "MARTINEZ^ANTHONY", "HERNANDEZ^ELIZABETH", "LOPEZ^MARK", "GONZALEZ^HELEN",
    "WILSON^PAUL", "ANDERSON^NANCY", "THOMAS^STEVEN", "TAYLOR^KAREN", "MOORE^EDWARD"
]

# Common study descriptions
STUDY_DESCRIPTIONS = {
    'CT': ['CT HEAD W/O CONTRAST', 'CT CHEST W CONTRAST', 'CT ABDOMEN/PELVIS W CONTRAST', 'CT SPINE'],
    'MR': ['MRI BRAIN W/O CONTRAST', 'MRI KNEE W/O CONTRAST', 'MRI LUMBAR SPINE', 'MRI SHOULDER'],
    'XR': ['CHEST XRAY', 'HAND XRAY', 'KNEE XRAY', 'SPINE XRAY'],
    'CR': ['CHEST PORTABLE', 'ABDOMEN XRAY', 'PELVIS XRAY'],
    'US': ['ABDOMEN ULTRASOUND', 'ECHOCARDIOGRAM', 'CAROTID ULTRASOUND', 'PELVIC ULTRASOUND'],
    'MG': ['BILATERAL MAMMOGRAPHY', 'UNILATERAL MAMMOGRAPHY'],
    'NM': ['BONE SCAN', 'MYOCARDIAL PERFUSION', 'THYROID SCAN'],
    'PET': ['PET/CT WHOLE BODY', 'PET BRAIN', 'PET CARDIAC'],
    'RF': ['UPPER GI SERIES', 'BARIUM ENEMA', 'FLUOROSCOPY'],
    'SC': ['SCANNED DOCUMENT', 'DOSE REPORT'],
    'OT': ['OTHER PROCEDURE'],
    'DX': ['DIGITAL CHEST', 'DIGITAL ABDOMEN'],
    'ES': ['UPPER ENDOSCOPY', 'COLONOSCOPY'],
    'XA': ['CARDIAC CATHETERIZATION', 'CEREBRAL ANGIOGRAPHY'],
    'OP': ['RETINAL PHOTOGRAPHY', 'ANTERIOR SEGMENT'],
    'OPT': ['OCT RETINA', 'OCT ANTERIOR SEGMENT'],
    'GM': ['TISSUE MICROSCOPY'],
    'SM': ['PATHOLOGY SLIDE'],
    'IO': ['BITEWING XRAY', 'PERIAPICAL XRAY'],
    'RTSTRUCT': ['RT STRUCTURE SET']
}


class DICOMGenerator:
    """Bulk DICOM image generator"""
    
    def __init__(self, output_dir: str = "generated_dicom"):
        """
        Initialize DICOM generator
        
        Args:
            output_dir: Output directory for generated files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # Create etc directory for sample source images (gitignored)
        self.etc_dir = Path("etc")
        self.etc_dir.mkdir(exist_ok=True)
        
        logger.info(f"DICOM Generator initialized. Output: {self.output_dir}")
    
    def generate_patient_id(self) -> str:
        """Generate a random patient ID"""
        return f"P{random.randint(100000, 999999)}"
    
    def generate_study_uid(self) -> str:
        """Generate a unique study instance UID"""
        return generate_uid()
    
    def generate_series_uid(self) -> str:
        """Generate a unique series instance UID"""
        return generate_uid()
    
    def generate_instance_uid(self) -> str:
        """Generate a unique SOP instance UID"""
        return generate_uid()
    
    def generate_random_pixel_data(self, modality: str) -> Optional[bytes]:
        """
        Generate random pixel data for a modality
        
        Args:
            modality: DICOM modality code
            
        Returns:
            Random pixel data as bytes
        """
        if modality not in MODALITIES or MODALITIES[modality]['matrix_size'] is None:
            return None
        
        rows, cols = MODALITIES[modality]['matrix_size']
        bits_allocated = MODALITIES[modality]['bits_allocated']
        
        # For very large images like slide microscopy, use smaller test size
        if rows * cols > 1000000:  # If > 1M pixels, reduce size for testing
            rows = min(rows, 1000)
            cols = min(cols, 1000)
        
        if bits_allocated == 8:
            # 8-bit data
            if MODALITIES[modality]['photometric_interpretation'] == 'RGB':
                # RGB image
                pixel_array = np.random.randint(0, 256, (rows, cols, 3), dtype=np.uint8)
            else:
                # Grayscale
                pixel_array = np.random.randint(0, 256, (rows, cols), dtype=np.uint8)
        else:
            # 16-bit data
            pixel_array = np.random.randint(0, 4096, (rows, cols), dtype=np.uint16)
        
        return pixel_array.tobytes()
    
    def create_dicom_dataset(
        self,
        patient_id: str,
        patient_name: str,
        study_uid: str,
        series_uid: str,
        instance_uid: str,
        modality: str,
        study_description: str,
        study_date: str,
        birth_date: Optional[str] = None,
        sex: Optional[str] = None
    ) -> FileDataset:
        """
        Create a DICOM dataset with specified parameters
        
        Args:
            patient_id: Patient ID
            patient_name: Patient name
            study_uid: Study instance UID
            series_uid: Series instance UID  
            instance_uid: SOP instance UID
            modality: DICOM modality
            study_description: Study description
            study_date: Study date (YYYYMMDD)
            birth_date: Patient birth date (optional)
            sex: Patient sex (optional)
            
        Returns:
            DICOM FileDataset
        """
        # Create file meta information
        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = '1.2.840.10008.5.1.4.1.1.2'  # CT Image Storage
        file_meta.MediaStorageSOPInstanceUID = instance_uid
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        
        # Create main dataset
        ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\\x00" * 128)
        
        # Patient information
        ds.PatientName = patient_name
        ds.PatientID = patient_id
        if birth_date:
            ds.PatientBirthDate = birth_date
        if sex:
            ds.PatientSex = sex
        
        # Study information
        ds.StudyInstanceUID = study_uid
        ds.StudyDate = study_date
        ds.StudyTime = datetime.now().strftime("%H%M%S")
        ds.StudyDescription = study_description
        ds.StudyID = str(random.randint(1000, 9999))
        ds.AccessionNumber = f"ACC{random.randint(100000, 999999)}"
        
        # Series information
        ds.SeriesInstanceUID = series_uid
        ds.SeriesNumber = str(random.randint(1, 100))
        ds.SeriesDescription = f"{modality} Series"
        ds.SeriesDate = study_date
        ds.SeriesTime = ds.StudyTime
        
        # Image information
        ds.SOPInstanceUID = instance_uid
        ds.SOPClassUID = '1.2.840.10008.5.1.4.1.1.2'
        ds.Modality = modality
        ds.InstanceNumber = str(random.randint(1, 1000))
        
        # Add pixel data if applicable
        if modality in MODALITIES and MODALITIES[modality]['matrix_size'] is not None:
            modality_info = MODALITIES[modality]
            rows, cols = modality_info['matrix_size']
            
            # Limit size for testing
            if rows * cols > 1000000:
                rows = min(rows, 1000)
                cols = min(cols, 1000)
            
            ds.Rows = rows
            ds.Columns = cols
            ds.BitsAllocated = modality_info['bits_allocated']
            ds.BitsStored = modality_info['bits_allocated']
            ds.HighBit = modality_info['bits_allocated'] - 1
            ds.PixelRepresentation = 0
            ds.PhotometricInterpretation = modality_info['photometric_interpretation']
            ds.SamplesPerPixel = 3 if 'RGB' in modality_info['photometric_interpretation'] else 1
            
            # Generate pixel data
            pixel_data = self.generate_random_pixel_data(modality)
            if pixel_data:
                ds.PixelData = pixel_data
        
        # Institution and equipment
        ds.InstitutionName = "Test Hospital"
        ds.InstitutionAddress = "123 Medical Center Dr, Test City, TC 12345"
        ds.Manufacturer = "Test Manufacturer"
        ds.ManufacturerModelName = "Test Model v1.0"
        ds.StationName = "TEST_STATION"
        
        # Timestamps
        ds.ContentDate = study_date
        ds.ContentTime = ds.StudyTime
        ds.InstanceCreationDate = study_date
        ds.InstanceCreationTime = ds.StudyTime
        
        return ds
    
    def generate_bulk_dicom(
        self,
        num_images: int = 100,
        num_patients: int = 10,
        num_studies: int = 20,
        modalities: Optional[List[str]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Generate bulk DICOM images
        
        Args:
            num_images: Number of images to generate (1-10,000)
            num_patients: Number of patients (1-100,000)
            num_studies: Number of studies (1-100,000)
            modalities: List of modalities to use (default: all)
            start_date: Start date for studies
            end_date: End date for studies
            
        Returns:
            Generation statistics
        """
        # Validate parameters
        num_images = max(1, min(num_images, 10000))
        num_patients = max(1, min(num_patients, 100000))
        num_studies = max(1, min(num_studies, 100000))
        
        if modalities is None:
            modalities = list(MODALITIES.keys())
        
        if start_date is None:
            start_date = datetime.now() - timedelta(days=365)
        if end_date is None:
            end_date = datetime.now()
        
        logger.info(f"Generating {num_images} DICOM images across {num_patients} patients and {num_studies} studies")
        
        # Generate patient pool
        patients = []
        for i in range(num_patients):
            patient_id = self.generate_patient_id()
            patient_name = random.choice(SAMPLE_NAMES)
            birth_date = (start_date - timedelta(days=random.randint(365*18, 365*80))).strftime("%Y%m%d")
            sex = random.choice(['M', 'F'])
            patients.append({
                'id': patient_id,
                'name': patient_name,
                'birth_date': birth_date,
                'sex': sex
            })
        
        # Generate study pool
        studies = []
        for i in range(num_studies):
            patient = random.choice(patients)
            study_uid = self.generate_study_uid()
            study_date = (start_date + timedelta(
                days=random.randint(0, (end_date - start_date).days)
            )).strftime("%Y%m%d")
            modality = random.choice(modalities)
            study_description = random.choice(STUDY_DESCRIPTIONS.get(modality, [f"{modality} Study"]))
            
            studies.append({
                'uid': study_uid,
                'patient': patient,
                'date': study_date,
                'modality': modality,
                'description': study_description
            })
        
        # Generate images
        generated_files = []
        errors = 0
        
        for i in range(num_images):
            try:
                study = random.choice(studies)
                series_uid = self.generate_series_uid()
                instance_uid = self.generate_instance_uid()
                
                # Create DICOM dataset
                ds = self.create_dicom_dataset(
                    patient_id=study['patient']['id'],
                    patient_name=study['patient']['name'],
                    study_uid=study['uid'],
                    series_uid=series_uid,
                    instance_uid=instance_uid,
                    modality=study['modality'],
                    study_description=study['description'],
                    study_date=study['date'],
                    birth_date=study['patient']['birth_date'],
                    sex=study['patient']['sex']
                )
                
                # Create output directory structure
                patient_dir = self.output_dir / study['patient']['id']
                study_dir = patient_dir / study['uid']
                series_dir = study_dir / series_uid
                series_dir.mkdir(parents=True, exist_ok=True)
                
                # Save DICOM file
                filename = f"{instance_uid}.dcm"
                filepath = series_dir / filename
                ds.save_as(filepath)
                
                generated_files.append(str(filepath))
                
                if (i + 1) % 100 == 0:
                    logger.info(f"Generated {i + 1}/{num_images} DICOM files...")
                
            except Exception as e:
                logger.error(f"Error generating DICOM file {i+1}: {e}")
                errors += 1
                continue
        
        # Generate statistics
        stats = {
            'images_generated': len(generated_files),
            'images_requested': num_images,
            'patients_used': len(set(study['patient']['id'] for study in studies if any(
                study['patient']['id'] in f for f in generated_files
            ))),
            'studies_used': len(set(study['uid'] for study in studies if any(
                study['uid'] in f for f in generated_files
            ))),
            'modalities_used': list(set(study['modality'] for study in studies)),
            'errors': errors,
            'output_directory': str(self.output_dir),
            'generation_time': datetime.now().isoformat()
        }
        
        logger.info(f"DICOM generation complete: {stats['images_generated']} files generated with {errors} errors")
        
        return stats


# Command-line interface
def main():
    """Command-line interface for DICOM generator"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Bulk DICOM Image Generator")
    parser.add_argument('--images', type=int, default=100, help='Number of images to generate (1-10000)')
    parser.add_argument('--patients', type=int, default=10, help='Number of patients (1-100000)')
    parser.add_argument('--studies', type=int, default=20, help='Number of studies (1-100000)')
    parser.add_argument('--output', type=str, default='generated_dicom', help='Output directory')
    parser.add_argument('--modalities', nargs='+', help='Modalities to generate', 
                       choices=list(MODALITIES.keys()))
    
    args = parser.parse_args()
    
    generator = DICOMGenerator(args.output)
    stats = generator.generate_bulk_dicom(
        num_images=args.images,
        num_patients=args.patients,
        num_studies=args.studies,
        modalities=args.modalities
    )
    
    print("Generation Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()


__all__ = ['DICOMGenerator', 'MODALITIES']
