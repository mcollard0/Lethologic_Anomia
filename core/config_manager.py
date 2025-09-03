"""
Database Configuration Manager

Manages service configurations stored in the database with fallback to code defaults.
Provides a centralized way to configure all services dynamically.
"""

import json
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass

from .database import DatabaseManager
from .custom_logging import get_logger

logger = get_logger(__name__)


@dataclass
class ConfigItem:
    """Configuration item"""
    service: str
    name: str
    value: Any
    description: Optional[str] = None
    value_type: str = "string"  # string, integer, boolean, json


class DatabaseConfigManager:
    """
    Database-backed configuration manager
    
    Manages service configurations stored in database with intelligent fallbacks.
    Supports hierarchical configuration lookup and type conversion.
    """
    
    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize config manager
        
        Args:
            db_manager: Database manager instance
        """
        self.db_manager = db_manager
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_dirty = True
        
    async def initialize(self) -> None:
        """Initialize the config manager and create tables"""
        try:
            # Tables are already created by SQLAlchemy in DatabaseManager.initialize()
            await self._populate_default_configs()
            await self._load_cache()
            logger.info("Database config manager initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize config manager: {e}")
            raise
    
    async def _populate_default_configs(self) -> None:
        """Populate default configurations for all services"""
        default_configs = [
            # DICOM SCP Configuration
            ConfigItem("dicom_scp", "port", "50104", "Default DICOM SCP port", "integer"),
            ConfigItem("dicom_scp", "ssl_port", "50112", "DICOM SCP SSL port", "integer"),
            ConfigItem("dicom_scp", "ae_title", "LETHOLOGIC_SCP", "Application Entity title for SCP", "string"),
            ConfigItem("dicom_scp", "max_pdu", "16384", "Maximum PDU size for DICOM", "integer"),
            ConfigItem("dicom_scp", "acse_timeout", "30", "ACSE timeout in seconds", "integer"),
            ConfigItem("dicom_scp", "dimse_timeout", "30", "DIMSE timeout in seconds", "integer"),
            ConfigItem("dicom_scp", "socket_timeout", "60", "Socket timeout in seconds", "integer"),
            ConfigItem("dicom_scp", "storage_directory", "/tmp/dicom_storage", "Directory for DICOM storage", "string"),
            ConfigItem("dicom_scp", "auto_start", "true", "Auto-start DICOM SCP service", "boolean"),
            ConfigItem("dicom_scp", "ssl_enabled", "false", "Enable SSL for DICOM SCP", "boolean"),
            ConfigItem("dicom_scp", "ssl_cert_file", "/etc/ssl/certs/dicom.crt", "SSL certificate file", "string"),
            ConfigItem("dicom_scp", "ssl_key_file", "/etc/ssl/private/dicom.key", "SSL private key file", "string"),
            
            # DICOM SCU Configuration
            ConfigItem("dicom_scu", "ae_title", "LETHOLOGIC_SCU", "Application Entity title for SCU", "string"),
            ConfigItem("dicom_scu", "timeout", "30", "Default SCU timeout", "integer"),
            ConfigItem("dicom_scu", "max_associations", "10", "Maximum concurrent associations", "integer"),
            
            # Web Interface Configuration
            ConfigItem("web_interface", "port", "8080", "Web interface HTTP port", "integer"),
            ConfigItem("web_interface", "ssl_port", "8443", "Web interface HTTPS port", "integer"),
            ConfigItem("web_interface", "host", "0.0.0.0", "Web interface bind host", "string"),
            ConfigItem("web_interface", "enabled", "true", "Enable web interface", "boolean"),
            ConfigItem("web_interface", "ssl_enabled", "false", "Enable HTTPS", "boolean"),
            ConfigItem("web_interface", "ssl_cert_file", "/etc/ssl/certs/web.crt", "HTTPS certificate file", "string"),
            ConfigItem("web_interface", "ssl_key_file", "/etc/ssl/private/web.key", "HTTPS private key file", "string"),
            ConfigItem("web_interface", "max_upload_size", "104857600", "Max upload size in bytes (100MB)", "integer"),
            
            # SSH Server Configuration
            ConfigItem("ssh_server", "port", "2222", "SSH server port", "integer"),
            ConfigItem("ssh_server", "host", "0.0.0.0", "SSH server bind host", "string"),
            ConfigItem("ssh_server", "enabled", "true", "Enable SSH server", "boolean"),
            ConfigItem("ssh_server", "host_key_file", "/etc/ssh/ssh_host_rsa_key", "SSH host key file", "string"),
            ConfigItem("ssh_server", "max_connections", "10", "Maximum SSH connections", "integer"),
            ConfigItem("ssh_server", "timeout", "300", "SSH session timeout in seconds", "integer"),
            
            # HL7/FHIR Configuration
            ConfigItem("hl7_listener", "port", "7777", "HL7 listener port", "integer"),
            ConfigItem("hl7_listener", "host", "0.0.0.0", "HL7 listener bind host", "string"),
            ConfigItem("hl7_listener", "enabled", "true", "Enable HL7 listener", "boolean"),
            ConfigItem("hl7_listener", "max_connections", "50", "Maximum HL7 connections", "integer"),
            ConfigItem("hl7_listener", "message_timeout", "30", "HL7 message timeout in seconds", "integer"),
            
            # AI Processor Configuration
            ConfigItem("ai_processor", "model_name", "gpt-3.5-turbo", "Default AI model", "string"),
            ConfigItem("ai_processor", "max_tokens", "4096", "Maximum tokens per request", "integer"),
            ConfigItem("ai_processor", "temperature", "0.7", "AI model temperature", "string"),
            ConfigItem("ai_processor", "enabled", "false", "Enable AI processor", "boolean"),
            
            # Redis Configuration
            ConfigItem("redis", "host", "localhost", "Redis server host", "string"),
            ConfigItem("redis", "port", "6379", "Redis server port", "integer"),
            ConfigItem("redis", "db", "0", "Redis database number", "integer"),
            ConfigItem("redis", "password", "", "Redis password (empty for no auth)", "string"),
            ConfigItem("redis", "heartbeat_interval", "30", "Heartbeat interval in seconds", "integer"),
            
            # Database Configuration
            ConfigItem("database", "path", "lethologic_anomia.db", "SQLite database path", "string"),
            ConfigItem("database", "pool_size", "10", "Database connection pool size", "integer"),
            ConfigItem("database", "timeout", "30", "Database query timeout", "integer"),
            
            # Logging Configuration  
            ConfigItem("logging", "level", "INFO", "Log level", "string"),
            ConfigItem("logging", "file", "migration_service.log", "Log file path", "string"),
            ConfigItem("logging", "max_file_size", "10485760", "Max log file size (10MB)", "integer"),
            ConfigItem("logging", "backup_count", "5", "Number of log backup files", "integer"),
        ]
        
        # Insert default configs (ignore if already exist)
        for config_item in default_configs:
            try:
                await self.db_manager.execute_query(
                    """
                    INSERT OR IGNORE INTO config 
                    (service, name, value, description, value_type, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (
                        config_item.service,
                        config_item.name,
                        str(config_item.value),
                        config_item.description,
                        config_item.value_type
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to insert default config {config_item.service}.{config_item.name}: {e}")
        
        logger.info(f"Populated {len(default_configs)} default configuration items")
    
    async def _load_cache(self) -> None:
        """Load all configurations into cache"""
        try:
            result = await self.db_manager.execute_query(
                "SELECT service, name, value, value_type FROM config ORDER BY service, name"
            )
            
            self._cache = {}
            for row in result:
                service = row['service']
                name = row['name']
                value = self._convert_value(row['value'], row['value_type'])
                
                if service not in self._cache:
                    self._cache[service] = {}
                
                self._cache[service][name] = value
            
            self._cache_dirty = False
            logger.debug(f"Loaded {len(result)} config items into cache")
            
        except Exception as e:
            logger.error(f"Failed to load config cache: {e}")
            self._cache = {}
    
    def _convert_value(self, value: str, value_type: str) -> Any:
        """Convert string value to appropriate type"""
        try:
            if value_type == "integer":
                return int(value)
            elif value_type == "boolean":
                return value.lower() in ("true", "1", "yes", "on")
            elif value_type == "json":
                return json.loads(value)
            else:  # string or unknown
                return value
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to convert config value '{value}' to {value_type}: {e}")
            return value
    
    async def get_service_config(
        self, 
        service: str, 
        fallback_settings: Optional[object] = None
    ) -> Dict[str, Any]:
        """
        Get all configuration for a service
        
        Args:
            service: Service name (e.g., 'dicom_scp', 'web_interface')
            fallback_settings: Settings object to use for fallback values
            
        Returns:
            Dictionary of configuration values
        """
        try:
            # Reload cache if dirty
            if self._cache_dirty:
                await self._load_cache()
            
            # Get config from cache
            service_config = self._cache.get(service, {})
            
            # If fallback settings provided, merge with missing values
            if fallback_settings and hasattr(fallback_settings, service):
                fallback_config = getattr(fallback_settings, service)
                if fallback_config:
                    # Add any missing config from settings
                    for attr_name in dir(fallback_config):
                        if not attr_name.startswith('_') and attr_name not in service_config:
                            value = getattr(fallback_config, attr_name)
                            if not callable(value):
                                service_config[attr_name] = value
            
            return service_config
            
        except Exception as e:
            logger.error(f"Failed to get service config for {service}: {e}")
            return {}
    
    async def get_config_value(
        self, 
        service: str, 
        name: str, 
        default: Any = None,
        fallback_settings: Optional[object] = None
    ) -> Any:
        """
        Get a specific configuration value
        
        Args:
            service: Service name
            name: Config parameter name
            default: Default value if not found
            fallback_settings: Settings object for fallback
            
        Returns:
            Configuration value
        """
        try:
            # Reload cache if dirty
            if self._cache_dirty:
                await self._load_cache()
            
            # Check cache first
            if service in self._cache and name in self._cache[service]:
                return self._cache[service][name]
            
            # Check fallback settings
            if fallback_settings and hasattr(fallback_settings, service):
                service_settings = getattr(fallback_settings, service)
                if service_settings and hasattr(service_settings, name):
                    value = getattr(service_settings, name)
                    if not callable(value):
                        return value
            
            # Return default
            return default
            
        except Exception as e:
            logger.error(f"Failed to get config value {service}.{name}: {e}")
            return default
    
    async def set_config_value(
        self,
        service: str,
        name: str,
        value: Any,
        description: Optional[str] = None,
        value_type: Optional[str] = None
    ) -> bool:
        """
        Set a configuration value
        
        Args:
            service: Service name
            name: Config parameter name
            value: Value to set
            description: Optional description
            value_type: Value type (string, integer, boolean, json)
            
        Returns:
            True if successful
        """
        try:
            # Determine value type if not provided
            if value_type is None:
                if isinstance(value, bool):
                    value_type = "boolean"
                elif isinstance(value, int):
                    value_type = "integer"
                elif isinstance(value, (dict, list)):
                    value_type = "json"
                else:
                    value_type = "string"
            
            # Convert value to string for database storage
            if value_type == "json":
                value_str = json.dumps(value)
            elif value_type == "boolean":
                value_str = "true" if value else "false"
            else:
                value_str = str(value)
            
            # Update database
            await self.db_manager.execute_query(
                """
                INSERT OR REPLACE INTO config 
                (service, name, value, description, value_type, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (service, name, value_str, description, value_type)
            )
            
            # Update cache
            if service not in self._cache:
                self._cache[service] = {}
            self._cache[service][name] = value
            
            logger.info(f"Set config {service}.{name} = {value}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set config {service}.{name}: {e}")
            return False
    
    async def delete_config_value(self, service: str, name: str) -> bool:
        """
        Delete a configuration value
        
        Args:
            service: Service name
            name: Config parameter name
            
        Returns:
            True if successful
        """
        try:
            await self.db_manager.execute_query(
                "DELETE FROM config WHERE service = ? AND name = ?",
                (service, name)
            )
            
            # Update cache
            if service in self._cache and name in self._cache[service]:
                del self._cache[service][name]
            
            logger.info(f"Deleted config {service}.{name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete config {service}.{name}: {e}")
            return False
    
    async def get_all_service_configs(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all service configurations
        
        Returns:
            Dictionary mapping service names to their configs
        """
        try:
            if self._cache_dirty:
                await self._load_cache()
            
            return self._cache.copy()
            
        except Exception as e:
            logger.error(f"Failed to get all service configs: {e}")
            return {}
    
    async def list_services(self) -> List[str]:
        """
        List all configured services
        
        Returns:
            List of service names
        """
        try:
            result = await self.db_manager.execute_query(
                "SELECT DISTINCT service FROM config ORDER BY service"
            )
            
            return [row['service'] for row in result]
            
        except Exception as e:
            logger.error(f"Failed to list services: {e}")
            return []
    
    async def export_config(self, service: Optional[str] = None) -> Dict[str, Any]:
        """
        Export configuration as JSON
        
        Args:
            service: Specific service to export or None for all
            
        Returns:
            Configuration data
        """
        try:
            if service:
                query = "SELECT * FROM config WHERE service = ? ORDER BY name"
                params = (service,)
            else:
                query = "SELECT * FROM config ORDER BY service, name"
                params = ()
            
            result = await self.db_manager.execute_query(query, params)
            
            export_data = {}
            for row in result:
                service_name = row['service']
                if service_name not in export_data:
                    export_data[service_name] = {}
                
                export_data[service_name][row['name']] = {
                    'value': self._convert_value(row['value'], row['value_type']),
                    'description': row['description'],
                    'value_type': row['value_type'],
                    'updated_at': row['updated_at']
                }
            
            return export_data
            
        except Exception as e:
            logger.error(f"Failed to export config: {e}")
            return {}
    
    async def import_config(self, config_data: Dict[str, Any]) -> bool:
        """
        Import configuration from JSON data
        
        Args:
            config_data: Configuration data to import
            
        Returns:
            True if successful
        """
        try:
            imported_count = 0
            
            for service_name, service_config in config_data.items():
                for config_name, config_info in service_config.items():
                    if isinstance(config_info, dict) and 'value' in config_info:
                        # Full config format with metadata
                        value = config_info['value']
                        description = config_info.get('description')
                        value_type = config_info.get('value_type', 'string')
                    else:
                        # Simple value format
                        value = config_info
                        description = None
                        value_type = None
                    
                    success = await self.set_config_value(
                        service_name, config_name, value, description, value_type
                    )
                    
                    if success:
                        imported_count += 1
            
            logger.info(f"Imported {imported_count} configuration items")
            return True
            
        except Exception as e:
            logger.error(f"Failed to import config: {e}")
            return False
    
    def invalidate_cache(self) -> None:
        """Mark cache as dirty to force reload"""
        self._cache_dirty = True
        logger.debug("Config cache invalidated")
    
    # Convenience methods for testing and compatibility
    async def get_config(self, name: str, default: Any = None) -> Any:
        """Get configuration by full name (service.config_name format)"""
        if '.' in name:
            service, config_name = name.split('.', 1)
            return await self.get_config_value(service, config_name, default)
        else:
            # Legacy support - assume global config
            return await self.get_config_value("global", name, default)
    
    async def set_config(self, name: str, value: Any, description: Optional[str] = None) -> bool:
        """Set configuration by full name (service.config_name format)"""
        if '.' in name:
            service, config_name = name.split('.', 1)
            return await self.set_config_value(service, config_name, value, description)
        else:
            # Legacy support - assume global config
            return await self.set_config_value("global", name, value, description)
    
    async def get_service_config_value(self, service: str, config_name: str, default: Any = None) -> Any:
        """Get a specific service configuration value"""
        return await self.get_config_value(service, config_name, default)
    
    async def set_service_config_value(self, service: str, config_name: str, value: Any) -> bool:
        """Set a specific service configuration value"""
        return await self.set_config_value(service, config_name, value)
    
    async def list_all_configs(self) -> List[Dict[str, Any]]:
        """List all configuration entries"""
        try:
            result = await self.db_manager.execute_query(
                "SELECT service, name, value, description, value_type, updated_at FROM config ORDER BY service, name"
            )
            
            # Convert to list format expected by the test
            configs = []
            for row in result:
                configs.append({
                    'name': f"{row['service']}.{row['name']}",
                    'value': self._convert_value(row['value'], row['value_type']),
                    'service': row['service'],
                    'config_name': row['name'],
                    'description': row['description'],
                    'value_type': row['value_type'],
                    'updated_at': row['updated_at']
                })
            
            return configs
            
        except Exception as e:
            logger.error(f"Failed to list all configs: {e}")
            return []
    
    # Convenience methods for specific services
    async def get_dicom_scp_config(self, fallback_settings: Optional[object] = None) -> Dict[str, Any]:
        """Get DICOM SCP configuration"""
        return await self.get_service_config_dict("dicom_scp", fallback_settings)
    
    async def get_web_interface_config(self, fallback_settings: Optional[object] = None) -> Dict[str, Any]:
        """Get web interface configuration"""
        return await self.get_service_config_dict("web_interface", fallback_settings)
    
    async def get_ssh_server_config(self, fallback_settings: Optional[object] = None) -> Dict[str, Any]:
        """Get SSH server configuration"""
        return await self.get_service_config_dict("ssh_server", fallback_settings)
    
    async def get_hl7_listener_config(self, fallback_settings: Optional[object] = None) -> Dict[str, Any]:
        """Get HL7 listener configuration"""
        return await self.get_service_config_dict("hl7_listener", fallback_settings)
    
    async def get_service_config_dict(
        self, 
        service: str, 
        fallback_settings: Optional[object] = None
    ) -> Dict[str, Any]:
        """
        Get all configuration for a service as a dictionary
        
        Args:
            service: Service name (e.g., 'dicom_scp', 'web_interface')
            fallback_settings: Settings object to use for fallback values
            
        Returns:
            Dictionary of configuration values
        """
        try:
            # Reload cache if dirty
            if self._cache_dirty:
                await self._load_cache()
            
            # Get config from cache
            service_config = self._cache.get(service, {})
            
            # If fallback settings provided, merge with missing values
            if fallback_settings and hasattr(fallback_settings, service):
                fallback_config = getattr(fallback_settings, service)
                if fallback_config:
                    # Add any missing config from settings
                    for attr_name in dir(fallback_config):
                        if not attr_name.startswith('_') and attr_name not in service_config:
                            value = getattr(fallback_config, attr_name)
                            if not callable(value):
                                service_config[attr_name] = value
            
            return service_config
            
        except Exception as e:
            logger.error(f"Failed to get service config for {service}: {e}")
            return {}
