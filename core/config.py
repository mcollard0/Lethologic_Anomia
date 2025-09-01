"""
Configuration settings for the Migration Service

Handles all configuration through environment variables and config files.
Equivalent to the C++ configuration management but with Pydantic validation.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Union
from functools import lru_cache

from pydantic import Field, validator
from pydantic_settings import BaseSettings


class DatabaseSettings(BaseSettings):
    """Database configuration settings"""
    
    # Primary database URL (defaults to SQLite)
    database_url: str = Field(
        default="sqlite:///./lethologic_anomia.db",
        env="DATABASE_URL",
        description="Primary database connection URL"
    )
    
    # SQL Server settings
    sql_server_url: Optional[str] = Field(
        default=None,
        env="SQL_SERVER_URL",
        description="SQL Server connection URL"
    )
    
    # Oracle settings  
    oracle_url: Optional[str] = Field(
        default=None,
        env="ORACLE_URL",
        description="Oracle database connection URL"
    )
    
    # MySQL/MariaDB settings
    mysql_url: Optional[str] = Field(
        default=None,
        env="MYSQL_URL", 
        description="MySQL/MariaDB connection URL"
    )
    
    # MongoDB settings
    mongodb_url: Optional[str] = Field(
        default=None,
        env="MONGODB_URL",
        description="MongoDB connection URL"
    )
    
    # Connection pool settings
    pool_size: int = Field(default=20, env="DB_POOL_SIZE")
    max_overflow: int = Field(default=30, env="DB_MAX_OVERFLOW")
    pool_timeout: int = Field(default=30, env="DB_POOL_TIMEOUT")
    pool_recycle: int = Field(default=3600, env="DB_POOL_RECYCLE")


class RedisSettings(BaseSettings):
    """Redis/Valkey configuration"""
    
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        env="REDIS_URL",
        description="Redis/Valkey connection URL"
    )
    
    redis_password: Optional[str] = Field(default=None, env="REDIS_PASSWORD")
    redis_db: int = Field(default=0, env="REDIS_DB")
    redis_timeout: int = Field(default=5, env="REDIS_TIMEOUT")
    
    # Process management
    heartbeat_interval: int = Field(default=300, env="HEARTBEAT_INTERVAL")  # 5 minutes
    process_cleanup_interval: int = Field(default=300, env="PROCESS_CLEANUP_INTERVAL")  # 5 minutes
    lock_timeout: int = Field(default=30, env="LOCK_TIMEOUT")


class DICOMSettings(BaseSettings):
    """DICOM service configuration"""
    
    # SCP (Server) settings
    scp_port: int = Field(default=50104, env="DICOM_SCP_PORT")
    scp_ssl_port: int = Field(default=50112, env="DICOM_SCP_SSL_PORT")
    our_ae_title: str = Field(default="MIGRATION_SCP", env="DICOM_OUR_AE_TITLE")
    
    # Connection settings
    max_pdu: int = Field(default=65536, env="DICOM_MAX_PDU")
    acse_timeout: int = Field(default=30, env="DICOM_ACSE_TIMEOUT")
    dimse_timeout: int = Field(default=30, env="DICOM_DIMSE_TIMEOUT") 
    socket_timeout: int = Field(default=60, env="DICOM_SOCKET_TIMEOUT")
    
    # SSL settings
    ssl_enabled: bool = Field(default=False, env="DICOM_SSL_ENABLED")
    ssl_cert_file: Optional[str] = Field(default=None, env="DICOM_SSL_CERT")
    ssl_key_file: Optional[str] = Field(default=None, env="DICOM_SSL_KEY")
    
    # Storage settings
    storage_directory: str = Field(default="./dicom_storage", env="DICOM_STORAGE_DIR")
    file_extension: str = Field(default="dcm", env="DICOM_FILE_EXT")
    
    # Threading
    max_threads: int = Field(default=10, env="DICOM_MAX_THREADS")


class HL7Settings(BaseSettings):
    """HL7/FHIR configuration"""
    
    # HL7 settings
    hl7_port: int = Field(default=50575, env="HL7_PORT")
    hl7_enabled: bool = Field(default=True, env="HL7_ENABLED")
    
    # FHIR settings  
    fhir_enabled: bool = Field(default=True, env="FHIR_ENABLED")
    fhir_version: str = Field(default="R4", env="FHIR_VERSION")
    
    # Message processing
    input_directory: str = Field(default="./hl7_input", env="HL7_INPUT_DIR")
    output_directory: str = Field(default="./hl7_output", env="HL7_OUTPUT_DIR")
    
    # Passthrough settings
    passthrough_enabled: bool = Field(default=False, env="HL7_PASSTHROUGH_ENABLED")
    passthrough_port: int = Field(default=50576, env="HL7_PASSTHROUGH_PORT")


class AISettings(BaseSettings):
    """AI/ML configuration"""
    
    # API Keys (loaded from environment variables for security)
    # Note: These should NEVER be set in code - always use env vars!
    xai_api_key: Optional[str] = Field(default=None, env="XAI_API_KEY")
    anthropic_api_key: Optional[str] = Field(default=None, env="ANTHROPIC_API_KEY")
    openai_api_key: Optional[str] = Field(default=None, env="OPENAI_API_KEY")
    huggingface_api_key: Optional[str] = Field(default=None, env="HUGGINGFACE_API_KEY")
    
    # Provider priorities (1=highest priority)
    # Local HuggingFace first (free), then XAI, Anthropic, OpenAI, finally HF API (paid)
    ai_providers: List[str] = Field(
        default=["huggingface_local", "xai", "anthropic", "openai", "huggingface_api"],
        env="AI_PROVIDERS",
        description="AI provider priority order - local first, paid APIs last"
    )
    
    # Model selection
    default_model: str = Field(default="microsoft/DialoGPT-large", env="AI_DEFAULT_MODEL")
    local_model: str = Field(default="microsoft/DialoGPT-large", env="AI_LOCAL_MODEL")
    
    # Provider-specific models
    huggingface_model: str = Field(default="microsoft/DialoGPT-large", env="HUGGINGFACE_MODEL")
    xai_model: str = Field(default="grok-beta", env="XAI_MODEL")
    anthropic_model: str = Field(default="claude-3-haiku-20240307", env="ANTHROPIC_MODEL")
    openai_model: str = Field(default="gpt-3.5-turbo", env="OPENAI_MODEL")
    
    # API endpoints
    xai_base_url: str = Field(default="https://api.x.ai/v1", env="XAI_BASE_URL")
    huggingface_base_url: str = Field(default="https://api-inference.huggingface.co", env="HF_BASE_URL")
    
    # Speech settings
    speech_enabled: bool = Field(default=False, env="SPEECH_ENABLED")
    tts_engine: str = Field(default="pyttsx3", env="TTS_ENGINE")
    stt_engine: str = Field(default="whisper", env="STT_ENGINE")
    
    # Languages
    supported_languages: List[str] = Field(
        default=["en", "la"],  # English and Latin
        env="SUPPORTED_LANGUAGES"
    )
    
    # Trust and moderation
    initial_trust_level: int = Field(default=5, env="AI_INITIAL_TRUST")
    max_trust_level: int = Field(default=20, env="AI_MAX_TRUST")
    moderation_enabled: bool = Field(default=True, env="AI_MODERATION_ENABLED")


class WebSettings(BaseSettings):
    """Web interface configuration"""
    
    web_interface_enabled: bool = Field(default=True, env="WEB_INTERFACE_ENABLED")
    web_port: int = Field(default=50443, env="WEB_PORT")
    
    # SSL settings - ENFORCED SSL-only, no HTTP fallback
    ssl_enabled: bool = Field(default=True, env="WEB_SSL_ENABLED")
    ssl_only: bool = Field(default=True, env="WEB_SSL_ONLY")  # Force SSL-only
    ssl_certfile: Optional[str] = Field(default="etc/key/certificate.pem", env="WEB_SSL_CERT")
    ssl_keyfile: Optional[str] = Field(default="etc/key/private.key", env="WEB_SSL_KEY")
    ssl_min_version: str = Field(default="TLSv1_2", env="WEB_SSL_MIN_VERSION")  # Minimum TLS 1.2
    ssl_max_version: str = Field(default="TLSv1_3", env="WEB_SSL_MAX_VERSION")  # Allow up to TLS 1.3
    ssl_ciphers: Optional[str] = Field(default=None, env="WEB_SSL_CIPHERS")  # Use system defaults unless specified
    
    # Session settings
    secret_key: str = Field(default="change-me-in-production", env="WEB_SECRET_KEY")
    session_timeout: int = Field(default=3600, env="WEB_SESSION_TIMEOUT")  # 1 hour


class SSHSettings(BaseSettings):
    """SSH server configuration"""
    
    ssh_enabled: bool = Field(default=True, env="SSH_ENABLED")
    ssh_port: int = Field(default=50022, env="SSH_PORT")
    ssh_host_key: Optional[str] = Field(default="etc/key/ssh_host_key", env="SSH_HOST_KEY")
    ssh_host_key_type: str = Field(default="rsa", env="SSH_HOST_KEY_TYPE")  # rsa, ed25519
    
    # Authentication settings
    ssh_password: Optional[str] = Field(default=None, env="SSH_PASSWORD")
    ssh_authorized_keys: Optional[str] = Field(default="etc/key/authorized_keys", env="SSH_AUTHORIZED_KEYS")
    ssh_require_auth: bool = Field(default=True, env="SSH_REQUIRE_AUTH")
    ssh_allow_password: bool = Field(default=True, env="SSH_ALLOW_PASSWORD")
    ssh_allow_public_key: bool = Field(default=True, env="SSH_ALLOW_PUBLIC_KEY")
    
    # AILoop integration
    ailoop_enabled: bool = Field(default=True, env="SSH_AILOOP_ENABLED")
    ailoop_banner: str = Field(
        default="Welcome to Migration Service AI Assistant\nType 'help' for commands or speak naturally\n",
        env="SSH_AILOOP_BANNER"
    )
    ailoop_prompt: str = Field(default="AI> ", env="SSH_AILOOP_PROMPT")
    
    # Connection settings
    max_connections: int = Field(default=10, env="SSH_MAX_CONNECTIONS")
    connection_timeout: int = Field(default=300, env="SSH_CONNECTION_TIMEOUT")  # 5 minutes
    keepalive_interval: int = Field(default=60, env="SSH_KEEPALIVE_INTERVAL")  # 1 minute


class Settings(BaseSettings):
    """Main application settings"""
    
    # Application info
    app_name: str = "Migration Service"
    version: str = "1.0.0"
    description: str = "DICOM/HL7 Medical Image Data Migration Service with AI"
    
    # Environment
    debug: bool = Field(default=False, env="DEBUG")
    testing: bool = Field(default=False, env="TESTING")
    environment: str = Field(default="production", env="ENVIRONMENT")
    
    # Logging
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_file: Optional[str] = Field(default=None, env="LOG_FILE")
    
    # Directories
    base_directory: Path = Field(default=Path.cwd(), env="BASE_DIR")
    config_directory: Path = Field(default=Path.cwd() / "config", env="CONFIG_DIR")
    data_directory: Path = Field(default=Path.cwd() / "data", env="DATA_DIR")
    
    # Nested settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings) 
    dicom: DICOMSettings = Field(default_factory=DICOMSettings)
    hl7: HL7Settings = Field(default_factory=HL7Settings)
    ai: AISettings = Field(default_factory=AISettings)
    web: WebSettings = Field(default_factory=WebSettings)
    ssh: SSHSettings = Field(default_factory=SSHSettings)
    
    # Legacy compatibility properties for easier access
    @property
    def database_url(self) -> str:
        return self.database.database_url
    
    @property  
    def redis_url(self) -> str:
        return self.redis.redis_url
        
    @property
    def web_interface_enabled(self) -> bool:
        return self.web.web_interface_enabled
        
    @property
    def web_port(self) -> int:
        return self.web.web_port
        
    @property
    def ssl_enabled(self) -> bool:
        return self.web.ssl_enabled
        
    @property
    def ssl_certfile(self) -> Optional[str]:
        return self.web.ssl_certfile
        
    @property
    def ssl_keyfile(self) -> Optional[str]:
        return self.web.ssl_keyfile
        
    @property
    def ssh_enabled(self) -> bool:
        return self.ssh.ssh_enabled
        
    @property
    def ssh_port(self) -> int:
        return self.ssh.ssh_port
    
    @validator('base_directory', 'config_directory', 'data_directory', pre=True)
    def ensure_path(cls, v):
        if isinstance(v, str):
            return Path(v)
        return v
    
    def model_post_init(self, __context) -> None:
        """Post-initialization setup"""
        # Create directories if they don't exist
        for directory in [self.config_directory, self.data_directory]:
            directory.mkdir(parents=True, exist_ok=True)
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8" 
        case_sensitive = False
        extra = "ignore"  # Ignore extra environment variables


@lru_cache()
def get_settings(config_file: Optional[str] = None) -> Settings:
    """
    Get application settings with caching.
    
    Args:
        config_file: Optional path to configuration file
        
    Returns:
        Settings instance
    """
    if config_file and os.path.exists(config_file):
        # Load from specific config file
        return Settings(_env_file=config_file)
    else:
        # Load from environment and default .env
        return Settings()


# Export commonly used settings for easy import
__all__ = [
    "Settings",
    "DatabaseSettings", 
    "RedisSettings",
    "DICOMSettings",
    "HL7Settings", 
    "AISettings",
    "WebSettings",
    "SSHSettings",
    "get_settings"
]
