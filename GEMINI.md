# GEMINI.md

This file provides guidance to GEMINI when working with code in this repository.

## Project Overview

Lethologic Anomia is a Python-based medical imaging migration service that supports DICOM/HL7 operations, multi-database backends, and AI integration. Originally ported from a C++ Windows service to a cross-platform Python application.

## Common Commands

### Running the Service

```fish
# Activate virtual environment and run (recommended)
./lethologic_anomia.sh --help

# Run with debug output
./lethologic_anomia.sh --debug

# Direct execution
source venv/bin/activate && python lethologic_anomia.py --help
```

### Testing

Run tests directly with pytest:

```fish
# Run all tests
pytest tests/

# Run specific test files
pytest tests/test_config.py
pytest tests/test_dicom_functionality.py

# Run with coverage
pytest --cov=core --cov=service tests/
```

### Development Operations

```fish
# Generate test DICOM images
python utils/dicom_generator.py --images 1000 --patients 50 --studies 100

# Database schema inspection
python lethologic_anomia.py --schema

# Execute database queries
python lethologic_anomia.py --query "SELECT * FROM studies LIMIT 5"

# DICOM operations
python lethologic_anomia.py --start-scp --port 50104 --aet MY_SCP
python lethologic_anomia.py --discovery 192.168.1.100:104
```

### Code Quality

```fish

We're going to have to talk. I have exacting and specific ideas about code quality.

# Format code
I have written a custom formatter. However, if I run it on Save... 

# Lint
flake8 core/ service/ utils/

# Type checking
mypy core/ service/
```

## Architecture

### Core Components

**Process Management** (`core/process_manager.py`): Orchestrates all services using Redis for coordination and database for persistence. Services are tracked with ProcessInfo dataclasses containing state, PID, heartbeat, and metadata. Supports three execution modes: thread (I/O bound), process (CPU intensive), and asyncio (async I/O).

**AI Integration** (`core/ai_loop.py`): Multi-provider AI service supporting OpenAI, Anthropic (Claude), XAI (Grok), and local HuggingFace models. Priority order configurable via AI_PROVIDERS environment variable. Implements function calling for system operations like DICOM discovery, database queries, FizzBuzz, math quiz generation, and migration management.

**Database Layer** (`core/database.py`, `core/extended_database.py`): SQLAlchemy-based multi-backend support (SQLite, PostgreSQL, MySQL, Oracle, MongoDB). Unified schema with singular table names (study, series, image, user, site, device, service). Config stored hierarchically by service in config table.

**Service Architecture** (`service/`): Modular services including web interface (FastAPI on port 50443), SSH server (port 50022), DICOM services (SCP/SCU/Search/Parser), HL7 listeners, and AI processors. All use consistent async patterns.

### Port Configuration (50### Scheme)

All services use the 50### port numbering scheme:
- DICOM SCP: 50104
- DICOM SCP SSL: 50112
- Web Interface: 50443 (SSL) / 50080 (HTTP)
- SSH Server: 50022
- HL7 Listener: 50575
- HL7 Passthrough: 50576
- Redis: 50379

### Database Schema

Single unified database with singular table names. Core tables:
- `config`: Hierarchical service-based configuration (service, name, value)
- `site`: Migration sites with status tracking
- `user`: Authentication and access control
- `device`: DICOM/HL7 device connections (AE titles, IPs, ports)
- `service`: Runtime service state and configuration
- `study`/`series`/`image`: DICOM data hierarchy
- `hl7_message`/`hl7_adt`/`hl7_order`: HL7 message storage and parsed data

### AI Service Flow

1. Initialize providers in priority order (configurable via AI_PROVIDERS)
2. Load local HuggingFace model (Mistral-7B-Instruct, fallback to DialoGPT)
3. Process user input through selected provider
4. Execute function calls via `_handle_function_call()`
5. Track responses and trust/aggression levels in database

### Process Manager Lifecycle

1. `initialize()`: Sets up database, Redis, config manager, starts heartbeat and monitoring workers
2. `auto_start_core_services()`: Launches configured services (web, SSH, DICOM, HL7)
3. Service monitoring via heartbeat polling and Redis coordination
4. `shutdown()`: Graceful termination of all managed processes

## Key Implementation Details

### Service Registration

Services register via `ProcessManager.register_process()` with ProcessInfo containing:
- `process_id`: Unique identifier
- `process_type`: Enum from ProcessType
- `state`: ProcessState (stopped/starting/running/stopping/error)
- `pid`, `started_at`, `last_heartbeat`, `metadata`

### Async Patterns

All services implement:
- `initialize()`: Setup phase
- Main async loop for operation
- `shutdown()`: Cleanup phase
- Exception handling with logger.error()

### Database Configuration

Use `DatabaseConfigManager` for service-specific config:
```python
await config_manager.set_service_config( "dicom_scp", { "port": 50104, "ae_title": "MY_SCP" } );
config = await config_manager.get_service_config( "dicom_scp" );
```

### AI Function Calls

AI can execute system functions via defined schema. Trust levels control access:
- Low trust (0-4): Read-only operations (queries, status checks)
- High trust (5+): Write operations (migrations, inserts, service control)

## Important Notes

- Virtual environment must be activated before running (use `./lethologic_anomia.sh` or `source venv/bin/activate`)
- AI dependencies are optional; service runs in basic mode without them
- Redis is optional; falls back to database and in-memory coordination
- All CLI options support `--help-extended` for detailed documentation
- Service uses rich console output with emojis and color formatting
- FizzBuzz and math_quiz functions are fully implemented for testing

## Environment Configuration

Key environment variables:
- `DATABASE_URL`: Database connection string (default: sqlite:///migration.db)
- `REDIS_URL`: Redis connection string (default: redis://localhost:6379)
- `AI_PROVIDERS`: Comma-separated provider priority list (default: "huggingface_local,xai,anthropic,openai")
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `XAI_API_KEY`: AI provider credentials
- `WEB_PORT`, `SSH_PORT`: Service port overrides

Use `.env.example` or `.env.sample` as templates for local configuration.
