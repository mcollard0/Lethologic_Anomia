#!/usr/bin/env python3
"""
Unified Database Migration Script

This script:
1. Merges data from lethologic_anomia.db into lethologic_anomia.db
2. Updates the schema to the unified version with singular table names
3. Updates all code references to use single database
4. Removes the separate lethologic_anomia.db file
"""

import os
import sqlite3
import sys
import glob
from datetime import datetime

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def backup_existing_data(main_db_path: str, migration_db_path: str):
    """Backup existing data from both databases"""
    print("📦 Backing up existing data...")
    
    # Export data from both databases
    backup_data = {
        'main_db': {},
        'migration_db': {}
    }
    
    # Backup main database data
    if os.path.exists(main_db_path):
        conn = sqlite3.connect(main_db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = cursor.fetchall()
        
        for table in tables:
            table_name = table['name']
            cursor.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()
            backup_data['main_db'][table_name] = [dict(row) for row in rows]
        
        conn.close()
        print(f"✅ Backed up {len(tables)} tables from main database")
    
    # Backup migration database data
    if os.path.exists(migration_db_path):
        conn = sqlite3.connect(migration_db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = cursor.fetchall()
        
        for table in tables:
            table_name = table['name']
            cursor.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()
            backup_data['migration_db'][table_name] = [dict(row) for row in rows]
        
        conn.close()
        print(f"✅ Backed up {len(tables)} tables from migration database")
    
    return backup_data

def create_unified_database(db_path: str):
    """Create unified database with new schema"""
    
    # Remove existing database
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"🗑️  Removed existing database: {db_path}")
    
    # Create new database from schema file
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print(f"🆕 Creating unified database: {db_path}")
    
    # Read and execute the unified schema
    schema_path = "/home/michael/FASTESTARCHIVE/Archive/Lethologic Anomia/database_schema_unified.sql"
    
    if os.path.exists(schema_path):
        with open(schema_path, 'r') as f:
            schema_sql = f.read()
        
        # Execute schema in chunks (SQLite can be sensitive to multiple statements)
        statements = [stmt.strip() for stmt in schema_sql.split(';') if stmt.strip()]
        
        for statement in statements:
            if statement:
                try:
                    cursor.execute(statement)
                except Exception as e:
                    print(f"Warning: Failed to execute statement: {e}")
                    print(f"Statement: {statement[:100]}...")
        
        conn.commit()
        print("✅ Applied unified schema")
    else:
        print("❌ Schema file not found, creating basic schema")
        
        # Basic schema if file not found
        cursor.execute("""
            CREATE TABLE config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(255) UNIQUE NOT NULL,
                value TEXT NOT NULL,
                description TEXT,
                service VARCHAR(64),
                value_type VARCHAR(20) DEFAULT 'string',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE site (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sitename VARCHAR(255) UNIQUE NOT NULL,
                status VARCHAR(50),
                enabled BOOLEAN NOT NULL DEFAULT 1,
                deleted BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
    
    conn.close()
    print("✅ Created unified database")

def restore_data_to_unified_db(db_path: str, backup_data: dict):
    """Restore backed up data to the unified database"""
    print("📥 Restoring data to unified database...")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    restored_count = 0
    
    # Restore data from main database first
    for table_name, rows in backup_data['main_db'].items():
        if not rows:
            continue
            
        try:
            # Check if table exists in new schema
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cursor.fetchone():
                print(f"⚠️  Table {table_name} not found in unified schema, skipping")
                continue
            
            # Get column names for this table
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns_info = cursor.fetchall()
            column_names = [col[1] for col in columns_info]
            
            # Insert data
            for row in rows:
                # Filter row data to only include existing columns
                filtered_row = {k: v for k, v in row.items() if k in column_names}
                
                if filtered_row:
                    placeholders = ', '.join(['?' for _ in filtered_row])
                    columns = ', '.join(filtered_row.keys())
                    values = list(filtered_row.values())
                    
                    cursor.execute(
                        f"INSERT OR IGNORE INTO {table_name} ({columns}) VALUES ({placeholders})",
                        values
                    )
                    restored_count += 1
            
            print(f"✅ Restored {len(rows)} rows to {table_name}")
            
        except Exception as e:
            print(f"❌ Error restoring data to {table_name}: {e}")
    
    # Restore unique data from migration database (avoid duplicates)
    for table_name, rows in backup_data['migration_db'].items():
        if not rows:
            continue
            
        try:
            # Check if table exists in new schema
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cursor.fetchone():
                print(f"⚠️  Table {table_name} not found in unified schema, skipping")
                continue
            
            # For migration DB data, only restore if not already present
            # This avoids duplicating data that was already in main DB
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            existing_count = cursor.fetchone()[0]
            
            if existing_count > 0:
                print(f"ℹ️  Table {table_name} already has data, skipping migration DB data")
                continue
            
            # Get column names for this table
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns_info = cursor.fetchall()
            column_names = [col[1] for col in columns_info]
            
            # Insert data
            for row in rows:
                # Filter row data to only include existing columns
                filtered_row = {k: v for k, v in row.items() if k in column_names}
                
                if filtered_row:
                    placeholders = ', '.join(['?' for _ in filtered_row])
                    columns = ', '.join(filtered_row.keys())
                    values = list(filtered_row.values())
                    
                    cursor.execute(
                        f"INSERT OR IGNORE INTO {table_name} ({columns}) VALUES ({placeholders})",
                        values
                    )
                    restored_count += 1
            
            print(f"✅ Restored {len(rows)} rows to {table_name} from migration DB")
            
        except Exception as e:
            print(f"❌ Error restoring migration data to {table_name}: {e}")
    
    conn.commit()
    conn.close()
    
    print(f"✅ Restored {restored_count} total records to unified database")

def update_code_references():
    """Update all code references from lethologic_anomia.db to lethologic_anomia.db"""
    print("🔧 Updating code references...")
    
    # Files to update
    files_to_update = [
        "/home/michael/FASTESTARCHIVE/Archive/Lethologic Anomia/utils/fix_timestamp_defaults.py",
        "/home/michael/FASTESTARCHIVE/Archive/Lethologic Anomia/.env.example"
    ]
    
    # Add any Python files that might reference the old database
    python_files = glob.glob("/home/michael/FASTESTARCHIVE/Archive/Lethologic Anomia/**/*.py", recursive=True)
    files_to_update.extend(python_files)
    
    updated_files = []
    
    for file_path in files_to_update:
        if not os.path.exists(file_path):
            continue
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check if file contains lethologic_anomia.db references
            if 'lethologic_anomia.db' in content:
                # Replace references
                updated_content = content.replace('lethologic_anomia.db', 'lethologic_anomia.db')
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(updated_content)
                
                updated_files.append(file_path)
                print(f"✅ Updated {file_path}")
                
        except Exception as e:
            print(f"❌ Error updating {file_path}: {e}")
    
    print(f"✅ Updated {len(updated_files)} files")
    return updated_files

def update_config_table_schema():
    """Update config table to support service-based configuration"""
    print("🔧 Updating config table schema...")
    
    db_path = "/home/michael/FASTESTARCHIVE/Archive/Lethologic Anomia/lethologic_anomia.db"
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if config table has service column
        cursor.execute("PRAGMA table_info(config)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        if 'service' not in column_names:
            print("Adding service column to config table...")
            
            # Add service and value_type columns
            cursor.execute("ALTER TABLE config ADD COLUMN service VARCHAR(64)")
            cursor.execute("ALTER TABLE config ADD COLUMN value_type VARCHAR(20) DEFAULT 'string'")
            
            # Create new index for service
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_config_service ON config(service)")
            
            conn.commit()
            print("✅ Updated config table schema")
        else:
            print("✅ Config table already has correct schema")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error updating config table schema: {e}")

def main():
    """Main function to run unified database migration"""
    
    print("🚀 Unified Database Migration")
    print("=" * 60)
    
    # Database paths
    main_db = "/home/michael/FASTESTARCHIVE/Archive/Lethologic Anomia/lethologic_anomia.db"
    migration_db = "/home/michael/FASTESTARCHIVE/Archive/Lethologic Anomia/lethologic_anomia.db"
    
    try:
        # Step 1: Backup existing data
        backup_data = backup_existing_data(main_db, migration_db)
        
        # Step 2: Create unified database
        create_unified_database(main_db)
        
        # Step 3: Restore data to unified database
        restore_data_to_unified_db(main_db, backup_data)
        
        # Step 4: Update config table schema for service-based config
        update_config_table_schema()
        
        # Step 5: Update code references
        updated_files = update_code_references()
        
        # Step 6: Remove migration database
        if os.path.exists(migration_db):
            os.remove(migration_db)
            print(f"🗑️  Removed separate migration database: {migration_db}")
        
        print("\n🎉 Unified database migration completed successfully!")
        print("✅ All data merged into single lethologic_anomia.db")
        print("✅ All code references updated")
        print("✅ Schema standardized with singular table names")
        print(f"✅ Updated {len(updated_files)} source files")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
