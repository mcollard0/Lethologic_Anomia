"""
Extended Database Manager with HL7 and FHIR Support

Extends the core database manager with specific table models for HL7 and FHIR message storage.
This includes all the tables referenced in the HL7 listener, processor, and FHIR interface service.
"""

import json
from datetime import datetime
from typing import Dict, Any, Optional, List

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, DatabaseManager
from .custom_logging import get_logger

logger = get_logger(__name__)


# ===================================================================
# HL7 MESSAGE STORAGE MODELS
# ===================================================================

class HL7Message(Base):
    """Full HL7 messages storage - from HL7 processor _store_message method"""
    __tablename__ = 'hl7_message'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    processing_id: Mapped[str] = mapped_column(String(100), unique=True)
    message_type: Mapped[str] = mapped_column(String(10))
    message_text: Mapped[str] = mapped_column(Text)
    source_address: Mapped[str] = mapped_column(String(100))
    received_at: Mapped[datetime] = mapped_column(DateTime)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class HL7ADT(Base):
    """ADT message parsed data - from HL7 listener _handle_adt_message method"""
    __tablename__ = 'hl7_adt'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[str] = mapped_column(String(100))
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    dob: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    sex: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class HL7Order(Base):
    """ORM order message parsed data - from HL7 listener _handle_orm_message method"""
    __tablename__ = 'hl7_order'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    order_control: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    procedure_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class HL7ProcessingStatus(Base):
    """HL7 message processing status tracking - from HL7 processor _update_processing_status method"""
    __tablename__ = 'hl7_processing_status'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    processing_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))  # pending, processing, processed, failed, retrying
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class HL7Workflow(Base):
    """HL7 workflow configuration - from HL7 processor _load_workflows_from_db method"""
    __tablename__ = 'hl7_workflow'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(100), unique=True)
    message_type: Mapped[str] = mapped_column(String(10))
    steps: Mapped[str] = mapped_column(Text)  # JSON array of workflow steps
    retry_count: Mapped[int] = mapped_column(Integer, default=3)
    retry_delay_seconds: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


# ===================================================================
# FHIR RESOURCE STORAGE MODELS
# ===================================================================

class FHIRResource(Base):
    """FHIR resources storage - from FHIR interface _store_fhir_resource method"""
    __tablename__ = 'fhir_resource'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    version_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    data: Mapped[str] = mapped_column(Text)  # JSON data of the FHIR resource
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class FHIREndpoint(Base):
    """FHIR endpoints configuration - from FHIR interface _load_fhir_endpoints method"""
    __tablename__ = 'fhir_endpoint'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint_id: Mapped[str] = mapped_column(String(100), unique=True)
    base_url: Mapped[str] = mapped_column(String(500))
    auth_type: Mapped[str] = mapped_column(String(20))  # none, bearer, basic, oauth2
    auth_config: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON configuration for authentication
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


# ===================================================================
# EXTENDED DATABASE MANAGER
# ===================================================================

class ExtendedDatabaseManager(DatabaseManager):
    """
    Extended Database Manager with HL7 and FHIR support
    
    Provides all the functionality of the base DatabaseManager plus
    specific methods for HL7 and FHIR message storage and retrieval.
    """
    
    async def initialize_extended_tables(self) -> None:
        """Initialize the extended HL7 and FHIR tables"""
        try:
            # The tables will be created automatically when Base.metadata.create_all() is called
            # in the parent class initialization
            logger.info("Extended HL7 and FHIR tables ready")
            
            # Insert default data if needed
            await self._insert_default_data()
            
        except Exception as e:
            logger.error(f"Failed to initialize extended tables: {e}")
            raise

    async def _insert_default_data(self) -> None:
        """Insert default configuration data"""
        try:
            # Insert default FHIR endpoint
            await self.execute_query(
                """INSERT OR IGNORE INTO fhir_endpoint 
                   (endpoint_id, base_url, auth_type, auth_config, enabled) 
                   VALUES (?, ?, ?, ?, ?)""",
                ['default', 'http://localhost:8080/fhir', 'none', '{}', True]
            )
            
            # Insert default HL7 workflows
            default_workflows = [
                ('ADT_default', 'ADT', '["validate", "store", "fhir_convert"]', 3, 60),
                ('ORM_default', 'ORM', '["validate", "store", "fhir_convert"]', 3, 60),
                ('ORU_default', 'ORU', '["validate", "store", "fhir_convert"]', 3, 60),
                ('ACK_simple', 'ACK', '["validate", "store"]', 1, 30),
            ]
            
            for workflow_id, message_type, steps, retry_count, retry_delay in default_workflows:
                await self.execute_query(
                    """INSERT OR IGNORE INTO hl7_workflow 
                       (workflow_id, message_type, steps, retry_count, retry_delay_seconds, enabled)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [workflow_id, message_type, steps, retry_count, retry_delay, True]
                )
                
            logger.info("Default HL7 and FHIR configuration data inserted")
            
        except Exception as e:
            logger.warning(f"Failed to insert default data: {e}")

    # ===================================================================
    # HL7 MESSAGE STORAGE METHODS
    # ===================================================================
    
    async def store_hl7_message(self, processing_id: str, message_type: str, 
                               message_text: str, source_address: str, 
                               received_at: datetime, processed_at: Optional[datetime] = None) -> bool:
        """
        Store a full HL7 message (used by HL7 processor)
        
        Args:
            processing_id: Unique processing identifier
            message_type: HL7 message type (ADT, ORM, etc.)
            message_text: Full HL7 message text
            source_address: Source address of the message
            received_at: When the message was received
            processed_at: When the message was processed (optional)
            
        Returns:
            True if stored successfully
        """
        try:
            await self.execute_query(
                """INSERT INTO hl7_messages 
                   (processing_id, message_type, message_text, source_address, received_at, processed_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [processing_id, message_type, message_text, source_address, 
                 received_at.isoformat(), processed_at.isoformat() if processed_at else None]
            )
            return True
        except Exception as e:
            logger.error(f"Failed to store HL7 message: {e}")
            return False

    async def store_hl7_adt_data(self, patient_id: str, name: str, dob: str, 
                                sex: str, received_at: datetime) -> bool:
        """
        Store parsed ADT message data (used by HL7 listener)
        
        Args:
            patient_id: Patient identifier
            name: Patient name
            dob: Date of birth
            sex: Patient sex
            received_at: When the message was received
            
        Returns:
            True if stored successfully
        """
        try:
            await self.execute_query(
                """INSERT OR REPLACE INTO hl7_adt 
                   (patient_id, name, dob, sex, received_at) 
                   VALUES (?, ?, ?, ?, ?)""",
                [patient_id, name, dob, sex, received_at.isoformat()]
            )
            return True
        except Exception as e:
            logger.error(f"Failed to store HL7 ADT data: {e}")
            return False

    async def store_hl7_order_data(self, order_number: str, order_control: str,
                                  procedure_code: str, received_at: datetime) -> bool:
        """
        Store parsed ORM message data (used by HL7 listener)
        
        Args:
            order_number: Order number
            order_control: Order control code
            procedure_code: Procedure code
            received_at: When the message was received
            
        Returns:
            True if stored successfully
        """
        try:
            await self.execute_query(
                """INSERT INTO hl7_orders 
                   (order_number, order_control, procedure_code, received_at) 
                   VALUES (?, ?, ?, ?)""",
                [order_number, order_control, procedure_code, received_at.isoformat()]
            )
            return True
        except Exception as e:
            logger.error(f"Failed to store HL7 order data: {e}")
            return False

    async def update_hl7_processing_status(self, processing_id: str, status: str, 
                                         message: str) -> bool:
        """
        Update HL7 message processing status (used by HL7 processor)
        
        Args:
            processing_id: Processing identifier
            status: Processing status
            message: Status message
            
        Returns:
            True if updated successfully
        """
        try:
            await self.execute_query(
                """INSERT OR REPLACE INTO hl7_processing_status 
                   (processing_id, status, message, updated_at) 
                   VALUES (?, ?, ?, ?)""",
                [processing_id, status, message, datetime.now().isoformat()]
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update HL7 processing status: {e}")
            return False

    # ===================================================================
    # FHIR RESOURCE STORAGE METHODS
    # ===================================================================

    async def store_fhir_resource(self, resource_type: str, resource_id: Optional[str],
                                 version_id: Optional[str], data: Dict[str, Any],
                                 created_at: datetime, updated_at: datetime) -> bool:
        """
        Store a FHIR resource (used by FHIR interface)
        
        Args:
            resource_type: FHIR resource type
            resource_id: Resource identifier
            version_id: Resource version identifier
            data: FHIR resource data
            created_at: Creation timestamp
            updated_at: Update timestamp
            
        Returns:
            True if stored successfully
        """
        try:
            await self.execute_query(
                """INSERT OR REPLACE INTO fhir_resources 
                   (resource_type, resource_id, version_id, data, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [resource_type, resource_id, version_id, json.dumps(data),
                 created_at.isoformat(), updated_at.isoformat()]
            )
            return True
        except Exception as e:
            logger.error(f"Failed to store FHIR resource: {e}")
            return False

    # ===================================================================
    # RETRIEVAL METHODS
    # ===================================================================

    async def get_hl7_messages(self, message_type: Optional[str] = None,
                              start_date: Optional[datetime] = None,
                              end_date: Optional[datetime] = None,
                              limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieve HL7 messages with optional filtering
        
        Args:
            message_type: Filter by message type
            start_date: Filter by start date
            end_date: Filter by end date
            limit: Maximum number of results
            
        Returns:
            List of HL7 messages
        """
        query = "SELECT * FROM hl7_messages WHERE 1=1"
        params = []
        
        if message_type:
            query += " AND message_type = ?"
            params.append(message_type)
            
        if start_date:
            query += " AND received_at >= ?"
            params.append(start_date.isoformat())
            
        if end_date:
            query += " AND received_at <= ?"
            params.append(end_date.isoformat())
            
        query += " ORDER BY received_at DESC"
        
        if limit:
            query += f" LIMIT {limit}"
        
        try:
            result = await self.execute_query(query, params)
            return result
        except Exception as e:
            logger.error(f"Failed to retrieve HL7 messages: {e}")
            return []

    async def get_fhir_resources(self, resource_type: Optional[str] = None,
                               limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieve FHIR resources with optional filtering
        
        Args:
            resource_type: Filter by resource type
            limit: Maximum number of results
            
        Returns:
            List of FHIR resources
        """
        query = "SELECT * FROM fhir_resources WHERE 1=1"
        params = []
        
        if resource_type:
            query += " AND resource_type = ?"
            params.append(resource_type)
            
        query += " ORDER BY created_at DESC"
        
        if limit:
            query += f" LIMIT {limit}"
        
        try:
            result = await self.execute_query(query, params)
            # Parse JSON data field
            for row in result:
                if row.get('data'):
                    row['data'] = json.loads(row['data'])
            return result
        except Exception as e:
            logger.error(f"Failed to retrieve FHIR resources: {e}")
            return []

    async def get_message_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about stored messages
        
        Returns:
            Dictionary containing message statistics
        """
        try:
            # HL7 message counts
            hl7_total = await self.execute_query("SELECT COUNT(*) as count FROM hl7_messages")
            hl7_adt_count = await self.execute_query("SELECT COUNT(*) as count FROM hl7_adt")
            hl7_orders_count = await self.execute_query("SELECT COUNT(*) as count FROM hl7_orders")
            
            # FHIR resource counts
            fhir_total = await self.execute_query("SELECT COUNT(*) as count FROM fhir_resources")
            
            # Message type breakdown
            hl7_by_type = await self.execute_query(
                "SELECT message_type, COUNT(*) as count FROM hl7_messages GROUP BY message_type"
            )
            
            fhir_by_type = await self.execute_query(
                "SELECT resource_type, COUNT(*) as count FROM fhir_resources GROUP BY resource_type"
            )
            
            return {
                'hl7': {
                    'total_messages': hl7_total[0]['count'] if hl7_total else 0,
                    'adt_records': hl7_adt_count[0]['count'] if hl7_adt_count else 0,
                    'order_records': hl7_orders_count[0]['count'] if hl7_orders_count else 0,
                    'by_type': {row['message_type']: row['count'] for row in hl7_by_type}
                },
                'fhir': {
                    'total_resources': fhir_total[0]['count'] if fhir_total else 0,
                    'by_type': {row['resource_type']: row['count'] for row in fhir_by_type}
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to get message statistics: {e}")
            return {'hl7': {'total_messages': 0}, 'fhir': {'total_resources': 0}}


__all__ = [
    'ExtendedDatabaseManager',
    'HL7Message',
    'HL7ADT',
    'HL7Order', 
    'HL7ProcessingStatus',
    'HL7Workflow',
    'FHIRResource',
    'FHIREndpoint'
]
