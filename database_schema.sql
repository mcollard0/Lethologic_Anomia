-- Complete Database Schema for Healthcare Message Storage
-- This schema includes all tables needed for HL7 and FHIR message storage and processing

-- =================================================================
-- HL7 MESSAGE STORAGE TABLES
-- =================================================================

-- Full HL7 messages storage (from HL7 processor)
CREATE TABLE IF NOT EXISTS hl7_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processing_id VARCHAR(100) UNIQUE NOT NULL,
    message_type VARCHAR(10) NOT NULL,
    message_text TEXT NOT NULL,
    source_address VARCHAR(100) NOT NULL,
    received_at DATETIME NOT NULL,
    processed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ADT message parsed data (from HL7 listener)
CREATE TABLE IF NOT EXISTS hl7_adt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id VARCHAR(100) NOT NULL,
    name VARCHAR(200),
    dob VARCHAR(20),
    sex VARCHAR(1),
    received_at DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ORM order message parsed data (from HL7 listener)
CREATE TABLE IF NOT EXISTS hl7_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_number VARCHAR(100),
    order_control VARCHAR(10),
    procedure_code VARCHAR(100),
    received_at DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- HL7 message processing status tracking (from HL7 processor)
CREATE TABLE IF NOT EXISTS hl7_processing_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processing_id VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL, -- pending, processing, processed, failed, retrying
    message TEXT,
    updated_at DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- HL7 workflow configuration (from HL7 processor)
CREATE TABLE IF NOT EXISTS hl7_workflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id VARCHAR(100) UNIQUE NOT NULL,
    message_type VARCHAR(10) NOT NULL,
    steps TEXT NOT NULL, -- JSON array of workflow steps
    retry_count INTEGER DEFAULT 3,
    retry_delay_seconds INTEGER DEFAULT 60,
    enabled BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- =================================================================
-- FHIR RESOURCE STORAGE TABLES
-- =================================================================

-- FHIR resources storage (from FHIR interface)
CREATE TABLE IF NOT EXISTS fhir_resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_type VARCHAR(50) NOT NULL,
    resource_id VARCHAR(100),
    version_id VARCHAR(50),
    data TEXT NOT NULL, -- JSON data of the FHIR resource
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

-- FHIR endpoints configuration (from FHIR interface)
CREATE TABLE IF NOT EXISTS fhir_endpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint_id VARCHAR(100) UNIQUE NOT NULL,
    base_url VARCHAR(500) NOT NULL,
    auth_type VARCHAR(20) NOT NULL, -- none, bearer, basic, oauth2
    auth_config TEXT, -- JSON configuration for authentication
    timeout_seconds INTEGER DEFAULT 30,
    enabled BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- =================================================================
-- INDEXES FOR PERFORMANCE
-- =================================================================

-- HL7 message indexes
CREATE INDEX IF NOT EXISTS idx_hl7_messages_processing_id ON hl7_messages(processing_id);
CREATE INDEX IF NOT EXISTS idx_hl7_messages_message_type ON hl7_messages(message_type);
CREATE INDEX IF NOT EXISTS idx_hl7_messages_received_at ON hl7_messages(received_at);

-- HL7 ADT indexes  
CREATE INDEX IF NOT EXISTS idx_hl7_adt_patient_id ON hl7_adt(patient_id);
CREATE INDEX IF NOT EXISTS idx_hl7_adt_received_at ON hl7_adt(received_at);

-- HL7 orders indexes
CREATE INDEX IF NOT EXISTS idx_hl7_orders_order_number ON hl7_orders(order_number);
CREATE INDEX IF NOT EXISTS idx_hl7_orders_received_at ON hl7_orders(received_at);

-- HL7 processing status indexes
CREATE INDEX IF NOT EXISTS idx_hl7_processing_status_processing_id ON hl7_processing_status(processing_id);
CREATE INDEX IF NOT EXISTS idx_hl7_processing_status_status ON hl7_processing_status(status);
CREATE INDEX IF NOT EXISTS idx_hl7_processing_status_updated_at ON hl7_processing_status(updated_at);

-- FHIR resource indexes
CREATE INDEX IF NOT EXISTS idx_fhir_resources_type_id ON fhir_resources(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_fhir_resources_created_at ON fhir_resources(created_at);
CREATE INDEX IF NOT EXISTS idx_fhir_resources_updated_at ON fhir_resources(updated_at);

-- FHIR endpoint indexes
CREATE INDEX IF NOT EXISTS idx_fhir_endpoints_endpoint_id ON fhir_endpoints(endpoint_id);
CREATE INDEX IF NOT EXISTS idx_fhir_endpoints_enabled ON fhir_endpoints(enabled);

-- =================================================================
-- SAMPLE DATA INSERTION (OPTIONAL)
-- =================================================================

-- Insert default FHIR endpoint if it doesn't exist
INSERT OR IGNORE INTO fhir_endpoints (endpoint_id, base_url, auth_type, auth_config, enabled) 
VALUES ('default', 'http://localhost:8080/fhir', 'none', '{}', 1);

-- Insert default HL7 workflows if they don't exist
INSERT OR IGNORE INTO hl7_workflows (workflow_id, message_type, steps, retry_count, retry_delay_seconds, enabled)
VALUES 
    ('ADT_default', 'ADT', '["validate", "store", "fhir_convert"]', 3, 60, 1),
    ('ORM_default', 'ORM', '["validate", "store", "fhir_convert"]', 3, 60, 1),
    ('ORU_default', 'ORU', '["validate", "store", "fhir_convert"]', 3, 60, 1),
    ('ACK_simple', 'ACK', '["validate", "store"]', 1, 30, 1);

-- =================================================================
-- NOTES ON USAGE
-- =================================================================

/*
This schema provides comprehensive storage for inbound HL7 and FHIR messages:

1. HL7 MESSAGE FLOW:
   - Raw HL7 messages are received by the HL7 listener
   - Parsed field data from ADT messages goes to 'hl7_adt' table
   - Parsed field data from ORM messages goes to 'hl7_orders' table
   - Full message text and metadata goes to 'hl7_messages' table via HL7 processor
   - Processing status is tracked in 'hl7_processing_status' table
   - Workflow configurations are stored in 'hl7_workflows' table

2. FHIR RESOURCE FLOW:
   - FHIR resources (converted from HL7 or directly received) go to 'fhir_resources' table
   - FHIR endpoint configurations are stored in 'fhir_endpoints' table
   - Full JSON representation of FHIR resources is stored in the 'data' field

3. STORAGE CONFIRMATION:
   Yes, the services DO store inbound message data:
   - HL7 listener stores parsed ADT/ORM data in specialized tables
   - HL7 processor stores full message text in hl7_messages table
   - FHIR interface stores converted resources in fhir_resources table
   
4. RETRIEVAL:
   - Messages can be retrieved by processing_id, message_type, date ranges
   - FHIR resources can be retrieved by resource_type, resource_id
   - Full audit trail is maintained with timestamps
*/
