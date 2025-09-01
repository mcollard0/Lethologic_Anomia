# SSL and SSH Configuration Guide

## Overview

The Migration Service has been configured for secure access with:

- **Web Portal**: SSL-only access with TLS 1.2+ enforcement on port 50443
- **SSH Server**: Secure remote access with AILoop integration on port 50022

## Web Portal SSL Configuration

### SSL Settings

The web portal is configured to use **SSL-only** with the following security settings:

- **Port**: 50443 (HTTPS only)
- **Minimum TLS Version**: 1.2
- **Maximum TLS Version**: 1.3
- **Certificate Path**: `etc/key/certificate.pem`
- **Private Key Path**: `etc/key/private.key`
- **SSL Ciphers**: High-security ciphers only

### Certificate Management

SSL certificates are automatically generated and managed:

```bash
# Generate SSL infrastructure
python -c "from core.ssl_manager import setup_ssl; setup_ssl()"

# Or use the SSL manager directly
python core/ssl_manager.py --setup
```

### Environment Variables

Configure SSL settings via environment variables:

```bash
# SSL Configuration
WEB_SSL_ENABLED=true
WEB_SSL_ONLY=true
WEB_SSL_MIN_VERSION=TLSv1_2
WEB_SSL_MAX_VERSION=TLSv1_3
WEB_SSL_CERT=etc/key/certificate.pem
WEB_SSL_KEY=etc/key/private.key
```

## SSH Server Configuration

### SSH Settings

The SSH server provides secure remote access to the AILoop:

- **Port**: 50022
- **Authentication**: Password and/or Public Key
- **AILoop Integration**: Direct access to AI assistant
- **Session Timeout**: 5 minutes (configurable)

### Authentication Setup

#### 1. Password Authentication

Set the SSH password via environment variable:

```bash
# Set SSH password (required for password auth)
export SSH_PASSWORD="your_secure_password_here"
```

Or add to `.env` file:
```
SSH_PASSWORD=your_secure_password_here
```

#### 2. Public Key Authentication

Generate and configure SSH keys:

```bash
# Generate SSH key pair (client side)
ssh-keygen -t ed25519 -f ~/.ssh/migration_service_key

# Add public key to authorized_keys
mkdir -p etc/key
echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGh..." >> etc/key/authorized_keys
chmod 600 etc/key/authorized_keys
```

#### 3. Environment Variables for SSH

```bash
# SSH Server Configuration
SSH_ENABLED=true
SSH_PORT=50022
SSH_REQUIRE_AUTH=true
SSH_ALLOW_PASSWORD=true
SSH_ALLOW_PUBLIC_KEY=true
SSH_HOST_KEY=etc/key/ssh_host_key
SSH_AUTHORIZED_KEYS=etc/key/authorized_keys

# AILoop Integration
SSH_AILOOP_ENABLED=true
SSH_AILOOP_BANNER="Welcome to Migration Service AI Assistant\nType 'help' for commands or speak naturally\n"
SSH_AILOOP_PROMPT="AI> "

# Connection Settings
SSH_MAX_CONNECTIONS=10
SSH_CONNECTION_TIMEOUT=300
SSH_KEEPALIVE_INTERVAL=60
```

## Service Startup

### Web Server

The web server automatically starts with SSL-only configuration:

```python
from services.web_interface import start_web_server
from core.config import get_settings

settings = get_settings()
await start_web_server(process_manager, settings)
```

### SSH Server

The SSH server requires the `asyncssh` library:

```bash
# Install SSH dependencies
pip install asyncssh

# Start SSH server
from services.ssh_server import start_ssh_server

ssh_server = await start_ssh_server(settings, process_manager)
```

## Usage

### Accessing the Web Portal

```bash
# Access via HTTPS (SSL-only)
https://localhost:50443
```

The web portal will:
- Enforce TLS 1.2 or higher
- Use strong cipher suites
- Automatically redirect any HTTP attempts to HTTPS

### Accessing via SSH

```bash
# Using password authentication
ssh -p 50022 username@localhost

# Using public key authentication  
ssh -p 50022 -i ~/.ssh/migration_service_key username@localhost

# Direct connection with custom port
ssh -o "UserKnownHostsFile=/dev/null" -o "StrictHostKeyChecking=no" -p 50022 user@server
```

Once connected, you'll be directly connected to the AILoop:

```
Welcome to Migration Service AI Assistant
Type 'help' for commands or speak naturally

AI> help
Migration Service Commands:

Basic Commands:
- help                    : Show this help message
- quit                   : Exit the service
- schema                 : Show database schema
...

AI> discovery 192.168.1.100:104
✅ DICOM service discovered at 192.168.1.100:104
AE Title: SAMPLE_SCP
Response Time: 0.045s
Service Type: SCP
```

## Security Features

### Web Portal Security
- **TLS 1.2+ Only**: Older protocols disabled
- **Strong Ciphers**: Weak encryption disabled
- **Auto Certificate Generation**: Self-signed certificates created automatically
- **No HTTP Fallback**: Only HTTPS connections accepted

### SSH Security
- **Host Key Verification**: Automatic host key generation
- **Multiple Auth Methods**: Password and/or public key authentication
- **Connection Limits**: Maximum concurrent connections enforced
- **Session Timeouts**: Automatic disconnection on inactivity
- **Secure Key Storage**: Proper file permissions on keys

## Port Configuration Summary

| Service | Port | Protocol | Description |
|---------|------|----------|-------------|
| Web UI | 50443 | HTTPS | SSL-only web interface |
| SSH | 50022 | SSH | Secure shell with AILoop |
| HL7 | 50575 | TCP | HL7 message processing |
| DICOM SCP | 50104 | TCP | DICOM storage |
| FHIR | 8080 | HTTP | FHIR endpoints |

## Troubleshooting

### SSL Issues

```bash
# Check SSL certificate info
python core/ssl_manager.py --info

# Regenerate certificates
python core/ssl_manager.py --setup --force
```

### SSH Issues

```bash
# Check SSH host key
ls -la etc/key/ssh_host_key*

# Check authorized keys
cat etc/key/authorized_keys

# Test connection
ssh -vvv -p 50022 user@localhost
```

### Dependencies

Make sure required packages are installed:

```bash
pip install fastapi uvicorn cryptography asyncssh pydantic-settings
```

## Environment File Example

Create a `.env` file with your configuration:

```env
# Database
DATABASE_URL=sqlite:///./lethologic_anomia.db

# Web SSL Configuration
WEB_SSL_ENABLED=true
WEB_SSL_ONLY=true
WEB_SSL_MIN_VERSION=TLSv1_2
WEB_SSL_MAX_VERSION=TLSv1_3

# SSH Configuration
SSH_ENABLED=true
SSH_PORT=50022
SSH_PASSWORD=your_secure_password_here
SSH_REQUIRE_AUTH=true
SSH_ALLOW_PASSWORD=true
SSH_ALLOW_PUBLIC_KEY=true

# AI Configuration
XAI_API_KEY=your_xai_key_here
ANTHROPIC_API_KEY=your_anthropic_key_here
OPENAI_API_KEY=your_openai_key_here
```

This configuration ensures secure access to the Migration Service with both web and SSH interfaces properly protected and authenticated.
