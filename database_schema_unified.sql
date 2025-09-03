-- Unified Database Schema for Lethologic Anomia
-- Single database design with singular table names and comprehensive coverage
-- Merges functionality from both lethologic_anomia.db and migration_service.db

-- =================================================================
-- CORE SYSTEM TABLES (SINGULAR NAMES)
-- =================================================================

-- Configuration entries table (supports hierarchical service-based config)
CREATE TABLE IF NOT EXISTS config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) UNIQUE NOT NULL,
    value TEXT NOT NULL,
    description TEXT,
    service VARCHAR(64),  -- Optional service grouping (e.g., 'dicom_scp', 'web_interface')
    value_type VARCHAR(20) DEFAULT 'string',  -- string, integer, boolean, json
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

-- User table for authentication and access control
CREATE TABLE IF NOT EXISTS user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255),
    password_hash VARCHAR(255),
    role VARCHAR(50) DEFAULT 'user',
    active BOOLEAN DEFAULT TRUE,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    deleted BOOLEAN NOT NULL DEFAULT 0,
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

-- Service table for managing system services configuration and runtime state
CREATE TABLE IF NOT EXISTS service (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id TEXT UNIQUE NOT NULL,
    instance_id TEXT NOT NULL,
    service_type TEXT NOT NULL,
    service_name TEXT,
    auto_started BOOLEAN DEFAULT FALSE,
    enabled BOOLEAN DEFAULT TRUE,
    singleton BOOLEAN DEFAULT TRUE,  -- Multiple instances allowed?
    execution_mode TEXT DEFAULT 'thread',
    host TEXT DEFAULT '0.0.0.0',
    port INTEGER,
    ssl_enabled BOOLEAN DEFAULT FALSE,
    target_host TEXT,
    target_port INTEGER,
    config_json TEXT,
    settings_json TEXT,  -- Additional JSON settings
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_heartbeat DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_ping DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'running',
    pid INTEGER,
    manager_id TEXT,
    description TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =================================================================
-- DICOM DATA TABLES (SINGULAR NAMES)
-- =================================================================

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

-- DICOM files table for file tracking
CREATE TABLE IF NOT EXISTS dicom_file (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename VARCHAR(255) NOT NULL,
    file_path VARCHAR(512),
    file_size INTEGER,
    dicom_tags TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =================================================================
-- HL7 MESSAGE STORAGE TABLES (SINGULAR NAMES)
-- =================================================================

-- Full HL7 messages storage
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

-- ADT message parsed data
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

-- ORM order message parsed data
CREATE TABLE IF NOT EXISTS hl7_order (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_number VARCHAR(100),
    order_control VARCHAR(10),
    procedure_code VARCHAR(100),
    received_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- HL7 message processing status tracking
CREATE TABLE IF NOT EXISTS hl7_processing_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processing_id VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL, -- pending, processing, processed, failed, retrying
    message TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- HL7 workflow configuration
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

-- FHIR resources storage
CREATE TABLE IF NOT EXISTS fhir_resource (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_type VARCHAR(50) NOT NULL,
    resource_id VARCHAR(100),
    version_id VARCHAR(50),
    data TEXT NOT NULL, -- JSON data of the FHIR resource
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- FHIR endpoints configuration
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
-- LOGGING TABLE
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
    exception TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =================================================================
-- ESSENTIAL INDEXES FOR PERFORMANCE
-- =================================================================

-- Core table indexes
CREATE INDEX IF NOT EXISTS idx_config_name ON config(name);
CREATE INDEX IF NOT EXISTS idx_config_service ON config(service);
CREATE INDEX IF NOT EXISTS idx_site_sitename ON site(sitename);
CREATE INDEX IF NOT EXISTS idx_user_username ON user(username);

-- Service management indexes
CREATE INDEX IF NOT EXISTS idx_service_type ON service(service_type);
CREATE INDEX IF NOT EXISTS idx_service_id ON service(service_id);
CREATE INDEX IF NOT EXISTS idx_service_status ON service(status);

-- DICOM table indexes
CREATE INDEX IF NOT EXISTS idx_study_uid ON study(study_uid);
CREATE INDEX IF NOT EXISTS idx_study_patient_id ON study(patient_id);
CREATE INDEX IF NOT EXISTS idx_series_uid ON series(series_uid);
CREATE INDEX IF NOT EXISTS idx_series_study_id ON series(study_id);
CREATE INDEX IF NOT EXISTS idx_image_sop_uid ON image(sop_instance_uid);
CREATE INDEX IF NOT EXISTS idx_image_series_id ON image(series_id);

-- HL7 message indexes
CREATE INDEX IF NOT EXISTS idx_hl7_message_processing_id ON hl7_message(processing_id);
CREATE INDEX IF NOT EXISTS idx_hl7_processing_status_processing_id ON hl7_processing_status(processing_id);

-- FHIR resource indexes
CREATE INDEX IF NOT EXISTS idx_fhir_resource_type_id ON fhir_resource(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_fhir_endpoint_endpoint_id ON fhir_endpoint(endpoint_id);

-- Log table indexes
CREATE INDEX IF NOT EXISTS idx_log_timestamp ON log(timestamp);
CREATE INDEX IF NOT EXISTS idx_log_level ON log(level);

-- =================================================================
-- VIEWS FOR BACKWARD COMPATIBILITY (PLURAL ALIASES)
-- =================================================================

-- Core table plural views
CREATE VIEW IF NOT EXISTS configs AS SELECT * FROM config;
CREATE VIEW IF NOT EXISTS sites AS SELECT * FROM site;
CREATE VIEW IF NOT EXISTS users AS SELECT * FROM user;
CREATE VIEW IF NOT EXISTS devices AS SELECT * FROM device;
CREATE VIEW IF NOT EXISTS services AS SELECT * FROM service;

-- DICOM plural views
CREATE VIEW IF NOT EXISTS studies AS SELECT * FROM study;
CREATE VIEW IF NOT EXISTS images AS SELECT * FROM image;
CREATE VIEW IF NOT EXISTS dicom_files AS SELECT * FROM dicom_file;

-- HL7 plural views
CREATE VIEW IF NOT EXISTS hl7_messages AS SELECT * FROM hl7_message;
CREATE VIEW IF NOT EXISTS hl7_orders AS SELECT * FROM hl7_order;
CREATE VIEW IF NOT EXISTS hl7_workflows AS SELECT * FROM hl7_workflow;

-- FHIR plural views
CREATE VIEW IF NOT EXISTS fhir_resources AS SELECT * FROM fhir_resource;
CREATE VIEW IF NOT EXISTS fhir_endpoints AS SELECT * FROM fhir_endpoint;

-- Log plural view
CREATE VIEW IF NOT EXISTS logs AS SELECT * FROM log;

-- Additional aliases for backward compatibility
CREATE VIEW IF NOT EXISTS client AS SELECT * FROM device;
CREATE VIEW IF NOT EXISTS clients AS SELECT * FROM device;

-- =================================================================
-- DEFAULT DATA INSERTION
-- =================================================================

-- Insert default configurations
INSERT OR IGNORE INTO config (name, value, description, service, value_type) VALUES
    ('database_version', '2.0.0', 'Unified database schema version', 'system', 'string'),
    ('system_initialized', 'true', 'Whether system has been initialized', 'system', 'boolean'),
    ('auto_start_services', 'true', 'Whether to auto-start core services', 'system', 'boolean');

-- Insert default site
INSERT OR IGNORE INTO site (sitename, status) VALUES 
    ('default', 'active');

-- Insert default FHIR endpoint
INSERT OR IGNORE INTO fhir_endpoint (endpoint_id, base_url, auth_type, auth_config, enabled) 
VALUES ('default', 'http://localhost:8080/fhir', 'none', '{}', 1);
