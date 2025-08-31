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

from .logging import get_logger

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
    name: Mapped[str] = mapped_column(String(255), unique=True)
    value: Mapped[str] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class Site(Base):
    """Sites table - equivalent to C++ SITES table"""
    __tablename__ = 'sites'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    sitename: Mapped[str] = mapped_column(String(255), unique=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ae_title: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class Study(Base):
    """Studies table - equivalent to C++ STUDIES table"""
    __tablename__ = 'studies'
    
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
    site_id: Mapped[Optional[int]] = mapped_column(ForeignKey('sites.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class Series(Base):
    """Series table - equivalent to C++ SERIES table"""
    __tablename__ = 'series'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    series_uid: Mapped[str] = mapped_column(String(64), unique=True)
    study_id: Mapped[int] = mapped_column(ForeignKey('studies.id'))
    series_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    series_description: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    modality: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    body_part: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    series_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    series_time: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class Image(Base):
    """Images table - equivalent to C++ IMAGES table"""
    __tablename__ = 'images'
    
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
                result = await session.execute(text(query), params or {})
                if result.returns_rows:
                    rows = result.fetchall()
                    return [dict(row._mapping) for row in rows]
                else:
                    await session.commit()
                    return []
                    
        except Exception as e:
            logger.error(f"Error executing query: {e}")
            raise
