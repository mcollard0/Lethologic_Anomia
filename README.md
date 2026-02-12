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
   python3 -m venv venv
   source venv/bin/activate  # Linux/Mac
   # or
   venv\Scripts\activate     # Windows
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
source venv/bin/activate && python lethologic_anomia.py --help
```

**Method 3: Using virtual environment Python directly**
```bash
./venv/bin/python lethologic_anomia.py --help
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

## AI Capabilities

Lethologic Anomia features a sophisticated AI engine designed for autonomous operation and natural language interaction.

### Multi-Provider Support
The system supports multiple AI backends with configurable priority:

1.  **OpenAI**: GPT-3.5/GPT-4 for high-reasoning tasks.
2.  **Anthropic**: Claude 3 (Opus/Sonnet/Haiku) for complex analysis and tool use.
3.  **XAI**: Grok via XAI API.
4.  **Local HuggingFace**: Runs offline using `Mistral-7B-Instruct` (primary) or `DialoGPT` (fallback). Automatically optimizes for available RAM/VRAM (FP16, INT8, or disk offload).

### Speech Interface
Integrated voice capabilities enable hands-free operation:
-   **Speech-TO-Text (STT)**: Uses OpenAI's **Whisper** model (local or API) for high-accuracy command transcription.
-   **Text-To-Speech (TTS)**: Uses `pyttsx3` or `gTTS` to provide vocal feedback and status updates.

### Medical Image Analysis
Advanced AI-powered analysis of medical imaging data:
-   **Anomaly Detection**: Identifies potential abnormalities using statistical and edge-detection algorithms.
-   **Classification**: Includes pre-trained models for Chest X-ray pathology (Swin Transformer).
-   **DICOM Integration**: Direct analysis of DICOM files with automatic windowing and metadata extraction.
-   **Standardization**: Automatic normalization and preprocessing for consistent analysis.

### Autonomous Agency
The AI operates with a dynamic **Trust & Aggression** system:
-   **Trust Level (-127 to 127)**: Determines permission to execute sensitive actions (e.g., database writes, service restarts).
    -   *Low Trust*: Read-only access (queries, status checks).
    -   *High Trust*: Full autonomous control (migrations, configuration changes).
-   **Aggression Level (-127 to 127)**: Influences the AI's initiative and personality.

### Natural Language Control
Control the entire system using natural language commands:

```text
"Start the DICOM SCP on port 11112"
"Create a new user named 'admin' with password 'secure123'"
"Migrate all CT studies from Site A to Site B"
"What is the system status?"
```

## Configuration

### Environment Variables
```bash
export DATABASE_URL="sqlite:///migration.db"
export REDIS_URL="redis://localhost:6379"

# AI Configuration
export AI_PROVIDERS="openai,anthropic,xai,huggingface_local" # Priority order
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export XAI_API_KEY="key..."
export HUGGINGFACE_API_KEY="hf_..."           # Optional for HF API

export WEB_PORT="50443"                       # Web interface port
export SSH_PORT="50022"                       # SSH server port
```

### CLI Model Management
You can manage AI settings directly from the CLI:

```bash
# List available models
python lethologic_anomia.py --list-models

# Set active model
python lethologic_anomia.py --set-model "anthropic/claude-3-sonnet"

# Adjust autonomy parameters
python lethologic_anomia.py --set-trust 10 --set-aggression 5
```

### Configuration File
Create a `config.json` file:
```json
{
  "database_url": "sqlite:///migration.db",
  "redis_url": "redis://localhost:6379",
  "ai": {
    "providers": ["openai", "anthropic"],
    "trust_level": 5,
    "voice_enabled": true
  },
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
├── core/                 # Core system modules (AI Loop, Process Manager)
├── services/            # Service implementations (DICOM, HL7, Web, SSH)
├── utils/               # Utility functions
├── dicom/               # DICOM-specific modules
├── hl7/                 # HL7 processing
├── web/                 # Web interface assets
├── etc/                 # Sample data (gitignored)
├── generated_dicom/     # Test DICOM output (gitignored)
└── venv/               # Virtual environment
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
- This indicates the system is running in **Basic Mode**.
- The service is fully functional for DICOM/HL7 migration but lacks voice/text intelligence.
- To enable AI: Install dependencies (`pip install -r requirements.txt`) and configure API keys.

**Virtual environment issues**
- Ensure you're using Python 3.8+
- Recreate venv: `rm -rf venv && python3 -m venv venv`

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
