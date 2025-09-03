#!/usr/bin/env python3
"""
Database Initialization Script for Lethologic Anomia
Creates/recreates the unified database with the updated config table schema
"""

import asyncio
import logging
import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)

class DatabaseInitializer:
    """Handles database initialization and schema creation"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or "lethologic_anomia.db"
        self.schema_file = project_root / "database_schema_unified.sql"
    
    def backup_existing_database(self) -> str:
        """Create a backup of the existing database if it exists"""
        if not os.path.exists(self.db_path):
            return None
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{self.db_path}.backup_{timestamp}"
        
        # Copy the database file
        import shutil
        shutil.copy2(self.db_path, backup_path)
        logger.info(f"Database backed up to: {backup_path}")
        return backup_path
    
    def drop_database(self):
        """Remove the existing database file"""
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
            logger.info(f"Existing database removed: {self.db_path}")
    
    def create_database_from_schema(self):
        """Create the database using the unified schema file"""
        if not self.schema_file.exists():
            raise FileNotFoundError(f"Schema file not found: {self.schema_file}")
        
        # Read the schema file
        with open(self.schema_file, 'r') as f:
            schema_sql = f.read()
        
        # Create the database and execute schema
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(schema_sql)
            conn.commit()
            logger.info(f"Database created successfully: {self.db_path}")
        finally:
            conn.close()
    
    async def initialize_with_defaults(self):
        """Initialize database with default configuration values"""
        # Add default configuration values using direct SQL to avoid ORM conflicts
        conn = sqlite3.connect(self.db_path)
        try:
            default_configs = [
                ("LA", "VERSION", "1.0.0"),
                ("LA", "INITIALIZED_AT", datetime.now().isoformat()),
                ("LA", "TRUST_LEVEL", "1"),
                ("LA", "LAST_RESPONSE_POSITION", "0"),
                ("AI", "DEFAULT_MODEL", "anthropic/claude-3-sonnet"),
                ("AI", "MAX_TOKENS", "4000"),
                ("SCP", "DEFAULT_PORT", "104"),
                ("SCP", "DEFAULT_AE_TITLE", "LETHOLOGIC_SCP"),
                ("WEB", "DEFAULT_PORT", "8000"),
                ("WEB", "DEFAULT_HOST", "0.0.0.0"),
            ]
            
            for service, name, value in default_configs:
                conn.execute(
                    "INSERT OR REPLACE INTO config (service, name, value, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (service, name, value)
                )
            
            conn.commit()
            logger.info("Default configuration values added")
            
        finally:
            conn.close()
    
    async def rebuild_database(self, backup: bool = True):
        """Complete database rebuild process"""
        logger.info("Starting database rebuild process...")
        
        # Step 1: Backup existing database
        backup_path = None
        if backup:
            backup_path = self.backup_existing_database()
        
        # Step 2: Drop existing database
        self.drop_database()
        
        # Step 3: Create new database from schema
        self.create_database_from_schema()
        
        # Step 4: Initialize with default values
        await self.initialize_with_defaults()
        
        logger.info("Database rebuild completed successfully!")
        if backup_path:
            logger.info(f"Original database backed up to: {backup_path}")


async def main():
    """Main entry point for the script"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Initialize or rebuild the Lethologic Anomia database")
    parser.add_argument("--db-path", help="Path to the database file", default="lethologic_anomia.db")
    parser.add_argument("--no-backup", action="store_true", help="Skip backup of existing database")
    parser.add_argument("--force", action="store_true", help="Force rebuild without confirmation")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    
    # Check if database exists and prompt for confirmation if not using --force
    if os.path.exists(args.db_path) and not args.force:
        response = input(f"Database {args.db_path} exists. Rebuild it? [y/N]: ")
        if response.lower() not in ('y', 'yes'):
            print("Operation cancelled.")
            return
    
    # Initialize and rebuild database
    initializer = DatabaseInitializer(args.db_path)
    
    try:
        await initializer.rebuild_database(backup=not args.no_backup)
        print(f"✅ Database {args.db_path} successfully initialized!")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        print(f"❌ Database initialization failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
