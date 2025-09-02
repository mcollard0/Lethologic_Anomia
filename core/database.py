"""
Database Manager for the Migration Service

Provides multi-database support with SQL translation between different database engines.
Supports SQLite, PostgreSQL, MySQL/MariaDB, Oracle, and MongoDB.

Equivalent to the C++ mdb namespace functionality with enhanced features.
"""

import asyncio
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.sql import text
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects import sqlite, postgresql, mysql, oracle

# MongoDB support
try:
    from motor.motor_asyncio import AsyncIOMotorClient
    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False

from .custom_logging import get_logger
import hashlib
from datetime import datetime

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy ORM models"""
    pass


class LogEntry(Base):
    """Log entries table - equivalent to C++ LOG table"""
    __tablename__ = 'log'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    level: Mapped[str] = mapped_column(String(20))
    module: Mapped[str] = mapped_column(String(100))
    function: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    thread_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    process_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    exception: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ConfigEntry(Base):
    """Configuration entries table - equivalent to C++ CONFIG table"""
    __tablename__ = 'config'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    service: Mapped[str] = mapped_column(String(64))  # Service name (e.g., dicom_scp, web_interface)
    name: Mapped[str] = mapped_column(String(255))  # Setting name (e.g., port, host)
    value: Mapped[str] = mapped_column(Text)  # Setting value
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    value_type: Mapped[str] = mapped_column(String(20), default='string')  # string, integer, boolean, json
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Composite unique constraint on service and name
    __table_args__ = (sa.UniqueConstraint('service', 'name'),)


class Site(Base):
    """Site table - normalized basic site information"""
    __tablename__ = 'site'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    sitename: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class Device(Base):
    """Device table - technical connection details"""
    __tablename__ = 'device'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey('site.id'))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    device_name: Mapped[str] = mapped_column(String(255))
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ae_title: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    device_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # DICOM_SCP, DICOM_SCU, HL7_LISTENER, etc.
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class Study(Base):
    """Study table - singular name, equivalent to C++ STUDIES table"""
    __tablename__ = 'study'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    study_uid: Mapped[str] = mapped_column(String(64), unique=True)
    study_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    study_time: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    study_description: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    patient_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    patient_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    patient_birth_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    patient_sex: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    modality: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    institution_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    study_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    site_id: Mapped[Optional[int]] = mapped_column(ForeignKey('site.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class Series(Base):
    """Series table - singular name, equivalent to C++ SERIES table"""
    __tablename__ = 'series'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    series_uid: Mapped[str] = mapped_column(String(64), unique=True)
    study_id: Mapped[int] = mapped_column(ForeignKey('study.id'))
    series_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    series_description: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    modality: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    body_part: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    series_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    series_time: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class Image(Base):
    """Image table - singular name, equivalent to C++ IMAGES table"""
    __tablename__ = 'image'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    sop_instance_uid: Mapped[str] = mapped_column(String(64), unique=True)
    series_id: Mapped[int] = mapped_column(ForeignKey('series.id'))
    instance_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    acquisition_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    acquisition_time: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    image_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    pixel_spacing: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    rows: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    columns: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class User(Base):
    """User table for authentication and access control"""
    __tablename__ = 'user'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password: Mapped[str] = mapped_column(String(128))  # SHA-512 hash
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class Service(Base):
    """Service table for managing system services configuration"""
    __tablename__ = 'service'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    service_name: Mapped[str] = mapped_column(String(64), unique=True)  # Web Server, FHIR Server, etc.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_start: Mapped[bool] = mapped_column(Boolean, default=True)
    singleton: Mapped[bool] = mapped_column(Boolean, default=True)  # Multiple instances allowed?
    ports: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Comma-separated ports
    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    settings_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON settings
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # running, stopped, error
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class DatabaseManager:
    """
    Multi-database manager with SQL translation capabilities
    
    Supports SQLite, PostgreSQL, MySQL/MariaDB, Oracle, and MongoDB.
    Provides automatic SQL translation between different database engines.
    """
    
    def __init__(self, database_url: str):
        """
        Initialize database manager
        
        Args:
            database_url: Database connection URL
        """
        self.database_url = database_url
        self.engine: Optional[AsyncEngine] = None
        self.session_factory: Optional[sessionmaker] = None
        self.mongodb_client: Optional[AsyncIOMotorClient] = None
        self.mongodb_db = None
        self.db_type = self._detect_database_type(database_url)
        
        # SQL translation mappings
        self.sql_translations = {
            'postgresql': {
                'AUTOINCREMENT': 'SERIAL',
                'TEXT': 'TEXT',
                'INTEGER': 'INTEGER',
                'DATETIME': 'TIMESTAMP',
                'CURRENT_TIMESTAMP': 'CURRENT_TIMESTAMP',
                'LIMIT': 'LIMIT',
                'INSERT OR REPLACE': 'INSERT ... ON CONFLICT DO UPDATE'
            },
            'mysql': {
                'AUTOINCREMENT': 'AUTO_INCREMENT',
                'TEXT': 'TEXT',
                'INTEGER': 'INT',
                'DATETIME': 'DATETIME',
                'CURRENT_TIMESTAMP': 'CURRENT_TIMESTAMP',
                'LIMIT': 'LIMIT',
                'INSERT OR REPLACE': 'REPLACE INTO'
            },
            'oracle': {
                'AUTOINCREMENT': '',  # Use IDENTITY or SEQUENCE
                'TEXT': 'CLOB',
                'INTEGER': 'NUMBER',
                'DATETIME': 'TIMESTAMP',
                'CURRENT_TIMESTAMP': 'CURRENT_TIMESTAMP',
                'LIMIT': 'ROWNUM <=',
                'INSERT OR REPLACE': 'MERGE'
            },
            'sqlite': {
                'AUTOINCREMENT': 'AUTOINCREMENT',
                'TEXT': 'TEXT',
                'INTEGER': 'INTEGER',
                'DATETIME': 'DATETIME',
                'CURRENT_TIMESTAMP': 'CURRENT_TIMESTAMP',
                'LIMIT': 'LIMIT',
                'INSERT OR REPLACE': 'INSERT OR REPLACE'
            }
        }
        
        logger.info(f"Initializing database manager for {self.db_type}")
    
    def _detect_database_type(self, url: str) -> str:
        """Detect database type from URL"""
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        
        # Handle simple filenames (no scheme)
        if not scheme:
            # Assume SQLite for simple filenames
            self.database_url = f"sqlite:///{url}"
            return 'sqlite'
        
        if scheme.startswith('sqlite'):
            return 'sqlite'
        elif scheme.startswith('postgresql') or scheme.startswith('postgres'):
            return 'postgresql'
        elif scheme.startswith('mysql') or scheme.startswith('mariadb'):
            return 'mysql'
        elif scheme.startswith('oracle'):
            return 'oracle'
        elif scheme.startswith('mongodb') or scheme.startswith('mongo'):
            return 'mongodb'
        else:
            logger.warning(f"Unknown database type: {scheme}, defaulting to sqlite")
            return 'sqlite'
    
    async def initialize(self) -> None:
        """Initialize database connection and create tables"""
        try:
            if self.db_type == 'mongodb':
                await self._initialize_mongodb()
            else:
                await self._initialize_sql()
            
            logger.info(f"Database manager initialized successfully for {self.db_type}")
            
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    async def _initialize_mongodb(self) -> None:
        """Initialize MongoDB connection"""
        if not MONGODB_AVAILABLE:
            raise RuntimeError("MongoDB support not available. Install motor: pip install motor")
        
        self.mongodb_client = AsyncIOMotorClient(self.database_url)
        # Extract database name from URL
        parsed = urlparse(self.database_url)
        db_name = parsed.path.lstrip('/') or 'migration_service'
        self.mongodb_db = self.mongodb_client[db_name]
        
        # Test connection
        await self.mongodb_client.admin.command('ping')
        
        # Create indexes
        await self._create_mongodb_indexes()
    
    async def _initialize_sql(self) -> None:
        """Initialize SQL database connection"""
        # Create async engine
        # Use aiosqlite driver for SQLite for async support
        if self.db_type == 'sqlite':
            database_url = self.database_url.replace('sqlite://', 'sqlite+aiosqlite://', 1)
        else:
            database_url = self.database_url

        self.engine = create_async_engine(
            database_url,
            echo=False,  # Set to True for SQL debugging
            pool_pre_ping=True,
            pool_recycle=3600
        )
        
        # Create session factory
        self.session_factory = sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # Create tables
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def _create_mongodb_indexes(self) -> None:
        """Create MongoDB indexes for performance"""
        # Log entries indexes
        await self.mongodb_db.log.create_index("timestamp")
        await self.mongodb_db.log.create_index("level")
        
        # Config indexes
        await self.mongodb_db.config.create_index("name", unique=True)
        
        # Studies indexes
        await self.mongodb_db.studies.create_index("study_uid", unique=True)
        await self.mongodb_db.studies.create_index("patient_id")
        await self.mongodb_db.studies.create_index("study_date")
        
        # Series indexes
        await self.mongodb_db.series.create_index("series_uid", unique=True)
        await self.mongodb_db.series.create_index("study_id")
        
        # Images indexes
        await self.mongodb_db.images.create_index("sop_instance_uid", unique=True)
        await self.mongodb_db.images.create_index("series_id")
    
    async def shutdown(self) -> None:
        """Shutdown database connections"""
        if self.engine:
            await self.engine.dispose()
        
        if self.mongodb_client:
            self.mongodb_client.close()
        
        logger.info("Database manager shutdown complete")
    
    async def log_message(
        self,
        level: str,
        module: str,
        function: str,
        message: str,
        timestamp: Optional[datetime] = None,
        thread_id: Optional[int] = None,
        process_id: Optional[int] = None,
        exception: Optional[str] = None
    ) -> None:
        """
        Log a message to the database
        
        Args:
            level: Log level
            module: Module name
            function: Function name
            message: Log message
            timestamp: Message timestamp
            thread_id: Thread ID
            process_id: Process ID
            exception: Exception details
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        try:
            if self.db_type == 'mongodb':
                await self._log_message_mongodb(
                    level, module, function, message, timestamp,
                    thread_id, process_id, exception
                )
            else:
                await self._log_message_sql(
                    level, module, function, message, timestamp,
                    thread_id, process_id, exception
                )
        except Exception as e:
            logger.error(f"Failed to log message to database: {e}")
    
    async def _log_message_sql(
        self,
        level: str,
        module: str,
        function: str,
        message: str,
        timestamp: datetime,
        thread_id: Optional[int],
        process_id: Optional[int],
        exception: Optional[str]
    ) -> None:
        """Log message to SQL database"""
        async with self.session_factory() as session:
            log_entry = LogEntry(
                timestamp=timestamp,
                level=level,
                module=module,
                function=function,
                message=message,
                thread_id=thread_id,
                process_id=process_id,
                exception=exception
            )
            session.add(log_entry)
            await session.commit()
    
    async def _log_message_mongodb(
        self,
        level: str,
        module: str,
        function: str,
        message: str,
        timestamp: datetime,
        thread_id: Optional[int],
        process_id: Optional[int],
        exception: Optional[str]
    ) -> None:
        """Log message to MongoDB"""
        document = {
            'timestamp': timestamp,
            'level': level,
            'module': module,
            'function': function,
            'message': message,
            'thread_id': thread_id,
            'process_id': process_id,
            'exception': exception
        }
        await self.mongodb_db.log.insert_one(document)
    
    async def get_config(self, name: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get configuration value
        
        Args:
            name: Configuration name
            default: Default value if not found
            
        Returns:
            Configuration value or default
        """
        try:
            result = await self.execute_query(
                "SELECT value FROM config WHERE name = ?", (name,)
            )
            if result and result[0].get('value'):
                return result[0]['value']
            return default
        except Exception as e:
            logger.error(f"Error getting config {name}: {e}")
            return default
    
    async def set_config(self, name: str, value: str) -> None:
        """
        Set configuration value
        
        Args:
            name: Configuration name
            value: Configuration value
        """
        try:
            await self.execute_query(
                "INSERT OR REPLACE INTO config (name, value) VALUES (?, ?)",
                (name, value)
            )
        except Exception as e:
            logger.error(f"Error setting config {name}: {e}")
            raise
    
    async def execute_query(
        self, 
        query: str, 
        params: Optional[Tuple] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a SQL query and return results
        
        Args:
            query: SQL query to execute
            params: Query parameters
            
        Returns:
            List of result dictionaries
        """
        try:
            if self.db_type == 'mongodb':
                # For MongoDB, this would need to be translated to MongoDB queries
                # For now, return empty list as most config operations use SQL-style queries
                return []
            
            async with self.session_factory() as session:
                # Handle both tuple and dict parameters
                if params is None:
                    result = await session.execute(text(query))
                elif isinstance(params, tuple):
                    # Convert tuple to dictionary with numbered keys
                    param_dict = {f'param{i+1}': param for i, param in enumerate(params)}
                    # Replace ? with :param1, :param2, etc.
                    formatted_query = query
                    for i in range(len(params)):
                        formatted_query = formatted_query.replace('?', f':param{i+1}', 1)
                    result = await session.execute(text(formatted_query), param_dict)
                else:
                    result = await session.execute(text(query), params)
                    
                if result.returns_rows:
                    rows = result.fetchall()
                    return [dict(row._mapping) for row in rows]
                else:
                    await session.commit()
                    return []
                    
        except Exception as e:
            logger.error(f"Error executing query: {e}")
            raise
    
    def _hash_password(self, password: str) -> str:
        """Hash password using SHA-512"""
        return hashlib.sha512(password.encode('utf-8')).hexdigest()
    
    async def check_user(self, username: str, password: str) -> bool:
        """
        Check user credentials for authentication
        
        Args:
            username: Username to check
            password: Plain text password to verify
            
        Returns:
            True if credentials are valid and user is enabled, False otherwise
        """
        try:
            password_hash = self._hash_password(password)
            
            result = await self.execute_query(
                "SELECT id, enabled, deleted FROM user WHERE username = ? AND password = ?",
                (username, password_hash)
            )
            
            if not result:
                logger.warning(f"Authentication failed for user: {username} (invalid credentials)")
                return False
            
            user = result[0]
            if user.get('deleted', False):
                logger.warning(f"Authentication failed for user: {username} (user deleted)")
                return False
                
            if not user.get('enabled', False):
                logger.warning(f"Authentication failed for user: {username} (user disabled)")
                return False
            
            logger.info(f"Authentication successful for user: {username}")
            return True
            
        except Exception as e:
            logger.error(f"Error checking user credentials: {e}")
            return False
    
    async def create_user(self, username: str, password: str) -> bool:
        """
        Create a new user account
        
        Args:
            username: Username for the new account
            password: Plain text password (will be hashed with SHA-512)
            
        Returns:
            True if user created successfully, False otherwise
        """
        try:
            # Check if user already exists
            existing = await self.execute_query(
                "SELECT id FROM user WHERE username = ?",
                (username,)
            )
            
            if existing:
                logger.warning(f"Cannot create user {username}: username already exists")
                return False
            
            password_hash = self._hash_password(password)
            
            await self.execute_query(
                "INSERT INTO user (username, password, enabled, deleted, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (username, password_hash, True, False, datetime.now(), datetime.now())
            )
            
            logger.info(f"User created successfully: {username}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating user {username}: {e}")
            return False
    
    async def delete_user(self, username: str) -> bool:
        """
        Delete a user account (soft delete - marks as deleted)
        
        Args:
            username: Username to delete
            
        Returns:
            True if user deleted successfully, False otherwise
        """
        try:
            result = await self.execute_query(
                "UPDATE user SET deleted = ?, enabled = ?, updated_at = ? WHERE username = ?",
                (True, False, datetime.now(), username)
            )
            
            # Check if any rows were affected
            user_check = await self.execute_query(
                "SELECT id FROM user WHERE username = ?",
                (username,)
            )
            
            if not user_check:
                logger.warning(f"Cannot delete user {username}: user not found")
                return False
            
            logger.info(f"User deleted successfully: {username}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting user {username}: {e}")
            return False
    
    async def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        """
        Change user password
        
        Args:
            username: Username whose password to change
            old_password: Current password (for verification)
            new_password: New password to set
            
        Returns:
            True if password changed successfully, False otherwise
        """
        try:
            # Verify current password
            if not await self.check_user(username, old_password):
                logger.warning(f"Password change failed for {username}: invalid current password")
                return False
            
            new_password_hash = self._hash_password(new_password)
            
            await self.execute_query(
                "UPDATE user SET password = ?, updated_at = ? WHERE username = ? AND enabled = ? AND deleted = ?",
                (new_password_hash, datetime.now(), username, True, False)
            )
            
            logger.info(f"Password changed successfully for user: {username}")
            return True
            
        except Exception as e:
            logger.error(f"Error changing password for user {username}: {e}")
            return False
    
    async def get_user_info(self, username: str) -> Optional[Dict[str, Any]]:
        """
        Get user information (excluding password)
        
        Args:
            username: Username to get info for
            
        Returns:
            Dictionary with user info or None if not found
        """
        try:
            result = await self.execute_query(
                "SELECT id, username, enabled, deleted, created_at, updated_at FROM user WHERE username = ?",
                (username,)
            )
            
            if result:
                return result[0]
            return None
            
        except Exception as e:
            logger.error(f"Error getting user info for {username}: {e}")
            return None
    
    async def list_users(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        """
        List all users (excluding passwords)
        
        Args:
            include_deleted: Whether to include deleted users
            
        Returns:
            List of user dictionaries
        """
        try:
            if include_deleted:
                query = "SELECT id, username, enabled, deleted, created_at, updated_at FROM user ORDER BY username"
                params = ()
            else:
                query = "SELECT id, username, enabled, deleted, created_at, updated_at FROM user WHERE deleted = ? ORDER BY username"
                params = (False,)
            
            result = await self.execute_query(query, params)
            return result or []
            
        except Exception as e:
            logger.error(f"Error listing users: {e}")
            return []
    
    # Service Management Functions
    
    async def get_service(self, service_name: str) -> Optional[Dict[str, Any]]:
        """
        Get service configuration by name
        
        Args:
            service_name: Name of the service
            
        Returns:
            Service configuration dictionary or None if not found
        """
        try:
            result = await self.execute_query(
                "SELECT * FROM service WHERE service_name = ?",
                (service_name,)
            )
            return result[0] if result else None
            
        except Exception as e:
            logger.error(f"Error getting service {service_name}: {e}")
            return None
    
    async def get_auto_start_services(self) -> List[Dict[str, Any]]:
        """
        Get all services that should auto-start
        
        Returns:
            List of service configurations for auto-start services
        """
        try:
            result = await self.execute_query(
                "SELECT * FROM service WHERE enabled = ? AND auto_start = ? ORDER BY service_name",
                (True, True)
            )
            return result or []
            
        except Exception as e:
            logger.error(f"Error getting auto-start services: {e}")
            return []
    
    async def list_services(self) -> List[Dict[str, Any]]:
        """
        List all services
        
        Returns:
            List of all service configurations
        """
        try:
            result = await self.execute_query(
                "SELECT * FROM service ORDER BY service_name"
            )
            return result or []
            
        except Exception as e:
            logger.error(f"Error listing services: {e}")
            return []
    
    async def create_or_update_service(
        self, 
        service_name: str, 
        enabled: bool = True,
        auto_start: bool = True,
        singleton: bool = True,
        ports: Optional[str] = None,
        description: Optional[str] = None,
        settings_json: Optional[str] = None,
        status: Optional[str] = None
    ) -> bool:
        """
        Create or update a service configuration
        
        Args:
            service_name: Name of the service
            enabled: Whether the service is enabled
            auto_start: Whether to auto-start the service
            singleton: Whether only one instance is allowed
            ports: Comma-separated list of ports
            description: Service description
            settings_json: JSON settings for the service
            status: Current service status
            
        Returns:
            True if successful, False otherwise
        """
        try:
            await self.execute_query(
                """INSERT OR REPLACE INTO service 
                   (service_name, enabled, auto_start, singleton, ports, description, settings_json, status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (service_name, enabled, auto_start, singleton, ports, description, settings_json, status, datetime.now())
            )
            
            logger.info(f"Service configuration updated: {service_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating/updating service {service_name}: {e}")
            return False
    
    async def update_service_status(self, service_name: str, status: str) -> bool:
        """
        Update service status
        
        Args:
            service_name: Name of the service
            status: New status (running, stopped, error, etc.)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            await self.execute_query(
                "UPDATE service SET status = ?, updated_at = ? WHERE service_name = ?",
                (status, datetime.now(), service_name)
            )
            return True
            
        except Exception as e:
            logger.error(f"Error updating service status for {service_name}: {e}")
            return False
    
    async def enable_service(self, service_name: str, enabled: bool = True) -> bool:
        """
        Enable or disable a service
        
        Args:
            service_name: Name of the service
            enabled: Whether to enable (True) or disable (False) the service
            
        Returns:
            True if successful, False otherwise
        """
        try:
            await self.execute_query(
                "UPDATE service SET enabled = ?, updated_at = ? WHERE service_name = ?",
                (enabled, datetime.now(), service_name)
            )
            
            action = "enabled" if enabled else "disabled"
            logger.info(f"Service {service_name} {action}")
            return True
            
        except Exception as e:
            logger.error(f"Error enabling/disabling service {service_name}: {e}")
            return False
    
    async def set_service_auto_start(self, service_name: str, auto_start: bool = True) -> bool:
        """
        Set service auto-start configuration
        
        Args:
            service_name: Name of the service
            auto_start: Whether to auto-start the service
            
        Returns:
            True if successful, False otherwise
        """
        try:
            await self.execute_query(
                "UPDATE service SET auto_start = ?, updated_at = ? WHERE service_name = ?",
                (auto_start, datetime.now(), service_name)
            )
            
            action = "enabled" if auto_start else "disabled"
            logger.info(f"Auto-start {action} for service {service_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error setting auto-start for service {service_name}: {e}")
            return False
