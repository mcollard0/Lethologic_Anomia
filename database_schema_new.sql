-- New Normalized Database Schema for Lethologic Anomia
-- Features: Singular table names, normalized site/device structure, HL7/FHIR support, plural views

-- =================================================================
-- CORE TABLES (SINGULAR NAMES)
-- =================================================================

-- Log entries table
CREATE TABLE IF NOT EXISTS log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    level VARCHAR(20) NOT NULL,
    module VARCHAR(100) NOT NULL,
    function VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    thread_id INTEGER,
    process_id INTEGER,
    exception TEXT
);

-- Configuration entries table
CREATE TABLE IF NOT EXISTS config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) UNIQUE NOT NULL,
    value TEXT NOT NULL,
    description TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Site table (normalized - basic site information only)
CREATE TABLE IF NOT EXISTS site (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    deleted BOOLEAN NOT NULL DEFAULT 0,
    sitename VARCHAR(255) UNIQUE NOT NULL,
    status VARCHAR(50),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Device table (technical connection details)
CREATE TABLE IF NOT EXISTS device (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    deleted BOOLEAN NOT NULL DEFAULT 0,
    device_name VARCHAR(255) NOT NULL,
    ip_address VARCHAR(45),
    port INTEGER,
    ae_title VARCHAR(16),
    device_type VARCHAR(50), -- DICOM_SCP, DICOM_SCU, HL7_LISTENER, etc.
    status VARCHAR(50),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(site_id) REFERENCES site (id)
);

-- Study table (singular)
CREATE TABLE IF NOT EXISTS study (
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
);

-- Series table (singular)
CREATE TABLE IF NOT EXISTS series (
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
);

-- Image table (singular)
CREATE TABLE IF NOT EXISTS image (
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
);

-- =================================================================
-- HL7 MESSAGE STORAGE TABLES (SINGULAR NAMES)
-- =================================================================

-- Full HL7 messages storage (from HL7 processor)
CREATE TABLE IF NOT EXISTS hl7_message (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processing_id VARCHAR(100) UNIQUE NOT NULL,
    message_type VARCHAR(10) NOT NULL,
    message_text TEXT NOT NULL,
    source_address VARCHAR(100) NOT NULL,
    received_at DATETIME NOT NULL,
    processed_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ADT message parsed data (from HL7 listener)
CREATE TABLE IF NOT EXISTS hl7_adt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id VARCHAR(100) NOT NULL,
    name VARCHAR(200),
    dob VARCHAR(20),
    sex VARCHAR(1),
    received_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ORM order message parsed data (from HL7 listener)
CREATE TABLE IF NOT EXISTS hl7_order (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_number VARCHAR(100),
    order_control VARCHAR(10),
    procedure_code VARCHAR(100),
    received_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- HL7 message processing status tracking (from HL7 processor)
CREATE TABLE IF NOT EXISTS hl7_processing_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processing_id VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL, -- pending, processing, processed, failed, retrying
    message TEXT,
    updated_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- HL7 workflow configuration (from HL7 processor)
CREATE TABLE IF NOT EXISTS hl7_workflow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id VARCHAR(100) UNIQUE NOT NULL,
    message_type VARCHAR(10) NOT NULL,
    steps TEXT NOT NULL, -- JSON array of workflow steps
    retry_count INTEGER DEFAULT 3,
    retry_delay_seconds INTEGER DEFAULT 60,
    enabled BOOLEAN DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =================================================================
-- FHIR RESOURCE STORAGE TABLES (SINGULAR NAMES)
-- =================================================================

-- FHIR resources storage (from FHIR interface)
CREATE TABLE IF NOT EXISTS fhir_resource (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_type VARCHAR(50) NOT NULL,
    resource_id VARCHAR(100),
    version_id VARCHAR(50),
    data TEXT NOT NULL, -- JSON data of the FHIR resource
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

-- FHIR endpoints configuration (from FHIR interface)
CREATE TABLE IF NOT EXISTS fhir_endpoint (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint_id VARCHAR(100) UNIQUE NOT NULL,
    base_url VARCHAR(500) NOT NULL,
    auth_type VARCHAR(20) NOT NULL, -- none, bearer, basic, oauth2
    auth_config TEXT, -- JSON configuration for authentication
    timeout_seconds INTEGER DEFAULT 30,
    enabled BOOLEAN DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =================================================================
-- INDEXES FOR PERFORMANCE
-- =================================================================

-- Core table indexes
CREATE INDEX IF NOT EXISTS idx_log_timestamp ON log(timestamp);
CREATE INDEX IF NOT EXISTS idx_log_level ON log(level);
CREATE INDEX IF NOT EXISTS idx_config_name ON config(name);

-- Site and device indexes
CREATE INDEX IF NOT EXISTS idx_site_sitename ON site(sitename);
CREATE INDEX IF NOT EXISTS idx_site_enabled ON site(enabled);
CREATE INDEX IF NOT EXISTS idx_site_deleted ON site(deleted);
CREATE INDEX IF NOT EXISTS idx_device_site_id ON device(site_id);
CREATE INDEX IF NOT EXISTS idx_device_enabled ON device(enabled);
CREATE INDEX IF NOT EXISTS idx_device_deleted ON device(deleted);
CREATE INDEX IF NOT EXISTS idx_device_ip_port ON device(ip_address, port);

-- DICOM table indexes
CREATE INDEX IF NOT EXISTS idx_study_uid ON study(study_uid);
CREATE INDEX IF NOT EXISTS idx_study_patient_id ON study(patient_id);
CREATE INDEX IF NOT EXISTS idx_study_date ON study(study_date);
CREATE INDEX IF NOT EXISTS idx_study_site_id ON study(site_id);

CREATE INDEX IF NOT EXISTS idx_series_uid ON series(series_uid);
CREATE INDEX IF NOT EXISTS idx_series_study_id ON series(study_id);

CREATE INDEX IF NOT EXISTS idx_image_sop_uid ON image(sop_instance_uid);
CREATE INDEX IF NOT EXISTS idx_image_series_id ON image(series_id);

-- HL7 message indexes
CREATE INDEX IF NOT EXISTS idx_hl7_message_processing_id ON hl7_message(processing_id);
CREATE INDEX IF NOT EXISTS idx_hl7_message_type ON hl7_message(message_type);
CREATE INDEX IF NOT EXISTS idx_hl7_message_received_at ON hl7_message(received_at);

CREATE INDEX IF NOT EXISTS idx_hl7_adt_patient_id ON hl7_adt(patient_id);
CREATE INDEX IF NOT EXISTS idx_hl7_adt_received_at ON hl7_adt(received_at);

CREATE INDEX IF NOT EXISTS idx_hl7_order_number ON hl7_order(order_number);
CREATE INDEX IF NOT EXISTS idx_hl7_order_received_at ON hl7_order(received_at);

CREATE INDEX IF NOT EXISTS idx_hl7_processing_status_processing_id ON hl7_processing_status(processing_id);
CREATE INDEX IF NOT EXISTS idx_hl7_processing_status_status ON hl7_processing_status(status);
CREATE INDEX IF NOT EXISTS idx_hl7_processing_status_updated_at ON hl7_processing_status(updated_at);

CREATE INDEX IF NOT EXISTS idx_hl7_workflow_workflow_id ON hl7_workflow(workflow_id);
CREATE INDEX IF NOT EXISTS idx_hl7_workflow_enabled ON hl7_workflow(enabled);

-- FHIR resource indexes
CREATE INDEX IF NOT EXISTS idx_fhir_resource_type_id ON fhir_resource(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_fhir_resource_created_at ON fhir_resource(created_at);
CREATE INDEX IF NOT EXISTS idx_fhir_resource_updated_at ON fhir_resource(updated_at);

CREATE INDEX IF NOT EXISTS idx_fhir_endpoint_endpoint_id ON fhir_endpoint(endpoint_id);
CREATE INDEX IF NOT EXISTS idx_fhir_endpoint_enabled ON fhir_endpoint(enabled);

-- =================================================================
-- VIEWS FOR PLURAL ALIASES (BACKWARD COMPATIBILITY)
-- =================================================================

-- Core table plural views
CREATE VIEW IF NOT EXISTS logs AS SELECT * FROM log;
CREATE VIEW IF NOT EXISTS configs AS SELECT * FROM config;
CREATE VIEW IF NOT EXISTS sites AS SELECT * FROM site;
CREATE VIEW IF NOT EXISTS devices AS SELECT * FROM device;
CREATE VIEW IF NOT EXISTS studies AS SELECT * FROM study;

-- DICOM plural views (for backward compatibility)
CREATE VIEW IF NOT EXISTS images AS SELECT * FROM image;

-- HL7 plural views
CREATE VIEW IF NOT EXISTS hl7_messages AS SELECT * FROM hl7_message;
CREATE VIEW IF NOT EXISTS hl7_orders AS SELECT * FROM hl7_order;
CREATE VIEW IF NOT EXISTS hl7_workflows AS SELECT * FROM hl7_workflow;

-- FHIR plural views
CREATE VIEW IF NOT EXISTS fhir_resources AS SELECT * FROM fhir_resource;
CREATE VIEW IF NOT EXISTS fhir_endpoints AS SELECT * FROM fhir_endpoint;

-- Additional aliases for devices
CREATE VIEW IF NOT EXISTS client AS SELECT * FROM device;
CREATE VIEW IF NOT EXISTS clients AS SELECT * FROM device;

-- =================================================================
-- DEFAULT DATA INSERTION
-- =================================================================

-- Insert default FHIR endpoint
INSERT OR IGNORE INTO fhir_endpoint (endpoint_id, base_url, auth_type, auth_config, enabled) 
VALUES ('default', 'http://localhost:8080/fhir', 'none', '{}', 1);

-- Insert default HL7 workflows
INSERT OR IGNORE INTO hl7_workflow (workflow_id, message_type, steps, retry_count, retry_delay_seconds, enabled)
VALUES 
    ('ADT_default', 'ADT', '["validate", "store", "fhir_convert"]', 3, 60, 1),
    ('ORM_default', 'ORM', '["validate", "store", "fhir_convert"]', 3, 60, 1),
    ('ORU_default', 'ORU', '["validate", "store", "fhir_convert"]', 3, 60, 1),
    ('ACK_simple', 'ACK', '["validate", "store"]', 1, 30, 1);

-- =================================================================
-- SCHEMA DOCUMENTATION
-- =================================================================

/*
SCHEMA CHANGES SUMMARY:
1. All table names are now singular (study, series, image, etc.)
2. Sites table normalized into site + device tables
3. Added HL7 and FHIR tables with singular names
4. Added enabled/deleted flags for soft deletes
5. Created plural views for backward compatibility
6. Added device table for technical connection details
7. Added proper indexing for performance
8. Database name changed to lethologic_anomia.db

SITE/DEVICE NORMALIZATION:
- site table: Basic site information (id, enabled, deleted, sitename, status, created_at, updated_at)
- device table: Technical details (ip_address, port, ae_title, device_type)
- Views: devices, clients, devices for backward compatibility

BACKWARD COMPATIBILITY:
- All existing plural table references work via views
- Existing code should continue to work without modification
- New code should use singular table names
*/
