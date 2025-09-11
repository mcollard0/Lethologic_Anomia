# Granular CLI Options Added to Lethologic Anomia

## Overview

Enhanced Lethologic Anomia CLI to match the granular control available in the Untitled Migration Service. Added 20+ new command-line options for direct access to common operations.

## New CLI Options Added

### DICOM Operations
- `--port <port>`, `-p` - Specify DICOM port number
- `--aet <title>`, `-a` - Specify DICOM AE Title  
- `--start-scp`, `-s` - Start DICOM Service Class Provider
- `--start-scu <target>` - Start DICOM SCU to target
- `--discovery <target>` - Run DICOM discovery on target

### AI Model Management
- `--get-model` - Show current AI model
- `--list-models` - List all available AI models
- `--set-model <model>` - Set AI model
- `--set-trust <level>` - Set AI trust level (-127 to 127)
- `--get-trust` - Get current trust level
- `--set-aggression <level>` - Set AI aggression level (-127 to 127)
- `--get-aggression` - Get current aggression level

### Database Operations
- `--query <sql>` - Execute database query
- `--insert-query <sql>` - Execute database insert/update
- `--schema` - Show database schema

### Migration & System Operations
- `--get-migration-status <site>` - Get migration status for site
- `--new-migration <site>` - Create new migration for site
- `--start-index` - Start DICOM file indexing
- `--start-parse` - Start DICOM file parsing
- `--log <message>` - Add message to log

## Implementation Details

### Code Structure Changes

1. **Enhanced Main Command Function**:
   - Added 20+ new Click options to the main command decorator
   - Organized options into logical groups (DICOM, AI, Database, System)
   - Maintained backward compatibility with existing functionality

2. **Immediate vs Service Options**:
   - **Immediate options**: Database queries, model management, trust/aggression settings - handled with minimal service startup
   - **Service options**: DICOM operations, indexing, migrations - require full service initialization

3. **Handler Functions**:
   - `_handle_immediate_options()` - Quick database access operations
   - `_handle_service_options()` - Complex operations requiring service components

### Key Features

**Smart Option Handling**:
- Options categorized by complexity and dependency requirements
- Immediate options bypass full service startup for faster response
- Service options initialize necessary components automatically

**Database Integration**:
- Direct SQL query execution with result formatting
- Configuration management through database config table
- Trust/aggression levels stored in database with validation

**Error Handling & Validation**:
- Trust/aggression levels validated to (-127, 127) range
- SQL query error handling with user-friendly messages
- Input validation for all parameters

**Rich Console Output**:
- Colorized and emoji-enhanced output using Rich library
- Structured display of query results and configuration data
- Clear success/error indicators

## Usage Examples

### Basic DICOM Operations
```bash
# Start DICOM SCP with custom port and AE title
python lethologic_anomia.py --start-scp --port 11112 --aet MY_SCP

# Discover DICOM services on network
python lethologic_anomia.py --discovery 192.168.1.100:104

# Start DICOM SCU to specific target
python lethologic_anomia.py --start-scu "192.168.1.100:104:PACS_AET"
```

### AI Model Management
```bash
# Check current model and list available models
python lethologic_anomia.py --get-model --list-models

# Set AI model and adjust personality parameters
python lethologic_anomia.py --set-model "anthropic/claude-3-sonnet"
python lethologic_anomia.py --set-trust 15 --set-aggression -3
```

### Database Operations
```bash
# Execute database queries
python lethologic_anomia.py --query "SELECT * FROM studies LIMIT 5"
python lethologic_anomia.py --query "SELECT COUNT(*) FROM patients"

# View database schema
python lethologic_anomia.py --schema

# Insert log entries
python lethologic_anomia.py --insert-query "INSERT INTO log (level, message) VALUES ('INFO', 'System check')"
```

### System Operations
```bash
# Check migration status
python lethologic_anomia.py --get-migration-status "Hospital_A"

# Start system operations
python lethologic_anomia.py --start-index
python lethologic_anomia.py --start-parse

# Add log messages
python lethologic_anomia.py --log "Daily system maintenance completed"
```

## Enhanced Help System

Updated `--help-extended` output includes:
- Categorized CLI options with descriptions
- Usage examples for each option category
- Integration instructions with existing config system
- Clear distinction between immediate and service operations

## Benefits

1. **Parity with C++ Service**: Now matches the granular control available in Untitled Migration Service
2. **Improved Developer Experience**: Direct CLI access to common operations without interactive mode
3. **Automation Friendly**: All operations can be scripted and automated
4. **Consistent Interface**: Familiar option patterns for users of both services
5. **Performance**: Lightweight immediate options bypass full service startup

## Integration Points

- **Configuration Management**: CLI options integrate with existing config subcommands
- **Database Schema**: Uses existing unified database schema
- **Service Components**: Leverages existing ProcessManager and service architecture
- **AI Integration**: Compatible with existing AI service components

## Testing Status

- ✅ CLI syntax validation completed
- ✅ Click option parsing verified
- ✅ Handler function structure implemented
- ✅ Help system updated with new options
- ⏳ Integration testing pending full dependency resolution

## Future Enhancements

Potential additions to complete parity:
- Algorithm testing utilities (FizzBuzz, Fibonacci, Turing test)
- Stack monitoring and system diagnostics
- Additional DICOM operations (C-MOVE, C-FIND variations)
- Batch operation modes
- Configuration file-based option sets

---

This enhancement brings Lethologic Anomia CLI capabilities in line with the Untitled Migration Service, providing users with comprehensive direct command-line control over all major system functions.
