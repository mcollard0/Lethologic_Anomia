#!/usr/bin/env python3
"""
Comprehensive Test Suite for AI Functions and DICOM Operations

Tests all the AI functions that were ported from the C++ version including:
- DICOM tag management (add/remove columns)
- AI games and utilities (Monty Hall, Fibonacci, Reverse Turing)
- Trust and aggression level management
- Database query operations
- System information functions

This test suite validates the new functionality matches the C++ implementation.
"""

import asyncio
import json
import os
import sys
import tempfile
import pytest
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# Add the project root to the path so we can import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import Settings
from core.database import DatabaseManager
from core.ai_loop import AIService


class TestAIFunctions:
    """Test suite for AI functions"""
    
    @pytest.fixture
    async def ai_service(self):
        """Create AI service instance for testing"""
        # Create temporary database
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        
        # Create test settings
        settings = Settings()
        settings.database.url = f"sqlite:///{self.temp_db.name}"
        
        # Create database manager
        db_manager = DatabaseManager(settings)
        await db_manager.initialize()
        
        # Create test tables
        await self._create_test_tables(db_manager)
        
        # Create AI service
        ai_service = AIService(settings, db_manager)
        
        # Mock the AI model initialization to avoid downloading models in tests
        ai_service.local_model = MagicMock()
        ai_service.tokenizer = MagicMock()
        ai_service.available_providers = ['test']
        
        yield ai_service
        
        # Cleanup
        await db_manager.close()
        os.unlink(self.temp_db.name)
    
    async def _create_test_tables(self, db_manager: DatabaseManager):
        """Create test database tables"""
        # Create config table
        await db_manager.execute_query("""
            CREATE TABLE IF NOT EXISTS config (
                name TEXT PRIMARY KEY,
                value TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create sites table
        await db_manager.execute_query("""
            CREATE TABLE IF NOT EXISTS sites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sitename TEXT UNIQUE NOT NULL,
                status TEXT DEFAULT 'active',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create migrations table
        await db_manager.execute_query("""
            CREATE TABLE IF NOT EXISTS migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                migration_id TEXT UNIQUE NOT NULL,
                sitename TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sitename) REFERENCES sites(sitename)
            )
        """)
        
        # Create test DICOM table
        await db_manager.execute_query("""
            CREATE TABLE IF NOT EXISTS dicom_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id TEXT,
                study_uid TEXT,
                series_uid TEXT,
                instance_uid TEXT,
                file_path TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
    
    # Test Monty Hall game
    async def test_lets_make_a_deal(self, ai_service):
        """Test Let's Make a Deal (Monty Hall problem) game"""
        result = await ai_service._lets_make_a_deal()
        
        assert "🎪 Let's Make a Deal - Monty Hall Problem 🎪" in result
        assert "Car is behind door:" in result
        assert "You initially chose:" in result
        assert "Host opens:" in result
        assert "Switch to:" in result
        assert "Running Statistics:" in result
        assert "Theoretical probability: Stay=33.3%, Switch=66.7%" in result
        
        # Test that statistics are saved
        stats_result = await ai_service.db_manager.execute_query(
            "SELECT value FROM config WHERE name = 'LMAD_STATS'"
        )
        assert stats_result
        stats = json.loads(stats_result[0]['value'])
        assert stats['games_played'] == 1
        assert 'stay_wins' in stats
        assert 'switch_wins' in stats
    
    # Test Fibonacci sequence
    async def test_fibonacci_sequence(self, ai_service):
        """Test Fibonacci sequence calculation"""
        # Test default count
        result = await ai_service._fibonacci_sequence()
        assert "🔢 Fibonacci Sequence (first 20 numbers):" in result
        assert "F( 0) =" in result
        assert "F(19) =" in result
        assert "Golden Ratio approximation:" in result
        
        # Test custom count
        result = await ai_service._fibonacci_sequence(5)
        assert "🔢 Fibonacci Sequence (first 5 numbers):" in result
        assert "F( 4) =" in result
        
        # Test edge cases
        result = await ai_service._fibonacci_sequence(0)
        assert "Please provide a count between 1 and 100." in result
        
        result = await ai_service._fibonacci_sequence(101)
        assert "Please provide a count between 1 and 100." in result
    
    # Test Reverse Turing Test
    async def test_reverse_turing_test(self, ai_service):
        """Test reverse Turing test functionality"""
        result = await ai_service._reverse_turing_test()
        
        assert "🤖 Reverse Turing Test 🤖" in result
        assert "Here's a question for you, human..." in result
        assert "Q:" in result
        assert "🤖 My AI answer:" in result
        assert "👤 Typical human answer:" in result
        assert "The point is to show how AIs and humans think differently!" in result
        
        # Test that question is saved for follow-up
        last_question = await ai_service.db_manager.execute_query(
            "SELECT value FROM config WHERE name = 'LAST_REVERSE_TURING'"
        )
        assert last_question
        question_data = json.loads(last_question[0]['value'])
        assert 'question' in question_data
        assert 'asked_at' in question_data
    
    # Test trust level management
    async def test_trust_level_management(self, ai_service):
        """Test trust level get/set functions"""
        # Test getting initial trust level
        result = await ai_service._handle_function_call("get_trust", {})
        assert "Current trust level: 0" in result
        
        # Test setting valid trust level
        result = await ai_service._handle_function_call("set_trust", {"trust": 15})
        assert "Trust level set to: 15" in result
        assert ai_service.trust_level == 15
        
        # Test invalid trust levels
        result = await ai_service._handle_function_call("set_trust", {"trust": 25})
        assert "Trust level must be between 0 and 20." in result
        
        result = await ai_service._handle_function_call("set_trust", {"trust": -1})
        assert "Trust level must be between 0 and 20." in result
    
    # Test aggression level management
    async def test_aggression_level_management(self, ai_service):
        """Test aggression level get/set functions"""
        # Test getting initial aggression level
        result = await ai_service._handle_function_call("get_aggression", {})
        assert "Current aggression level: 1" in result
        
        # Test setting valid aggression level
        result = await ai_service._handle_function_call("set_aggression", {"aggression": 7})
        assert "Aggression level set to: 7" in result
        assert ai_service.aggression_level == 7
        
        # Test invalid aggression levels
        result = await ai_service._handle_function_call("set_aggression", {"aggression": 11})
        assert "Aggression level must be between 1 and 10." in result
        
        result = await ai_service._handle_function_call("set_aggression", {"aggression": 0})
        assert "Aggression level must be between 1 and 10." in result
    
    # Test system information
    @patch('psutil.virtual_memory')
    @patch('psutil.swap_memory')
    @patch('psutil.Process')
    @patch('psutil.cpu_percent')
    @patch('psutil.cpu_count')
    @patch('psutil.disk_usage')
    async def test_get_stack_free_space(self, mock_disk, mock_cpu_count, mock_cpu_percent, 
                                       mock_process, mock_swap, mock_memory, ai_service):
        """Test system memory and stack information retrieval"""
        # Mock system information
        mock_memory.return_value = MagicMock(
            total=16*1024**3, available=8*1024**3, used=8*1024**3, 
            free=4*1024**3, percent=50.0
        )
        mock_swap.return_value = MagicMock(
            total=4*1024**3, used=1*1024**3, free=3*1024**3, percent=25.0
        )
        mock_process.return_value.memory_info.return_value = MagicMock(
            rss=512*1024**2, vms=1024*1024**2
        )
        mock_process.return_value.pid = 12345
        mock_process.return_value.cpu_percent.return_value = 5.5
        mock_cpu_percent.return_value = 15.0
        mock_cpu_count.return_value = 8
        mock_disk.return_value = MagicMock(
            total=1024*1024**3, used=512*1024**3, free=512*1024**3
        )
        
        result = await ai_service._get_stack_free_space()
        
        assert "💾 System Memory & Stack Information" in result
        assert "🖥️  System RAM:" in result
        assert "Total: 16.00 GB" in result
        assert "Available: 8.00 GB" in result
        assert "🔄 Swap Memory:" in result
        assert "🐍 Python Process:" in result
        assert "RSS: 512.00 MB" in result
        assert "⚡ CPU Information:" in result
        assert "CPU Cores: 8" in result
        assert "💿 Disk Space" in result
        assert "🧵 Python Stack Information:" in result
    
    # Test database column management
    async def test_add_columns_to_table(self, ai_service):
        """Test adding DICOM tag columns to database table"""
        # Test adding columns to existing table
        result = await ai_service._add_columns_to_table("dicom_images", "PatientName,StudyDate,Modality")
        
        assert "✅ DICOM column addition complete" in result
        assert "Added columns: PatientName, StudyDate, Modality" in result
        
        # Verify columns were actually added
        column_info = await ai_service.db_manager.execute_query("PRAGMA table_info(dicom_images)")
        column_names = [col['name'] for col in column_info]
        assert 'dicom_patientname' in column_names
        assert 'dicom_studydate' in column_names
        assert 'dicom_modality' in column_names
        
        # Test adding duplicate columns (should be skipped)
        result = await ai_service._add_columns_to_table("dicom_images", "PatientName,SeriesNumber")
        assert "Skipped (already exist): PatientName" in result
        assert "Added columns: SeriesNumber" in result
        
        # Test invalid table
        result = await ai_service._add_columns_to_table("nonexistent_table", "PatientName")
        assert "❌ Table 'nonexistent_table' does not exist." in result
    
    async def test_remove_columns_from_table(self, ai_service):
        """Test removing DICOM tag columns from database table"""
        # First add some columns
        await ai_service._add_columns_to_table("dicom_images", "PatientName,StudyDate,Modality")
        
        # Test removing columns
        result = await ai_service._remove_columns_from_table("dicom_images", "PatientName,StudyDate")
        
        assert "✅ DICOM column removal complete" in result
        assert "Removed columns:" in result
        
        # Verify columns were actually removed
        column_info = await ai_service.db_manager.execute_query("PRAGMA table_info(dicom_images)")
        column_names = [col['name'] for col in column_info]
        assert 'dicom_patientname' not in column_names
        assert 'dicom_studydate' not in column_names
        assert 'dicom_modality' in column_names  # Should still exist
        
        # Test removing non-existent columns
        result = await ai_service._remove_columns_from_table("dicom_images", "NonExistent")
        assert "❌ None of the specified DICOM tags exist" in result
    
    # Test migration creation
    async def test_create_new_migration(self, ai_service):
        """Test creating new migrations"""
        result = await ai_service._create_new_migration("TestSite")
        
        assert "✅ New migration created successfully" in result
        assert "Migration ID: migration_TestSite_" in result
        assert "Site: TestSite" in result
        assert "Status: pending" in result
        
        # Verify migration was created in database
        migration_result = await ai_service.db_manager.execute_query(
            "SELECT * FROM migrations WHERE sitename = ?", ("TestSite",)
        )
        assert migration_result
        assert migration_result[0]['sitename'] == 'TestSite'
        assert migration_result[0]['status'] == 'pending'
        
        # Verify site was created
        site_result = await ai_service.db_manager.execute_query(
            "SELECT * FROM site WHERE sitename = ?", ("TestSite",)
        )
        assert site_result
        assert site_result[0]['sitename'] == 'TestSite'
    
    # Test INSERT query with trust level requirement
    async def test_insert_query_trust_requirement(self, ai_service):
        """Test INSERT query function requires appropriate trust level"""
        # Test with low trust level
        ai_service.trust_level = 5
        result = await ai_service._execute_insert_query("INSERT INTO site (sitename) VALUES ('LowTrustTest')")
        assert "❌ INSERT/UPDATE/DELETE queries require trust level 10+" in result
        
        # Test with high trust level
        ai_service.trust_level = 15
        result = await ai_service._execute_insert_query("INSERT INTO site (sitename, status) VALUES ('HighTrustTest', 'active')")
        assert "✅ Query executed successfully" in result
        
        # Verify the insert actually worked
        verify_result = await ai_service.db_manager.execute_query(
            "SELECT * FROM site WHERE sitename = ?", ("HighTrustTest",)
        )
        assert verify_result
        assert verify_result[0]['sitename'] == 'HighTrustTest'
        assert verify_result[0]['status'] == 'active'
    
    # Test dangerous query blocking
    async def test_dangerous_query_blocking(self, ai_service):
        """Test that dangerous queries are blocked"""
        ai_service.trust_level = 20  # Max trust
        
        dangerous_queries = [
            "DROP TABLE site",
            "TRUNCATE TABLE site",
            "DELETE FROM user",
            "UPDATE user SET password = 'hacked'"
        ]
        
        for query in dangerous_queries:
            result = await ai_service._execute_insert_query(query)
            assert "❌ Query contains potentially dangerous pattern" in result or \
                   "Only INSERT, UPDATE, and DELETE queries are allowed" in result
    
    # Test natural language query parsing
    async def test_natural_language_select_parsing(self, ai_service):
        """Test parsing of natural language SELECT queries"""
        # Test simple natural language query
        parsed = ai_service._parse_natural_language_select("select sitename from site")
        assert parsed == "SELECT sitename FROM site"
        
        # Test with multiple columns
        parsed = ai_service._parse_natural_language_select("select sitename, status from site")
        assert parsed == "SELECT sitename, status FROM site"
        
        # Test with 'all' keyword
        parsed = ai_service._parse_natural_language_select("select all from site")
        assert parsed == "SELECT * FROM site"
        
        # Test already proper SQL
        parsed = ai_service._parse_natural_language_select("SELECT * FROM site WHERE status = 'active'")
        assert parsed == "SELECT * FROM site WHERE status = 'active'"
    
    # Test formatted query results
    async def test_formatted_query_results(self, ai_service):
        """Test formatted table output for query results"""
        # Insert test data
        await ai_service.db_manager.execute_query(
            "INSERT INTO sites (sitename, status) VALUES ('Site1', 'active')"
        )
        await ai_service.db_manager.execute_query(
            "INSERT INTO sites (sitename, status) VALUES ('Site2', 'inactive')"
        )
        
        # Execute formatted query
        result = await ai_service._execute_select_query("SELECT sitename, status FROM sites")
        
        assert "📊 Query Results (2 rows):" in result
        assert "│" in result  # Unicode table borders
        assert "├─" in result  # Table separators
        assert "Site1" in result
        assert "Site2" in result
        assert "active" in result
        assert "inactive" in result
        assert "📝 Query executed:" in result


class TestDICOMIntegration:
    """Test suite for DICOM integration functionality"""
    
    @pytest.fixture
    async def ai_service_with_dicom(self):
        """Create AI service with DICOM tables for testing"""
        # Create temporary database
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        
        # Create test settings
        settings = Settings()
        settings.database.url = f"sqlite:///{self.temp_db.name}"
        
        # Create database manager
        db_manager = DatabaseManager(settings)
        await db_manager.initialize()
        
        # Create comprehensive DICOM test tables
        await self._create_dicom_test_tables(db_manager)
        
        # Create AI service
        ai_service = AIService(settings, db_manager)
        ai_service.local_model = MagicMock()
        ai_service.tokenizer = MagicMock()
        ai_service.available_providers = ['test']
        
        yield ai_service
        
        # Cleanup
        await db_manager.close()
        os.unlink(self.temp_db.name)
    
    async def _create_dicom_test_tables(self, db_manager: DatabaseManager):
        """Create DICOM-specific test tables"""
        # Create comprehensive DICOM images table with common tags
        await db_manager.execute_query("""
            CREATE TABLE IF NOT EXISTS dicom_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                patient_id TEXT,
                patient_name TEXT,
                study_uid TEXT,
                study_date TEXT,
                study_description TEXT,
                series_uid TEXT,
                series_number INTEGER,
                series_description TEXT,
                instance_uid TEXT,
                modality TEXT,
                acquisition_date TEXT,
                image_type TEXT,
                rows INTEGER,
                columns INTEGER,
                bits_allocated INTEGER,
                pixel_spacing TEXT,
                slice_thickness REAL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create DICOM studies table
        await db_manager.execute_query("""
            CREATE TABLE IF NOT EXISTS dicom_studies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                study_uid TEXT UNIQUE NOT NULL,
                patient_id TEXT,
                patient_name TEXT,
                study_date TEXT,
                study_description TEXT,
                modality TEXT,
                number_of_series INTEGER DEFAULT 0,
                number_of_instances INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create DICOM series table
        await db_manager.execute_query("""
            CREATE TABLE IF NOT EXISTS dicom_series (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                series_uid TEXT UNIQUE NOT NULL,
                study_uid TEXT NOT NULL,
                series_number INTEGER,
                series_description TEXT,
                modality TEXT,
                number_of_instances INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (study_uid) REFERENCES dicom_studies(study_uid)
            )
        """)
        
        # Insert test DICOM data
        test_data = [
            ("STUDY001", "PAT001", "John Doe", "2024-01-15", "Chest CT", "CT"),
            ("STUDY002", "PAT002", "Jane Smith", "2024-01-16", "Brain MRI", "MR"),
            ("STUDY003", "PAT003", "Bob Johnson", "2024-01-17", "Abdomen US", "US")
        ]
        
        for study_uid, patient_id, patient_name, study_date, description, modality in test_data:
            await db_manager.execute_query("""
                INSERT INTO dicom_studies 
                (study_uid, patient_id, patient_name, study_date, study_description, modality, number_of_series)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (study_uid, patient_id, patient_name, study_date, description, modality, 1))
    
    # Test adding multiple DICOM tags
    async def test_add_multiple_dicom_tags(self, ai_service_with_dicom):
        """Test adding multiple DICOM tags to table"""
        ai_service = ai_service_with_dicom
        
        # Add multiple DICOM tags at once
        result = await ai_service._add_columns_to_table(
            "dicom_images", 
            "WindowCenter,WindowWidth,RescaleIntercept,RescaleSlope,ContrastBolusAgent"
        )
        
        assert "✅ DICOM column addition complete" in result
        assert "WindowCenter, WindowWidth, RescaleIntercept, RescaleSlope, ContrastBolusAgent" in result
        
        # Verify all columns were added
        column_info = await ai_service.db_manager.execute_query("PRAGMA table_info(dicom_images)")
        column_names = [col['name'].lower() for col in column_info]
        
        expected_columns = [
            'dicom_windowcenter',
            'dicom_windowwidth', 
            'dicom_rescaleintercept',
            'dicom_rescaleslope',
            'dicom_contrastbolusagent'
        ]
        
        for expected_col in expected_columns:
            assert expected_col in column_names
    
    # Test removing multiple DICOM tags
    async def test_remove_multiple_dicom_tags(self, ai_service_with_dicom):
        """Test removing multiple DICOM tags from table"""
        ai_service = ai_service_with_dicom
        
        # First add tags
        await ai_service._add_columns_to_table(
            "dicom_images", 
            "WindowCenter,WindowWidth,RescaleIntercept"
        )
        
        # Then remove some of them
        result = await ai_service._remove_columns_from_table(
            "dicom_images",
            "WindowCenter,WindowWidth"
        )
        
        assert "✅ DICOM column removal complete" in result
        
        # Verify columns were removed but others remain
        column_info = await ai_service.db_manager.execute_query("PRAGMA table_info(dicom_images)")
        column_names = [col['name'].lower() for col in column_info]
        
        assert 'dicom_windowcenter' not in column_names
        assert 'dicom_windowwidth' not in column_names
        assert 'dicom_rescaleintercept' in column_names  # Should still exist
    
    # Test C-FIND query simulation
    async def test_cfind_query_simulation(self, ai_service_with_dicom):
        """Test C-FIND query based on added DICOM tags"""
        ai_service = ai_service_with_dicom
        
        # Add DICOM tags we'll query on
        await ai_service._add_columns_to_table("dicom_studies", "PatientAge,StudyTime,ReferringPhysician")
        
        # Insert test image data with DICOM tags
        await ai_service.db_manager.execute_query("""
            INSERT INTO dicom_images 
            (patient_id, study_uid, file_path, modality)
            VALUES ('PAT001', 'STUDY001', '/tmp/test_image.dcm', 'CT')
        """)
        
        # Simulate C-FIND query using natural language
        cfind_query = "select patient_name, study_date, modality from dicom_studies where modality = 'CT'"
        result = await ai_service._execute_select_query(cfind_query)
        
        assert "📊 Query Results" in result
        assert "John Doe" in result
        assert "2024-01-15" in result
        assert "CT" in result
        
        # Test more complex C-FIND with multiple criteria
        complex_query = "SELECT patient_name, study_description FROM dicom_studies WHERE modality IN ('CT', 'MR') AND study_date >= '2024-01-15'"
        result = await ai_service._execute_select_query(complex_query)
        
        assert "📊 Query Results" in result
        assert "John Doe" in result or "Jane Smith" in result
    
    # Test image insertion and metadata
    async def test_image_insertion_with_metadata(self, ai_service_with_dicom):
        """Test inserting image records with comprehensive metadata"""
        ai_service = ai_service_with_dicom
        
        # Set high trust level for INSERT operations
        ai_service.trust_level = 15
        
        # Insert comprehensive DICOM image record
        insert_query = """
            INSERT INTO dicom_images 
            (file_path, patient_id, patient_name, study_uid, study_date, 
             series_uid, series_number, instance_uid, modality, rows, columns)
            VALUES 
            ('/data/dicom/patient123_ct_001.dcm', 'PAT123', 'Test Patient', 
             'STUDY123', '2024-01-20', 'SERIES123', 1, 'INSTANCE123', 'CT', 512, 512)
        """
        
        result = await ai_service._execute_insert_query(insert_query)
        assert "✅ Query executed successfully" in result
        
        # Verify the image was inserted correctly
        verify_query = "SELECT * FROM dicom_images WHERE patient_id = 'PAT123'"
        result = await ai_service._execute_select_query(verify_query)
        
        assert "Test Patient" in result
        assert "STUDY123" in result
        assert "CT" in result
        assert "512" in result
    

class TestDICOMWorkflow:
    """Test complete DICOM workflow scenarios"""
    
    @pytest.fixture
    async def workflow_service(self):
        """Create AI service for workflow testing"""
        # Create temporary database
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        
        # Create test settings
        settings = Settings()
        settings.database.url = f"sqlite:///{self.temp_db.name}"
        
        # Create database manager
        db_manager = DatabaseManager(settings)
        await db_manager.initialize()
        
        # Create workflow test tables
        await self._create_workflow_tables(db_manager)
        
        # Create AI service with high trust
        ai_service = AIService(settings, db_manager)
        ai_service.local_model = MagicMock()
        ai_service.tokenizer = MagicMock()
        ai_service.available_providers = ['test']
        ai_service.trust_level = 20  # Max trust for testing
        
        yield ai_service
        
        # Cleanup
        await db_manager.close()
        os.unlink(self.temp_db.name)
    
    async def _create_workflow_tables(self, db_manager: DatabaseManager):
        """Create tables for workflow testing"""
        # Create DICOM instances table for comprehensive testing
        await db_manager.execute_query("""
            CREATE TABLE IF NOT EXISTS dicom_instances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                patient_id TEXT,
                study_uid TEXT,
                series_uid TEXT,
                instance_uid TEXT,
                transfer_status TEXT DEFAULT 'pending',
                destination_ae TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create transfer log table
        await db_manager.execute_query("""
            CREATE TABLE IF NOT EXISTS transfer_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id INTEGER,
                destination_ae TEXT,
                transfer_date DATETIME,
                status TEXT,
                error_message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (instance_id) REFERENCES dicom_instances(id)
            )
        """)
    
    async def test_complete_dicom_workflow(self, workflow_service):
        """Test complete DICOM workflow: add tags -> insert image -> query -> transfer"""
        ai_service = workflow_service
        
        # Step 1: Add DICOM tags to instances table
        tag_result = await ai_service._add_columns_to_table(
            "dicom_instances",
            "PatientName,StudyDescription,SeriesDescription,ImageType,AcquisitionMatrix"
        )
        assert "✅ DICOM column addition complete" in tag_result
        
        # Step 2: Insert a DICOM image record
        insert_query = """
            INSERT INTO dicom_instances 
            (file_path, patient_id, study_uid, series_uid, instance_uid, transfer_status)
            VALUES 
            ('/data/ct_chest_001.dcm', 'PAT001', 'ST001', 'SE001', 'IN001', 'pending')
        """
        insert_result = await ai_service._execute_insert_query(insert_query)
        assert "✅ Query executed successfully" in insert_result
        
        # Step 3: Perform C-FIND style query to locate the image
        cfind_query = "select patient_id, study_uid, file_path, transfer_status from dicom_instances where patient_id = 'PAT001'"
        cfind_result = await ai_service._execute_select_query(cfind_query)
        
        assert "📊 Query Results (1 rows):" in cfind_result
        assert "PAT001" in cfind_result
        assert "ST001" in cfind_result
        assert "/data/ct_chest_001.dcm" in cfind_result
        assert "pending" in cfind_result
        
        # Step 4: Simulate image transfer to another instance
        transfer_query = """
            UPDATE dicom_instances 
            SET transfer_status = 'completed', destination_ae = 'REMOTE_AE' 
            WHERE patient_id = 'PAT001'
        """
        transfer_result = await ai_service._execute_insert_query(transfer_query)
        assert "✅ Query executed successfully" in transfer_result
        
        # Step 5: Log the transfer
        log_query = """
            INSERT INTO transfer_log 
            (instance_id, destination_ae, transfer_date, status) 
            VALUES 
            ((SELECT id FROM dicom_instances WHERE patient_id = 'PAT001'), 
             'REMOTE_AE', datetime('now'), 'success')
        """
        log_result = await ai_service._execute_insert_query(log_query)
        assert "✅ Query executed successfully" in log_result
        
        # Step 6: Verify complete workflow with final query
        final_query = """
            SELECT 
                di.patient_id, di.file_path, di.transfer_status, 
                tl.destination_ae, tl.transfer_date, tl.status as transfer_result
            FROM dicom_instances di
            LEFT JOIN transfer_log tl ON di.id = tl.instance_id
            WHERE di.patient_id = 'PAT001'
        """
        final_result = await ai_service._execute_select_query(final_query)
        
        assert "PAT001" in final_result
        assert "completed" in final_result
        assert "REMOTE_AE" in final_result
        assert "success" in final_result
    
    async def test_dicom_tag_cleanup_workflow(self, workflow_service):
        """Test workflow for cleaning up unused DICOM tags"""
        ai_service = workflow_service
        
        # Add multiple DICOM tags
        await ai_service._add_columns_to_table(
            "dicom_instances",
            "ContrastAgent,ExposureTime,KVP,mAs,FilterType,CollimatorShape"
        )
        
        # Verify all tags were added
        column_info = await ai_service.db_manager.execute_query("PRAGMA table_info(dicom_instances)")
        original_count = len(column_info)
        
        # Remove some tags that are no longer needed
        remove_result = await ai_service._remove_columns_from_table(
            "dicom_instances",
            "ExposureTime,FilterType,CollimatorShape"
        )
        
        assert "✅ DICOM column removal complete" in remove_result
        
        # Verify tags were removed
        updated_column_info = await ai_service.db_manager.execute_query("PRAGMA table_info(dicom_instances)")
        updated_count = len(updated_column_info)
        
        # Should have 3 fewer columns
        assert updated_count == original_count - 3
        
        # Verify specific columns remain
        remaining_names = [col['name'].lower() for col in updated_column_info]
        assert 'dicom_contrastagent' in remaining_names
        assert 'dicom_kvp' in remaining_names
        assert 'dicom_mas' in remaining_names
        assert 'dicom_exposuretime' not in remaining_names
        assert 'dicom_filtertype' not in remaining_names


if __name__ == "__main__":
    """Run tests directly with asyncio"""
    
    async def run_tests():
        """Run all tests manually without pytest"""
        print("🧪 Starting AI Functions Test Suite...")
        print("=" * 60)
        
        # Test basic AI functions
        print("\n📋 Testing AI Functions...")
        test_ai = TestAIFunctions()
        
        try:
            async for ai_service in test_ai.ai_service():
                await test_ai.test_lets_make_a_deal(ai_service)
                print("✅ Let's Make a Deal test passed")
                
                await test_ai.test_fibonacci_sequence(ai_service)
                print("✅ Fibonacci sequence test passed")
                
                await test_ai.test_reverse_turing_test(ai_service)
                print("✅ Reverse Turing test passed")
                
                await test_ai.test_trust_level_management(ai_service)
                print("✅ Trust level management test passed")
                
                await test_ai.test_aggression_level_management(ai_service)
                print("✅ Aggression level management test passed")
                
                await test_ai.test_natural_language_select_parsing(ai_service)
                print("✅ Natural language parsing test passed")
                
                break  # Only run once
        except Exception as e:
            print(f"❌ AI Functions test failed: {e}")
        
        # Test DICOM integration
        print("\n📋 Testing DICOM Integration...")
        test_dicom = TestDICOMIntegration()
        
        try:
            async for ai_service in test_dicom.ai_service_with_dicom():
                await test_dicom.test_add_multiple_dicom_tags(ai_service)
                print("✅ Add multiple DICOM tags test passed")
                
                await test_dicom.test_remove_multiple_dicom_tags(ai_service)
                print("✅ Remove multiple DICOM tags test passed")
                
                break  # Only run once
        except Exception as e:
            print(f"❌ DICOM Integration test failed: {e}")
        
        # Test complete workflow
        print("\n📋 Testing Complete DICOM Workflow...")
        test_workflow = TestDICOMWorkflow()
        
        try:
            async for ai_service in test_workflow.workflow_service():
                await test_workflow.test_complete_dicom_workflow(ai_service)
                print("✅ Complete DICOM workflow test passed")
                
                await test_workflow.test_dicom_tag_cleanup_workflow(ai_service)
                print("✅ DICOM tag cleanup workflow test passed")
                
                break  # Only run once
        except Exception as e:
            print(f"❌ DICOM Workflow test failed: {e}")
        
        print("\n🎉 Test suite completed!")
        print("=" * 60)
    
    # Run the tests
    if len(sys.argv) > 1 and sys.argv[1] == "--run":
        asyncio.run(run_tests())
    else:
        print("Test file created. Run with 'python test_ai_functions.py --run' to execute tests.")
        print("Or use 'pytest tests/test_ai_functions.py' for full pytest integration.")
