#!/usr/bin/env python3
"""
Database Timestamp Defaults Migration Script

This script ensures that all created_at and updated_at columns 
have proper default timestamp values. For SQLite, it adds 
CURRENT_TIMESTAMP defaults. For other databases, it ensures
Python-level defaults are applied when inserting new records.

According to the requirements:
- Date columns like 'created' and 'updated' should have default 
  timestamps either via SQL defaults (now() or getdate()) or 
  fallback Python insertion when unsupported.
"""

import asyncio
import sqlite3
import sys
import os
from datetime import datetime
from typing import List, Dict, Tuple

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import Settings
from core.database import DatabaseManager
from core.custom_logging import get_logger

logger = get_logger(__name__)


class TimestampDefaultsMigration:
    """Manages timestamp defaults migration for database tables"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.connection = None
    
    def connect(self):
        """Connect to the database"""
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
    
    def disconnect(self):
        """Disconnect from database"""
        if self.connection:
            self.connection.close()
    
    def get_tables_with_timestamp_columns(self) -> List[Dict]:
        """Find all tables with created_at or updated_at columns"""
        cursor = self.connection.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = cursor.fetchall()
        
        timestamp_tables = []
        
        for table in tables:
            table_name = table['name']
            
            # Get column info for this table
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            
            timestamp_columns = []
            for col in columns:
                col_name = col['name'].lower()
                if col_name in ['created_at', 'updated_at', 'created', 'updated']:
                    timestamp_columns.append({
                        'name': col['name'],
                        'type': col['type'],
                        'notnull': bool(col['notnull']),
                        'default': col['dflt_value'],
                        'has_default': col['dflt_value'] is not None
                    })
            
            if timestamp_columns:
                timestamp_tables.append({
                    'table_name': table_name,
                    'timestamp_columns': timestamp_columns
                })
        
        return timestamp_tables
    
    def fix_table_defaults(self, table_name: str, columns_to_fix: List[str]) -> bool:
        """Fix timestamp defaults for a specific table
        
        Args:
            table_name: Name of the table to fix
            columns_to_fix: List of column names that need default timestamps
            
        Returns:
            True if successful, False otherwise
        """
        try:
            cursor = self.connection.cursor()
            
            # SQLite doesn't support ALTER COLUMN with DEFAULT directly
            # We need to recreate the table with proper defaults
            
            # Get current table schema
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            
            # Get current indexes
            cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='{table_name}' AND sql IS NOT NULL")
            indexes = cursor.fetchall()
            
            # Get foreign keys
            cursor.execute(f"PRAGMA foreign_key_list({table_name})")
            foreign_keys = cursor.fetchall()
            
            # Build new table SQL with proper defaults
            column_definitions = []
            for col in columns:
                col_name = col['name']
                col_type = col['type']
                
                # Build column definition
                col_def = f"{col_name} {col_type}"
                
                # Add NOT NULL if applicable
                if col['notnull']:
                    col_def += " NOT NULL"
                
                # Add DEFAULT
                if col_name.lower() in ['created_at', 'updated_at', 'created', 'updated']:
                    # Add timestamp default
                    col_def += " DEFAULT CURRENT_TIMESTAMP"
                elif col['dflt_value'] is not None:
                    col_def += f" DEFAULT {col['dflt_value']}"
                
                # Add PRIMARY KEY if applicable
                if col['pk']:
                    col_def += " PRIMARY KEY"
                    if col_type.upper() == "INTEGER":
                        col_def += " AUTOINCREMENT"
                
                column_definitions.append(col_def)
            
            # Add foreign key constraints
            for fk in foreign_keys:
                fk_def = f"FOREIGN KEY ({fk['from']}) REFERENCES {fk['table']}({fk['to']})"
                column_definitions.append(fk_def)
            
            new_table_sql = f"CREATE TABLE {table_name}_new ({', '.join(column_definitions)})"
            
            # Execute migration in transaction
            cursor.execute("BEGIN TRANSACTION")
            
            try:
                # Create new table with proper defaults
                cursor.execute(new_table_sql)
                
                # Copy existing data
                column_names = [col['name'] for col in columns]
                copy_sql = f"INSERT INTO {table_name}_new ({', '.join(column_names)}) SELECT {', '.join(column_names)} FROM {table_name}"
                cursor.execute(copy_sql)
                
                # Drop old table
                cursor.execute(f"DROP TABLE {table_name}")
                
                # Rename new table
                cursor.execute(f"ALTER TABLE {table_name}_new RENAME TO {table_name}")
                
                # Recreate indexes
                for index in indexes:
                    index_sql = index['sql'].replace(f" ON {table_name}", f" ON {table_name}")
                    cursor.execute(index_sql)
                
                # Commit transaction
                cursor.execute("COMMIT")
                
                print(f"✅ Fixed timestamp defaults for table: {table_name}")
                return True
                
            except Exception as e:
                cursor.execute("ROLLBACK")
                raise e
                
        except Exception as e:
            print(f"❌ Error fixing table {table_name}: {e}")
            return False
    
    def run_migration(self):
        """Run the complete timestamp defaults migration"""
        print("🔧 Starting Timestamp Defaults Migration...")
        print("=" * 60)
        
        try:
            self.connect()
            
            # Find tables that need fixing
            tables_info = self.get_tables_with_timestamp_columns()
            
            if not tables_info:
                print("✅ No tables with timestamp columns found.")
                return
            
            print(f"📋 Found {len(tables_info)} tables with timestamp columns:")
            
            for table_info in tables_info:
                table_name = table_info['table_name']
                timestamp_cols = table_info['timestamp_columns']
                
                print(f"\n📊 Table: {table_name}")
                
                columns_needing_fix = []
                for col in timestamp_cols:
                    status = "✅ HAS DEFAULT" if col['has_default'] else "❌ NO DEFAULT"
                    print(f"   {col['name']} ({col['type']}) - {status}")
                    
                    if not col['has_default']:
                        columns_needing_fix.append(col['name'])
                
                if columns_needing_fix:
                    print(f"🔧 Fixing defaults for: {', '.join(columns_needing_fix)}")
                    if self.fix_table_defaults(table_name, columns_needing_fix):
                        print(f"✅ {table_name} defaults fixed successfully")
                    else:
                        print(f"❌ Failed to fix {table_name} defaults")
                else:
                    print(f"✅ {table_name} already has proper defaults")
            
            print(f"\n🎉 Timestamp defaults migration completed!")
            
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            raise
        finally:
            self.disconnect()


async def update_database_manager_defaults():
    """Update DatabaseManager to ensure Python-level timestamp defaults"""
    
    # Check if we need to update the database manager
    db_manager_path = "/home/michael/FASTESTARCHIVE/Archive/Lethologic Anomia/core/database.py"
    
    try:
        with open(db_manager_path, 'r') as f:
            content = f.read()
        
        # Check if we already have timestamp handling
        if 'def ensure_timestamps' in content:
            print("✅ DatabaseManager already has timestamp handling")
            return True
        
        # Add timestamp handling method to DatabaseManager
        timestamp_method = '''
    def ensure_timestamps(self, data: dict, include_updated: bool = True) -> dict:
        """Ensure created_at and updated_at timestamps are present in data
        
        Args:
            data: Dictionary of column data
            include_updated: Whether to set updated_at (default True)
            
        Returns:
            Data dictionary with timestamp defaults added
        """
        now = datetime.now()
        
        # Add created_at if not present
        if 'created_at' not in data or data['created_at'] is None:
            data['created_at'] = now
        
        if 'created' not in data or data['created'] is None:
            data['created'] = now
        
        # Add updated_at if requested and not present
        if include_updated:
            if 'updated_at' not in data or data['updated_at'] is None:
                data['updated_at'] = now
                
            if 'updated' not in data or data['updated'] is None:
                data['updated'] = now
        
        return data
'''
        
        # Find a good place to insert the method (before execute_query)
        insert_position = content.find("    async def execute_query")
        if insert_position == -1:
            print("❌ Could not find insertion point in DatabaseManager")
            return False
        
        # Insert the new method
        updated_content = content[:insert_position] + timestamp_method + "\n" + content[insert_position:]
        
        # Add datetime import if not present
        if "from datetime import datetime" not in updated_content:
            import_position = updated_content.find("from typing import")
            if import_position != -1:
                import_line = "from datetime import datetime\n"
                updated_content = updated_content[:import_position] + import_line + updated_content[import_position:]
        
        # Write updated content
        with open(db_manager_path, 'w') as f:
            f.write(updated_content)
        
        print("✅ Added timestamp handling to DatabaseManager")
        return True
        
    except Exception as e:
        print(f"❌ Error updating DatabaseManager: {e}")
        return False


def main():
    """Main function to run timestamp defaults migration"""
    
    print("🚀 Database Timestamp Defaults Migration")
    print("=" * 60)
    
    # Database files to migrate (unified single database)
    db_files = [
        "/home/michael/FASTESTARCHIVE/Archive/Lethologic Anomia/lethologic_anomia.db"
    ]
    
    for db_file in db_files:
        if os.path.exists(db_file):
            print(f"\n📋 Processing database: {os.path.basename(db_file)}")
            migration = TimestampDefaultsMigration(db_file)
            migration.run_migration()
        else:
            print(f"⚠️  Database file not found: {db_file}")
    
    # Update Python code to ensure timestamp defaults
    print("\n📋 Updating Python DatabaseManager...")
    asyncio.run(update_database_manager_defaults())
    
    print("\n🏁 All timestamp defaults migration tasks completed!")


if __name__ == "__main__":
    main()
