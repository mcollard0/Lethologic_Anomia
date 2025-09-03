# Database Migration: Config Table Refactoring (2025-01-09)

## Overview

This migration refactors the `config` table to use a composite primary key structure and removes unnecessary columns. The changes improve data organization and eliminate database constraints issues.

## Breaking Changes

### Schema Changes

**Old Schema:**
```sql
CREATE TABLE config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) UNIQUE NOT NULL,
    value TEXT NOT NULL,
    description TEXT,
    service VARCHAR(64),  -- Optional
    value_type VARCHAR(20) DEFAULT 'string',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

**New Schema:**
```sql
CREATE TABLE config (
    service TEXT NOT NULL,  -- Now required and first
    name TEXT NOT NULL,
    value TEXT,             -- Now nullable
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (service, name)  -- Composite primary key
);
```

### Key Changes

1. **Composite Primary Key**: Now uses `(service, name)` instead of auto-increment `id`
2. **Required Service Column**: `service` is now NOT NULL and comes first
3. **Nullable Value**: `value` column is now nullable
4. **Removed Columns**: 
   - `id` (replaced by composite key)
   - `description` (rarely used)
   - `value_type` (implicit from context)
5. **Column Order**: `service` comes before `name` to match the primary key order

### API Changes

**Database Manager Methods:**

```python
# OLD API
await db_manager.get_config(name, default=None)
await db_manager.set_config(name, value, service="LA", value_type="string")

# NEW API  
await db_manager.get_config(service, name, default=None)
await db_manager.set_config(service, name, value)
```

**SQL Query Changes:**

```sql
-- OLD QUERIES
SELECT value FROM config WHERE name = ?
INSERT OR REPLACE INTO config (name, value, service, value_type, created_at, updated_at) 
VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)

-- NEW QUERIES
SELECT value FROM config WHERE service = ? AND name = ?
INSERT OR REPLACE INTO config (service, name, value, created_at, updated_at) 
VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
```

## Migration Process

### Automatic Migration

Use the provided database rebuild tool to automatically migrate to the new schema:

```bash
# Rebuild database with backup
python tools/rebuild_db.py

# Force rebuild without confirmation
python tools/rebuild_db.py --force

# Rebuild without backup (risky)
python tools/rebuild_db.py --no-backup
```

Or use the underlying script directly:

```bash
# Using the initialization script
python scripts/init_db.py --force --verbose
```

### Manual Migration Steps

If you need to migrate manually:

1. **Backup Current Database**
   ```bash
   cp lethologic_anomia.db lethologic_anomia.db.backup_$(date +%Y%m%d_%H%M%S)
   ```

2. **Export Existing Config Data**
   ```sql
   -- Save existing config data
   SELECT COALESCE(service, 'LA') as service, name, value 
   FROM config WHERE name IS NOT NULL AND name != '';
   ```

3. **Drop and Recreate Database**
   ```bash
   rm lethologic_anomia.db
   python scripts/init_db.py --force
   ```

4. **Restore Data** (if needed)
   ```sql
   INSERT OR REPLACE INTO config (service, name, value) VALUES (?, ?, ?);
   ```

## Service Codes

The new schema uses service codes to organize configuration by system component:

| Service Code | Description | Example Keys |
|--------------|-------------|--------------|
| `LA` | Lethologic Anomia Core | `VERSION`, `TRUST_LEVEL`, `LAST_COMMAND` |
| `AI` | AI/ML Services | `DEFAULT_MODEL`, `MAX_TOKENS` |
| `SCP` | DICOM SCP Services | `DEFAULT_PORT`, `DEFAULT_AE_TITLE`, `SERVICE_CLASS_PROVIDER` |
| `WEB` | Web Interface | `DEFAULT_PORT`, `DEFAULT_HOST` |
| `PROC` | Process Management | `process_<pid>` entries |
| `SYSTEM` | System Configuration | `database_version`, `system_initialized` |

### Guidelines for Service Codes

- Use SHORT, descriptive codes (2-8 characters)
- Use UPPERCASE for consistency
- Group related functionality under the same service
- Use specific codes for different service types (e.g., `SCP`, `SCU` for DICOM)

## Code Changes Required

### Python Code Updates

1. **Update get_config calls:**
   ```python
   # OLD
   value = await db_manager.get_config("TRUST_LEVEL")
   
   # NEW
   value = await db_manager.get_config("LA", "TRUST_LEVEL")
   ```

2. **Update set_config calls:**
   ```python
   # OLD
   await db_manager.set_config("TRUST_LEVEL", "5", "LA")
   
   # NEW
   await db_manager.set_config("LA", "TRUST_LEVEL", "5")
   ```

3. **Update SQL queries:**
   ```python
   # OLD
   await db_manager.execute_query(
       "SELECT value FROM config WHERE name = ?", 
       ("TRUST_LEVEL",)
   )
   
   # NEW
   await db_manager.execute_query(
       "SELECT value FROM config WHERE service = ? AND name = ?", 
       ("LA", "TRUST_LEVEL")
   )
   ```

### Configuration Data Migration

Existing single-service applications should use the `LA` service code for backward compatibility:

```python
# During migration, convert single config entries:
OLD_DATA = {"TRUST_LEVEL": "5", "VERSION": "1.0.0"}
NEW_DATA = [("LA", "TRUST_LEVEL", "5"), ("LA", "VERSION", "1.0.0")]
```

## Testing

After migration, verify the changes:

1. **Test Database Connection:**
   ```python
   from core.database import DatabaseManager
   db = DatabaseManager("lethologic_anomia.db")
   await db.initialize()
   ```

2. **Test Configuration Operations:**
   ```python
   # Test setting and getting config values
   await db.set_config("LA", "test_key", "test_value")
   value = await db.get_config("LA", "test_key")
   assert value == "test_value"
   ```

3. **Test Composite Key Constraints:**
   ```python
   # Test that same key with different services works
   await db.set_config("LA", "port", "8000")
   await db.set_config("SCP", "port", "104")
   
   la_port = await db.get_config("LA", "port")
   scp_port = await db.get_config("SCP", "port")
   assert la_port == "8000" and scp_port == "104"
   ```

## Rollback

If you need to rollback to the old schema:

1. **Restore from backup:**
   ```bash
   cp lethologic_anomia.db.backup_* lethologic_anomia.db
   ```

2. **Or manually recreate old schema and migrate data back**

## Troubleshooting

### Common Issues

1. **"table config has no column named description"**
   - Old code trying to use removed columns
   - Fix: Update all SQL queries to use new schema

2. **"UNIQUE constraint failed: config.service, config.name"**
   - Trying to insert duplicate service/name combination
   - Fix: Use `INSERT OR REPLACE` instead of `INSERT`

3. **"NOT NULL constraint failed: config.service"**
   - Old code not providing service parameter
   - Fix: Update all config operations to include service code

### Verification Commands

```bash
# Check table schema
python -c "
import sqlite3
conn = sqlite3.connect('lethologic_anomia.db')
cursor = conn.execute('PRAGMA table_info(config)')
for row in cursor: print(row)
"

# Check data structure
python -c "
import sqlite3
conn = sqlite3.connect('lethologic_anomia.db')
cursor = conn.execute('SELECT service, name, value FROM config LIMIT 10')
for row in cursor: print(row)
"
```

## Related Files

- `database_schema_unified.sql` - Updated schema definition
- `scripts/init_db.py` - Database initialization script
- `tools/rebuild_db.py` - Database rebuild tool
- `core/database.py` - Database manager with updated API
- `core/ai_loop.py` - Updated to use new config API
- `core/redis_manager.py` - Updated to use new config API

## References

- [Database Design Best Practices](https://en.wikipedia.org/wiki/Database_normalization)
- [SQLite Composite Primary Keys](https://www.sqlite.org/lang_createtable.html#primkeyconst)
