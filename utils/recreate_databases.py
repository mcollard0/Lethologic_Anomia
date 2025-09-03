#!/usr/bin/env python3
"""
Database Recreation Script

This script drops and recreates the databases from scratch with proper schema
to resolve any SQL errors or corruption issues.
"""

import os
import sqlite3
import sys
from datetime import datetime

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def create_main_database(db_path: str):
    """Create the main lethologic_anomia.db with full schema"""
    
    # Remove existing database
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"🗑️  Removed existing database: {db_path}")
    
    # Create new database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print(f"🆕 Creating new database: {db_path}")
    
    # Core tables
    cursor.execute("""
        CREATE TABLE config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(255) UNIQUE NOT NULL,
            value TEXT NOT NULL,
            description TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE site (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            enabled BOOLEAN NOT NULL DEFAULT 1,
            deleted BOOLEAN NOT NULL DEFAULT 0,
            sitename VARCHAR(255) UNIQUE NOT NULL,
            status VARCHAR(50),
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE device (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT 1,
            deleted BOOLEAN NOT NULL DEFAULT 0,
            device_name VARCHAR(255) NOT NULL,
            ip_address VARCHAR(45),
            port INTEGER,
            ae_title VARCHAR(16),
            device_type VARCHAR(50),
            status VARCHAR(50),
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(site_id) REFERENCES site (id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE service (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id TEXT UNIQUE NOT NULL,
            instance_id TEXT NOT NULL,
            service_type TEXT NOT NULL,
            service_name TEXT,
            auto_started BOOLEAN DEFAULT FALSE,
            execution_mode TEXT DEFAULT 'thread',
            host TEXT DEFAULT '0.0.0.0',
            port INTEGER,
            ssl_enabled BOOLEAN DEFAULT FALSE,
            target_host TEXT,
            target_port INTEGER,
            config_json TEXT,
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_heartbeat DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_ping DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'running',
            pid INTEGER,
            manager_id TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(255) UNIQUE NOT NULL,
            email VARCHAR(255),
            password_hash VARCHAR(255),
            role VARCHAR(50) DEFAULT 'user',
            active BOOLEAN DEFAULT TRUE,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # DICOM tables
    cursor.execute("""
        CREATE TABLE study (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_uid VARCHAR(64) UNIQUE NOT NULL,
            study_date DATETIME,
            study_time VARCHAR(16),
            study_description VARCHAR(64),
            patient_name VARCHAR(64),
            patient_id VARCHAR(64),
            patient_birth_date DATETIME,
            patient_sex VARCHAR(1),
            modality VARCHAR(16),
            institution_name VARCHAR(64),
            study_status INTEGER,
            site_id INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(site_id) REFERENCES site (id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_uid VARCHAR(64) UNIQUE NOT NULL,
            study_id INTEGER NOT NULL,
            series_number INTEGER,
            series_description VARCHAR(64),
            modality VARCHAR(16),
            body_part VARCHAR(16),
            series_date DATETIME,
            series_time VARCHAR(16),
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(study_id) REFERENCES study (id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE image (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sop_instance_uid VARCHAR(64) UNIQUE NOT NULL,
            series_id INTEGER NOT NULL,
            instance_number INTEGER,
            file_path VARCHAR(512),
            file_size INTEGER,
            acquisition_date DATETIME,
            acquisition_time VARCHAR(16),
            image_type VARCHAR(128),
            pixel_spacing VARCHAR(32),
            rows INTEGER,
            columns INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(series_id) REFERENCES series (id)
        )
    """)
    
    # HL7 tables
    cursor.execute("""
        CREATE TABLE hl7_message (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            processing_id VARCHAR(100) UNIQUE NOT NULL,
            message_type VARCHAR(10) NOT NULL,
            message_text TEXT NOT NULL,
            source_address VARCHAR(100) NOT NULL,
            received_at DATETIME NOT NULL,
            processed_at DATETIME,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE hl7_adt (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id VARCHAR(100) NOT NULL,
            name VARCHAR(200),
            dob VARCHAR(20),
            sex VARCHAR(1),
            received_at DATETIME NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE hl7_order (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number VARCHAR(100),
            order_control VARCHAR(10),
            procedure_code VARCHAR(100),
            received_at DATETIME NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE hl7_processing_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            processing_id VARCHAR(100) NOT NULL,
            status VARCHAR(20) NOT NULL,
            message TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE hl7_workflow (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id VARCHAR(100) UNIQUE NOT NULL,
            message_type VARCHAR(10) NOT NULL,
            steps TEXT NOT NULL,
            retry_count INTEGER DEFAULT 3,
            retry_delay_seconds INTEGER DEFAULT 60,
            enabled BOOLEAN DEFAULT 1,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # FHIR tables
    cursor.execute("""
        CREATE TABLE fhir_resource (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_type VARCHAR(50) NOT NULL,
            resource_id VARCHAR(100),
            version_id VARCHAR(50),
            data TEXT NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE fhir_endpoint (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint_id VARCHAR(100) UNIQUE NOT NULL,
            base_url VARCHAR(500) NOT NULL,
            auth_type VARCHAR(20) NOT NULL,
            auth_config TEXT,
            timeout_seconds INTEGER DEFAULT 30,
            enabled BOOLEAN DEFAULT 1,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE dicom_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename VARCHAR(255) NOT NULL,
            file_path VARCHAR(512),
            file_size INTEGER,
            dicom_tags TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Essential indexes only (for larger tables)
    indexes = [
        "CREATE INDEX idx_config_name ON config(name)",
        "CREATE INDEX idx_site_sitename ON site(sitename)",
        "CREATE INDEX idx_service_type ON service(service_type)",
        "CREATE INDEX idx_service_id ON service(service_id)",
        "CREATE INDEX idx_study_uid ON study(study_uid)",
        "CREATE INDEX idx_series_uid ON series(series_uid)",
        "CREATE INDEX idx_image_sop_uid ON image(sop_instance_uid)",
        "CREATE INDEX idx_hl7_message_processing_id ON hl7_message(processing_id)"
    ]
    
    for index_sql in indexes:
        cursor.execute(index_sql)
    
    # Insert some default configuration
    default_configs = [
        ('database_version', '1.0.0', 'Current database schema version'),
        ('system_initialized', 'true', 'Whether system has been initialized'),
        ('auto_start_services', 'true', 'Whether to auto-start core services')
    ]
    
    for name, value, description in default_configs:
        cursor.execute(
            "INSERT OR IGNORE INTO config (name, value, description) VALUES (?, ?, ?)",
            (name, value, description)
        )
    
    # Insert default site
    cursor.execute(
        "INSERT OR IGNORE INTO site (sitename, status) VALUES (?, ?)",
        ('default', 'active')
    )
    
    conn.commit()
    conn.close()
    print(f"✅ Created main database with {len(default_configs)} default configs")

def create_migration_database(db_path: str):
    """Create the lethologic_anomia.db with service-specific schema"""
    
    # Remove existing database
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"🗑️  Removed existing database: {db_path}")
    
    # Create new database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print(f"🆕 Creating new migration database: {db_path}")
    
    # Core service tables (simplified for migration service)
    cursor.execute("""
        CREATE TABLE config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(255) UNIQUE NOT NULL,
            value TEXT NOT NULL,
            description TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE site (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            enabled BOOLEAN NOT NULL DEFAULT 1,
            deleted BOOLEAN NOT NULL DEFAULT 0,
            sitename VARCHAR(255) UNIQUE NOT NULL,
            status VARCHAR(50),
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(255) UNIQUE NOT NULL,
            email VARCHAR(255),
            password_hash VARCHAR(255),
            role VARCHAR(50) DEFAULT 'user',
            active BOOLEAN DEFAULT TRUE,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE service (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id TEXT UNIQUE NOT NULL,
            instance_id TEXT NOT NULL,
            service_type TEXT NOT NULL,
            service_name TEXT,
            auto_started BOOLEAN DEFAULT FALSE,
            execution_mode TEXT DEFAULT 'thread',
            host TEXT DEFAULT '0.0.0.0',
            port INTEGER,
            ssl_enabled BOOLEAN DEFAULT FALSE,
            target_host TEXT,
            target_port INTEGER,
            config_json TEXT,
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_heartbeat DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_ping DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'running',
            pid INTEGER,
            manager_id TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE device (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT 1,
            deleted BOOLEAN NOT NULL DEFAULT 0,
            device_name VARCHAR(255) NOT NULL,
            ip_address VARCHAR(45),
            port INTEGER,
            ae_title VARCHAR(16),
            device_type VARCHAR(50),
            status VARCHAR(50),
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(site_id) REFERENCES site (id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE study (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_uid VARCHAR(64) UNIQUE NOT NULL,
            study_date DATETIME,
            study_time VARCHAR(16),
            study_description VARCHAR(64),
            patient_name VARCHAR(64),
            patient_id VARCHAR(64),
            patient_birth_date DATETIME,
            patient_sex VARCHAR(1),
            modality VARCHAR(16),
            institution_name VARCHAR(64),
            study_status INTEGER,
            site_id INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(site_id) REFERENCES site (id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_uid VARCHAR(64) UNIQUE NOT NULL,
            study_id INTEGER NOT NULL,
            series_number INTEGER,
            series_description VARCHAR(64),
            modality VARCHAR(16),
            body_part VARCHAR(16),
            series_date DATETIME,
            series_time VARCHAR(16),
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(study_id) REFERENCES study (id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE image (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sop_instance_uid VARCHAR(64) UNIQUE NOT NULL,
            series_id INTEGER NOT NULL,
            instance_number INTEGER,
            file_path VARCHAR(512),
            file_size INTEGER,
            acquisition_date DATETIME,
            acquisition_time VARCHAR(16),
            image_type VARCHAR(128),
            pixel_spacing VARCHAR(32),
            rows INTEGER,
            columns INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(series_id) REFERENCES series (id)
        )
    """)
    
    # Essential indexes
    indexes = [
        "CREATE INDEX idx_config_name ON config(name)",
        "CREATE INDEX idx_site_sitename ON site(sitename)",
        "CREATE INDEX idx_service_type ON service(service_type)",
        "CREATE INDEX idx_service_id ON service(service_id)"
    ]
    
    for index_sql in indexes:
        cursor.execute(index_sql)
    
    # Insert default data
    default_configs = [
        ('database_version', '1.0.0', 'Current database schema version'),
        ('migration_service_version', '1.0.0', 'Migration service database version')
    ]
    
    for name, value, description in default_configs:
        cursor.execute(
            "INSERT INTO config (name, value, description) VALUES (?, ?, ?)",
            (name, value, description)
        )
    
    # Insert default site
    cursor.execute(
        "INSERT INTO site (sitename, status) VALUES (?, ?)",
        ('migration_default', 'active')
    )
    
    conn.commit()
    conn.close()
    print(f"✅ Created migration database with essential tables and indexes")

def main():
    """Main function to recreate both databases"""
    
    print("🚀 Database Recreation Script")
    print("=" * 60)
    
    # Database paths
    main_db = "/home/michael/FASTESTARCHIVE/Archive/Lethologic Anomia/lethologic_anomia.db"
    migration_db = "/home/michael/FASTESTARCHIVE/Archive/Lethologic Anomia/lethologic_anomia.db"
    
    try:
        # Recreate main database
        create_main_database(main_db)
        
        # Recreate migration database
        create_migration_database(migration_db)
        
        print("\n🎉 Both databases recreated successfully!")
        print("✅ All SQL errors should now be resolved")
        
    except Exception as e:
        print(f"❌ Error recreating databases: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
