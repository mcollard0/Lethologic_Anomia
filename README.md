# Lethologic Anomia - Medical Image Migration Service

A comprehensive Python-based medical imaging migration service with AI integration, supporting DICOM/HL7 operations, multi-database backends, and advanced processing capabilities.

## Quick Start

### Prerequisites
- Python 3.8 or higher
- Virtual environment support

### Installation & Setup

1. **Clone and navigate to the project:**
   ```bash
   cd "Lethologic Anomia"
   ```

2. **Create and activate virtual environment:**
   ```bash
   python3 -m venv venv_new
   source venv_new/bin/activate  # Linux/Mac
   # or
   venv_new\Scripts\activate     # Windows
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

### Running the Service

**Method 1: Using the convenience script (recommended)**
```bash
./lethologic_anomia.sh --help              # Show help
./lethologic_anomia.sh --help-extended     # Show detailed help
./lethologic_anomia.sh --debug             # Run in debug mode
```

**Method 2: Direct execution with virtual environment**
```bash
source venv_new/bin/activate && python lethologic_anomia.py --help
```

**Method 3: Using virtual environment Python directly**
```bash
./venv_new/bin/python lethologic_anomia.py --help
```

## Features

### Core Capabilities
- **DICOM Operations**: C-FIND, C-STORE, C-MOVE operations
- **HL7/FHIR Support**: Message processing and routing
- **Multi-Database Support**: SQLite, PostgreSQL, MySQL, Oracle, MongoDB
- **AI Integration**: Text processing, speech interfaces (when dependencies available)
- **Web Interface**: FastAPI-based management dashboard
- **Process Management**: Redis-based background processing
- **SSH Access**: Remote management capabilities

### Available Commands
- `help` - Show available commands
- `discovery <IP>:<Port>` - DICOM network discovery  
- `start_scp` - Start DICOM SCP listener
- `start_scu` - Start DICOM SCU operations
- `start_index` - Index files in directory
- `start_parse` - Parse DICOM files
- `select_query` - Execute SQL queries
- `schema` - Show database schema
- `quit` - Exit service

### Bulk DICOM Generation
Generate test DICOM images for migration testing:

```bash
python utils/dicom_generator.py --images 1000 --patients 50 --studies 100
```

Supports:
- 1-10,000 test images
- 1-100,000 patients and studies  
- 20 most common modalities (CT, MR, XR, US, MG, PET, etc.)
- Realistic metadata and proper DICOM structure

## Configuration

### Environment Variables
```bash
export DATABASE_URL="sqlite:///migration.db"
export REDIS_URL="redis://localhost:6379"
export OPENAI_API_KEY="your-api-key"          # Optional: for AI features
export ANTHROPIC_API_KEY="your-api-key"       # Optional: alternative AI
export WEB_PORT="50443"                       # Web interface port
export SSH_PORT="50022"                       # SSH server port
```

### Configuration File
Create a `config.json` file:
```json
{
  "database_url": "sqlite:///migration.db",
  "redis_url": "redis://localhost:6379",
  "web_port": 50443,
  "ssh_enabled": true,
  "debug": false
}
```

## Architecture

### Port Configuration (50### Scheme)
- **DICOM SCP**: 50104  
- **Web Interface**: 50443 (SSL) / 50080 (HTTP)
- **SSH Server**: 50022
- **HL7 Listener**: 50575
- **Redis**: 50379

### Directory Structure
```
Lethologic Anomia/
├── core/                 # Core system modules
├── services/            # Service implementations  
├── utils/               # Utility functions
├── dicom/               # DICOM-specific modules
├── hl7/                 # HL7 processing
├── web/                 # Web interface assets
├── etc/                 # Sample data (gitignored)
├── generated_dicom/     # Test DICOM output (gitignored)
└── venv_new/           # Virtual environment
```

## Development

### Running in Debug Mode
```bash
./lethologic_anomia.sh --debug
```

### Service Installation
```bash
sudo ./lethologic_anomia.sh --install      # Install as system service
sudo ./lethologic_anomia.sh --uninstall    # Remove system service
```

### Daemon Mode
```bash
./lethologic_anomia.sh --daemon           # Run as background daemon
```

## Troubleshooting

### Common Issues

**"AI loop not available" warning**
- This is normal if AI dependencies (openai, transformers) aren't installed
- The service runs in basic mode without AI features

**Virtual environment issues**
- Ensure you're using Python 3.8+
- Recreate venv: `rm -rf venv_new && python3 -m venv venv_new`

**Permission errors**
- Make lethologic_anomia.sh executable: `chmod +x lethologic_anomia.sh`
- Check file permissions in project directory

**Database connection issues**  
- Ensure SQLite permissions for file-based databases
- Check network connectivity for remote databases

## License

This project is a Python port of a C++ medical imaging migration service.

## Support

For technical support or questions about medical imaging migrations, consult the extended help:
```bash
./lethologic_anomia.sh --help-extended
```
