"""
Service Manager for Lethologic Anomia

Manages the lifecycle of system services, including auto-start, configuration,
and status monitoring based on the service table in the database.
"""

import asyncio
import json
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime

from .database import DatabaseManager
from .logging import get_logger
from .config import Settings

logger = get_logger(__name__)


class ServiceManager:
    """
    Manages system services based on database configuration
    """
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        self.db_manager = db_manager
        self.settings = settings
        self.running_services: Dict[str, Any] = {}
        self.service_handlers: Dict[str, Callable] = {}
        
    async def initialize(self) -> None:
        """Initialize the service manager and create default service entries"""
        logger.info("Initializing service manager...")
        
        # Create default service configurations if they don't exist
        await self._create_default_services()
        
        logger.info("Service manager initialized")
    
    async def _create_default_services(self) -> None:
        """Create default service configurations in the database"""
        default_services = [
            {
                'service_name': 'Web Server',
                'enabled': True,
                'auto_start': True,
                'singleton': True,
                'ports': '50443',
                'description': 'FastAPI web interface with SSL support',
                'settings_json': json.dumps({
                    'ssl_enabled': True,
                    'host': '0.0.0.0'
                })
            },
            {
                'service_name': 'SSH Server',
                'enabled': True,
                'auto_start': True,
                'singleton': True,
                'ports': '50022',
                'description': 'SSH server with AI loop integration',
                'settings_json': json.dumps({
                    'allow_password': True,
                    'allow_public_key': True,
                    'require_auth': True
                })
            },
            {
                'service_name': 'DICOM SCP',
                'enabled': True,
                'auto_start': False,
                'singleton': False,
                'ports': '104,11112',
                'description': 'DICOM Service Class Provider',
                'settings_json': json.dumps({
                    'ae_title': 'LETHOLOGIC',
                    'max_pdu': 16384,
                    'storage_directory': './dicom_store'
                })
            },
            {
                'service_name': 'DICOM Router',
                'enabled': True,
                'auto_start': False,
                'singleton': True,
                'ports': '11113',
                'description': 'DICOM routing and forwarding service',
                'settings_json': json.dumps({
                    'ae_title': 'ROUTER',
                    'routing_rules': []
                })
            },
            {
                'service_name': 'HL7 Server',
                'enabled': True,
                'auto_start': False,
                'singleton': False,
                'ports': '2575,2576',
                'description': 'HL7 message processing server',
                'settings_json': json.dumps({
                    'mllp_enabled': True,
                    'ack_timeout': 30
                })
            },
            {
                'service_name': 'FHIR Server',
                'enabled': True,
                'auto_start': False,
                'singleton': True,
                'ports': '8080',
                'description': 'FHIR R4 compliant server',
                'settings_json': json.dumps({
                    'version': 'R4',
                    'validation_enabled': True
                })
            }
        ]
        
        for service_config in default_services:
            # Check if service already exists
            existing = await self.db_manager.get_service(service_config['service_name'])
            if not existing:
                await self.db_manager.create_or_update_service(**service_config)
                logger.info(f"Created default service configuration: {service_config['service_name']}")
    
    def register_service_handler(self, service_name: str, handler: Callable) -> None:
        """Register a handler function for a service"""
        self.service_handlers[service_name] = handler
        logger.info(f"Registered handler for service: {service_name}")
    
    async def start_auto_start_services(self) -> None:
        """Start all services marked for auto-start"""
        logger.info("Starting auto-start services...")
        
        auto_start_services = await self.db_manager.get_auto_start_services()
        
        for service_config in auto_start_services:
            service_name = service_config['service_name']
            try:
                success = await self.start_service(service_name, service_config)
                if success:
                    logger.info(f"✅ Auto-started service: {service_name}")
                else:
                    logger.warning(f"❌ Failed to auto-start service: {service_name}")
            except Exception as e:
                logger.error(f"Error auto-starting service {service_name}: {e}")
                await self.db_manager.update_service_status(service_name, 'error')
    
    async def start_service(self, service_name: str, service_config: Optional[Dict] = None) -> bool:
        """Start a specific service"""
        try:
            if not service_config:
                service_config = await self.db_manager.get_service(service_name)
                if not service_config:
                    logger.error(f"Service not found: {service_name}")
                    return False
            
            if not service_config.get('enabled', False):
                logger.warning(f"Service is disabled: {service_name}")
                return False
            
            # Check if singleton service is already running
            if service_config.get('singleton', True) and service_name in self.running_services:
                logger.warning(f"Singleton service already running: {service_name}")
                return False
            
            # Parse ports
            ports = self._parse_ports(service_config.get('ports', ''))
            
            # Parse settings
            settings = {}
            if service_config.get('settings_json'):
                try:
                    settings = json.loads(service_config['settings_json'])
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON settings for {service_name}: {e}")
            
            # Update status to starting
            await self.db_manager.update_service_status(service_name, 'starting')
            
            # Call service handler if registered
            if service_name in self.service_handlers:
                handler = self.service_handlers[service_name]
                result = await handler(service_config, ports, settings)
                
                if result:
                    self.running_services[service_name] = {
                        'config': service_config,
                        'ports': ports,
                        'settings': settings,
                        'started_at': datetime.now(),
                        'instance': result
                    }
                    await self.db_manager.update_service_status(service_name, 'running')
                    return True
                else:
                    await self.db_manager.update_service_status(service_name, 'error')
                    return False
            else:
                logger.warning(f"No handler registered for service: {service_name}")
                await self.db_manager.update_service_status(service_name, 'error')
                return False
            
        except Exception as e:
            logger.error(f"Error starting service {service_name}: {e}")
            await self.db_manager.update_service_status(service_name, 'error')
            return False
    
    async def stop_service(self, service_name: str) -> bool:
        """Stop a specific service"""
        try:
            if service_name not in self.running_services:
                logger.warning(f"Service not running: {service_name}")
                return False
            
            service_info = self.running_services[service_name]
            instance = service_info.get('instance')
            
            # Update status to stopping
            await self.db_manager.update_service_status(service_name, 'stopping')
            
            # Stop the service instance
            if instance and hasattr(instance, 'stop'):
                await instance.stop()
            
            # Remove from running services
            del self.running_services[service_name]
            
            await self.db_manager.update_service_status(service_name, 'stopped')
            logger.info(f"Service stopped: {service_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping service {service_name}: {e}")
            await self.db_manager.update_service_status(service_name, 'error')
            return False
    
    async def restart_service(self, service_name: str) -> bool:
        """Restart a specific service"""
        logger.info(f"Restarting service: {service_name}")
        
        # Stop the service if running
        if service_name in self.running_services:
            await self.stop_service(service_name)
        
        # Wait a moment for cleanup
        await asyncio.sleep(1)
        
        # Start the service
        return await self.start_service(service_name)
    
    async def get_service_status(self, service_name: str) -> Dict[str, Any]:
        """Get detailed status of a service"""
        service_config = await self.db_manager.get_service(service_name)
        if not service_config:
            return {'error': 'Service not found'}
        
        status = {
            'name': service_name,
            'enabled': service_config.get('enabled', False),
            'auto_start': service_config.get('auto_start', False),
            'singleton': service_config.get('singleton', True),
            'ports': service_config.get('ports', ''),
            'description': service_config.get('description', ''),
            'status': service_config.get('status', 'unknown'),
            'running': service_name in self.running_services
        }
        
        if service_name in self.running_services:
            service_info = self.running_services[service_name]
            status['started_at'] = service_info['started_at'].isoformat()
            status['uptime'] = str(datetime.now() - service_info['started_at'])
        
        return status
    
    async def list_all_services(self) -> List[Dict[str, Any]]:
        """Get status of all services"""
        services = await self.db_manager.list_services()
        service_statuses = []
        
        for service in services:
            status = await self.get_service_status(service['service_name'])
            service_statuses.append(status)
        
        return service_statuses
    
    async def shutdown_all_services(self) -> None:
        """Shutdown all running services"""
        logger.info("Shutting down all services...")
        
        for service_name in list(self.running_services.keys()):
            await self.stop_service(service_name)
        
        logger.info("All services shut down")
    
    def _parse_ports(self, ports_str: str) -> List[int]:
        """Parse comma-separated port string into list of integers"""
        if not ports_str:
            return []
        
        ports = []
        for port_str in ports_str.split(','):
            port_str = port_str.strip()
            if port_str.isdigit():
                ports.append(int(port_str))
            else:
                logger.warning(f"Invalid port number: {port_str}")
        
        return ports
    
    async def enable_service(self, service_name: str, enabled: bool = True) -> bool:
        """Enable or disable a service"""
        success = await self.db_manager.enable_service(service_name, enabled)
        if success and not enabled and service_name in self.running_services:
            # Stop service if it's running and being disabled
            await self.stop_service(service_name)
        return success
    
    async def set_service_auto_start(self, service_name: str, auto_start: bool = True) -> bool:
        """Set service auto-start configuration"""
        return await self.db_manager.set_service_auto_start(service_name, auto_start)
