# Inbound Message Storage Architecture

## Executive Summary

**YES, the HL7 and FHIR services DO store inbound messages to the database.**

This document provides a comprehensive overview of how inbound HL7 and FHIR messages are stored and managed within the healthcare data migration system.

## Storage Architecture Overview

The system uses a multi-layered approach to store inbound healthcare messages:

1. **Raw Message Storage**: Full message text preservation
2. **Parsed Data Storage**: Extracted and structured data elements
3. **Processing Status Tracking**: Workflow and status management
4. **FHIR Resource Storage**: Converted and standardized healthcare resources

---

## HL7 Message Storage

### 1. Raw HL7 Message Storage (`hl7_messages` table)

**Location**: `services/hl7/processor.py` → `_store_message()` method  
**Database Table**: `hl7_messages`

```sql
CREATE TABLE hl7_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processing_id VARCHAR(100) UNIQUE NOT NULL,
    message_type VARCHAR(10) NOT NULL,
    message_text TEXT NOT NULL,           -- FULL HL7 MESSAGE TEXT
    source_address VARCHAR(100) NOT NULL,
    received_at DATETIME NOT NULL,
    processed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**What gets stored:**
- Complete HL7 message text (MSH, PID, ORC, OBR, OBX segments, etc.)
- Processing metadata (ID, type, source, timestamps)
- Processing workflow status

### 2. Parsed ADT Data Storage (`hl7_adt` table)

**Location**: `services/hl7/listener.py` → `_handle_adt_message()` method  
**Database Table**: `hl7_adt`

```sql
CREATE TABLE hl7_adt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id VARCHAR(100) NOT NULL,    -- From PID.3
    name VARCHAR(200),                   -- From PID.5
    dob VARCHAR(20),                     -- From PID.7
    sex VARCHAR(1),                      -- From PID.8
    received_at DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**What gets stored:**
- Extracted patient demographics from ADT messages
- Structured patient information for quick lookup

### 3. Parsed Order Data Storage (`hl7_orders` table)

**Location**: `services/hl7/listener.py` → `_handle_orm_message()` method  
**Database Table**: `hl7_orders`

```sql
CREATE TABLE hl7_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_number VARCHAR(100),           -- From ORC.2
    order_control VARCHAR(10),           -- From ORC.1
    procedure_code VARCHAR(100),         -- From OBR.4
    received_at DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**What gets stored:**
- Extracted order information from ORM messages
- Order control codes and procedure information

### 4. Processing Status Tracking (`hl7_processing_status` table)

**Location**: `services/hl7/processor.py` → `_update_processing_status()` method  
**Database Table**: `hl7_processing_status`

```sql
CREATE TABLE hl7_processing_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processing_id VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,         -- pending, processing, processed, failed, retrying
    message TEXT,
    updated_at DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**What gets stored:**
- Real-time processing status updates
- Error messages and workflow progression
- Audit trail for message processing

---

## FHIR Resource Storage

### 1. FHIR Resource Storage (`fhir_resources` table)

**Location**: `services/hl7/fhir_interface.py` → `_store_fhir_resource()` method  
**Database Table**: `fhir_resources`

```sql
CREATE TABLE fhir_resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_type VARCHAR(50) NOT NULL,  -- Patient, Observation, ServiceRequest, etc.
    resource_id VARCHAR(100),
    version_id VARCHAR(50),
    data TEXT NOT NULL,                  -- FULL FHIR RESOURCE JSON
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
```

**What gets stored:**
- Complete FHIR resources in JSON format
- Converted HL7 messages as FHIR resources
- Resource metadata and versioning information

### 2. FHIR Endpoint Configuration (`fhir_endpoints` table)

**Location**: `services/hl7/fhir_interface.py` → `_load_fhir_endpoints()` method  
**Database Table**: `fhir_endpoints`

```sql
CREATE TABLE fhir_endpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint_id VARCHAR(100) UNIQUE NOT NULL,
    base_url VARCHAR(500) NOT NULL,
    auth_type VARCHAR(20) NOT NULL,
    auth_config TEXT,
    timeout_seconds INTEGER DEFAULT 30,
    enabled BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**What gets stored:**
- FHIR server connection configurations
- Authentication settings for external FHIR servers

---

## Message Processing Flow

### Inbound HL7 Message Journey:

1. **Reception**: HL7 Listener receives TCP message
   ```
   services/hl7/listener.py → handle_connection()
   ```

2. **Parsing & Initial Storage**: Message type-specific processing
   ```
   ADT Messages → hl7_adt table (parsed patient data)
   ORM Messages → hl7_orders table (parsed order data)
   ```

3. **Full Message Storage**: Complete message preservation
   ```
   services/hl7/processor.py → _store_message() → hl7_messages table
   ```

4. **Status Tracking**: Processing workflow updates
   ```
   services/hl7/processor.py → _update_processing_status() → hl7_processing_status table
   ```

5. **FHIR Conversion**: Standards-based resource creation
   ```
   services/hl7/fhir_interface.py → convert_hl7_to_fhir() → fhir_resources table
   ```

### Data Persistence Guarantee:

- **HL7 Raw Messages**: ✅ Stored in `hl7_messages` table
- **HL7 Parsed Data**: ✅ Stored in `hl7_adt` and `hl7_orders` tables
- **FHIR Resources**: ✅ Stored in `fhir_resources` table
- **Processing Status**: ✅ Tracked in `hl7_processing_status` table
- **Audit Trail**: ✅ Complete timestamps and processing history

---

## Code References

### HL7 Listener Storage Operations:
```python
# File: services/hl7/listener.py
# Lines: 357-358 (ADT storage)
await self.db_manager.execute_query(
    "INSERT OR REPLACE INTO hl7_adt (patient_id, name, dob, sex, received_at) VALUES (?, ?, ?, ?, ?)",
    [patient_id, patient_name, dob, sex, datetime.now().isoformat()]
)

# Lines: 405-407 (ORM storage)  
await self.db_manager.execute_query(
    "INSERT INTO hl7_orders (order_number, order_control, procedure_code, received_at) VALUES (?, ?, ?, ?)",
    [order_number, order_control, procedure_code, datetime.now().isoformat()]
)
```

### HL7 Processor Storage Operations:
```python
# File: services/hl7/processor.py
# Lines: 560-574 (Full message storage)
await self.db_manager.execute_query(
    """
    INSERT INTO hl7_messages 
    (processing_id, message_type, message_text, source_address, received_at, processed_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """,
    [message_data['processing_id'], message_type, message_text, 
     message_data['source_address'], message_data['queued_at'].isoformat(), 
     datetime.now().isoformat()]
)

# Lines: 751-757 (Status tracking)
await self.db_manager.execute_query(
    """
    INSERT OR REPLACE INTO hl7_processing_status 
    (processing_id, status, message, updated_at)
    VALUES (?, ?, ?, ?)
    """,
    [processing_id, status.value, message, datetime.now().isoformat()]
)
```

### FHIR Interface Storage Operations:
```python
# File: services/hl7/fhir_interface.py
# Lines: 79+ (FHIR resource storage)
await self.db_manager.execute_query(
    """
    INSERT OR REPLACE INTO fhir_resources 
    (resource_type, resource_id, version_id, data, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """,
    [resource.resource_type, resource.resource_id, resource.version_id,
     json.dumps(resource.data), resource.created_at.isoformat(),
     resource.updated_at.isoformat()]
)
```

---

## Database Schema Files

- **Complete Schema**: `database_schema.sql` (includes all HL7 and FHIR tables)
- **Extended Database Manager**: `core/extended_database.py` (ORM models and helper methods)
- **Base Database Manager**: `core/database.py` (core DICOM tables only)

---

## Message Retrieval Capabilities

The system provides comprehensive retrieval methods:

### HL7 Messages:
```python
# Get messages by type, date range, limit
messages = await db.get_hl7_messages(message_type="ADT", limit=100)

# Get processing status
status = await db.get_processing_status(processing_id="hl7_20241201_120000_1")
```

### FHIR Resources:
```python
# Get FHIR resources by type
patients = await db.get_fhir_resources(resource_type="Patient", limit=50)

# Get all resources
all_resources = await db.get_fhir_resources()
```

### Statistics:
```python
# Get comprehensive message statistics
stats = await db.get_message_statistics()
# Returns: {'hl7': {'total_messages': 1250, 'adt_records': 890, ...}, 'fhir': {...}}
```

---

## Conclusion

**The healthcare data migration system comprehensively stores ALL inbound messages:**

1. ✅ **Raw HL7 messages** are preserved in full text format
2. ✅ **Parsed message components** are stored in structured tables
3. ✅ **FHIR resources** are stored as converted, standardized data
4. ✅ **Processing workflows** are tracked with full audit trails
5. ✅ **Message retrieval** is supported with flexible query capabilities

The multi-layered storage approach ensures no data loss while providing both raw message preservation and structured data access for healthcare workflows.
