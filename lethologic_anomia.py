#!/usr/bin/env python3
"""
Lethologic Anomia - Entry Point (Main)

This is a Python port of the C++ DICOM/HL7 Migration Service with AI integration.
Converts the original Windows service to a cross-platform Python application.

C++/Python author: Michael Collard
"""

import asyncio
import json
import os
import platform
import signal
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.traceback import install

# Install rich traceback for better error display
install()

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Core imports
from core.config import Settings, get_settings
from core.database import DatabaseManager
from core.custom_logging import setup_logging, get_logger
from core.process_manager import ProcessManager
# AI loop import - optional for basic functionality
try:
    from core.ai_loop import ai_loop
    AI_LOOP_AVAILABLE = True
except ImportError as e:
    print(f"AI loop not available: {e}")
    AI_LOOP_AVAILABLE = False
    ai_loop = None
from core.redis_manager import RedisManager
from services.web_interface import create_app
from services.ssh_server import SSHServer
from utils.platform_utils import detect_os, setup_signal_handlers

# Initialize console and logger
console = Console()
logger = get_logger(__name__)

# Global state
_process_manager: Optional[ProcessManager] = None
_shutdown_event = asyncio.Event()


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info(f"Received signal {signum}, initiating shutdown...")
    _shutdown_event.set()


async def initialize_services(settings: Settings) -> ProcessManager:
    """Initialize all core services"""
    logger.info("Initializing Lethologic Anomia...")
    
    # Initialize database
    db_manager = DatabaseManager(settings.database_url)
    await db_manager.initialize()
    logger.info("Database initialized")
    
    # Initialize Redis/Valkey with fallbacks
    redis_manager = RedisManager(settings.redis_url, db_manager)
    redis_available = await redis_manager.initialize()
    
    if redis_available:
        logger.info("Redis/Valkey connected successfully")
    else:
        logger.warning("Redis/Valkey not available - using fallback mechanisms")
        logger.info("Process management will use database and in-memory fallbacks")
    
    # Initialize process manager
    process_manager = ProcessManager(db_manager, redis_manager, settings)
    await process_manager.initialize()
    logger.info("Process manager initialized")
    
    return process_manager


# These functions are now replaced by auto-start functionality in ProcessManager
# Services are automatically started via process_manager.auto_start_core_services()


async def run_main_loop(settings: Settings, process_manager: ProcessManager):
    """Main application loop - equivalent to aiLoop() in C++"""
    try:
        # Auto-start core services first
        logger.info("Auto-starting core services...")
        started_services = await process_manager.auto_start_core_services()
        logger.info(f"Auto-started {len(started_services)} core services: {started_services}")
        
        # Initialize AI service for other components to use
        ai_service = None
        if AI_LOOP_AVAILABLE:
            from core.ai_loop import AIService
            ai_service = AIService(settings, process_manager.db_manager)
            await ai_service.initialize()
            logger.info("AI service initialized")
            
            # Store AI service reference for other components
            process_manager.ai_service = ai_service
        else:
            logger.warning("AI loop not available, running in basic mode")
        
        # In daemon mode, just wait for shutdown signal
        # Services are now managed by the process manager
        logger.info("Service running in daemon mode. Core services auto-started.")
        logger.info("Access via SSH, web interface, or DICOM connections.")
        
        # Wait for shutdown signal
        await _shutdown_event.wait()
        
        logger.info("Shutdown signal received, stopping services...")
        
        # Stop process manager
        await process_manager.shutdown()
        
        logger.info("All services stopped successfully")
        
    except Exception as e:
        logger.error(f"Error in main loop: {e}")
        raise



async def _async_main(settings: Settings, run_interactive: bool = False):
    """Async main function"""
    global _process_manager
    
    try:
        # Initialize services
        _process_manager = await initialize_services(settings)
        
        if run_interactive:
            # Run in interactive mode - start AI loop directly
            if AI_LOOP_AVAILABLE:
                logger.info("Starting interactive AI loop...")
                await ai_loop(_process_manager, settings)
            else:
                logger.error("Interactive mode requested but AI loop not available")
                sys.exit(1)
        else:
            # Run main loop in daemon mode
            await run_main_loop(settings, _process_manager)
        
    except Exception as e:
        logger.error(f"Error in async main: {e}")
        raise
    finally:
        if _process_manager:
            await _process_manager.shutdown()


class ConfigCLI:
    """Configuration CLI manager integrated into main application"""
    
    def __init__(self, db_path: str = "lethologic_anomia.db"):
        """Initialize CLI with database path"""
        self.db_manager = DatabaseManager(db_path)
        self.config_manager = None
    
    async def initialize(self):
        """Initialize the CLI"""
        await self.db_manager.initialize()
        try:
            from core.config_manager import DatabaseConfigManager
            self.config_manager = DatabaseConfigManager(self.db_manager)
            await self.config_manager.initialize()
        except ImportError:
            logger.warning("DatabaseConfigManager not available - config commands disabled")
    
    async def list_services(self):
        """List all configured services"""
        if not self.config_manager:
            print("Config manager not available")
            return
        print("Available services:")
        services = await self.config_manager.list_services()
        for service in services:
            print(f"  - {service}")
    
    async def show_service_config(self, service_name: str):
        """Show configuration for a specific service"""
        if not self.config_manager:
            print("Config manager not available")
            return
        config = await self.config_manager.get_service_config(service_name)
        if config:
            print(f"Configuration for service '{service_name}':")
            for key, value in config.items():
                print(f"  {key}: {value}")
        else:
            print(f"No configuration found for service '{service_name}'")
    
    async def show_all_configs(self):
        """Show all service configurations"""
        if not self.config_manager:
            print("Config manager not available")
            return
        all_configs = await self.config_manager.get_all_service_configs()
        for service_name, config in all_configs.items():
            print(f"\n[{service_name}]")
            for key, value in config.items():
                print(f"  {key} = {value}")
    
    async def set_config(self, service_name: str, config_name: str, value: str):
        """Set a configuration value"""
        if not self.config_manager:
            print("Config manager not available")
            return
        # Try to parse value as JSON, otherwise treat as string
        try:
            parsed_value = json.loads(value)
        except json.JSONDecodeError:
            # Check for boolean strings
            if value.lower() in ('true', 'false'):
                parsed_value = value.lower() == 'true'
            # Check for numeric strings
            elif value.isdigit():
                parsed_value = int(value)
            else:
                parsed_value = value
        
        success = await self.config_manager.set_config_value(service_name, config_name, parsed_value)
        if success:
            print(f"Set {service_name}.{config_name} = {parsed_value}")
        else:
            print(f"Failed to set {service_name}.{config_name}")
    
    async def export_config(self, output_file: Optional[str] = None):
        """Export configuration to JSON file"""
        if not self.config_manager:
            print("Config manager not available")
            return
        config_data = await self.config_manager.export_config()
        
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(config_data, f, indent=2)
            print(f"Configuration exported to {output_file}")
        else:
            print(json.dumps(config_data, indent=2))
    
    async def import_config(self, input_file: str):
        """Import configuration from JSON file"""
        if not self.config_manager:
            print("Config manager not available")
            return
        try:
            with open(input_file, 'r') as f:
                config_data = json.load(f)
            
            success = await self.config_manager.import_config(config_data)
            if success:
                print(f"Configuration imported from {input_file}")
            else:
                print(f"Failed to import configuration from {input_file}")
                
        except FileNotFoundError:
            print(f"File not found: {input_file}")
        except json.JSONDecodeError as e:
            print(f"Invalid JSON in {input_file}: {e}")
    
    async def shutdown(self):
        """Shutdown the CLI"""
        if self.db_manager:
            await self.db_manager.shutdown()


@click.group(invoke_without_command=True)
@click.pass_context
@click.option('--config', '-c', type=click.Path(exists=True), help='Configuration file path')
@click.option('--daemon', '-d', is_flag=True, help='Run as daemon')
@click.option('--interactive', '-i', is_flag=True, help='Force interactive mode (default if not daemon)')
@click.option('--install', is_flag=True, help='Install as system service')
@click.option('--uninstall', is_flag=True, help='Uninstall system service')
@click.option('--debug', is_flag=True, help='Enable debug mode')
@click.option('--help-extended', is_flag=True, help='Show extended help')
def main(ctx, config: Optional[str], daemon: bool, interactive: bool, install: bool, uninstall: bool, 
         debug: bool, help_extended: bool):
    """
    Lethologic Anomia - DICOM/HL7 Medical Image Data Migration with AI
    
    This is a comprehensive medical imaging migration service that supports:
    - DICOM C-FIND, C-STORE, C-MOVE operations
    - HL7/FHIR message processing
    - AI-powered text processing and voice interface
    - Multi-database support (SQLite, PostgreSQL, MySQL, Oracle, MongoDB)
    - Redis-based process management
    - Web-based management interface
    - SSH remote access
    """
    
    if ctx.invoked_subcommand is not None:
        # Subcommand will be invoked
        return
    
    if help_extended:
        console.print("""
[bold blue]Lethologic Anomia - Extended Help[/bold blue]

[bold]Available Commands:[/bold]
- help                  : Show available commands
- discovery <IP>:<Port> : DICOM discovery
- start_scp            : Start DICOM SCP listener  
- start_scu            : Start DICOM SCU operations
- start_index          : Start file indexing
- start_parse          : Start DICOM parsing
- select_query         : Execute SQL query
- schema               : Show database schema
- quit                 : Exit service

[bold]Advanced Features:[/bold]
- Multi-database support with automatic translation
- Redis/Valkey process management
- FastAPI web interface with SSL
- SSH server for remote management
- Speech-to-text and text-to-speech
- HuggingFace AI integration
- HL7/FHIR support
- Cross-platform (Linux/Windows)

[bold]Configuration:[/bold]
Set environment variables or use config file:
- DATABASE_URL: Database connection string
- REDIS_URL: Redis connection string  
- OPENAI_API_KEY: For AI features
- ANTHROPIC_API_KEY: Alternative AI provider
- WEB_PORT: Web interface port (default: 50443)
- SSH_PORT: SSH server port (default: 50022)

[bold]Configuration Management:[/bold]
Use the 'config' subcommand to manage database configurations:
- python lethologic_anomia.py config list                      # List all services
- python lethologic_anomia.py config show <service>            # Show service config
- python lethologic_anomia.py config show-all                  # Show all configs
- python lethologic_anomia.py config set <service> <name> <value>  # Set config value
- python lethologic_anomia.py config export [file.json]        # Export to file or stdout
- python lethologic_anomia.py config import <file.json>        # Import from file
        """)
        return
    
    # Load environment variables
    load_dotenv()
    
    # Initialize settings
    settings = get_settings(config_file=config)
    
    if debug:
        settings.debug = True
        os.environ["DEBUG"] = "1"
    
    # Setup logging
    setup_logging(settings.log_level, settings.log_file)
    
    # Handle service installation/uninstallation
    if install:
        from utils.service_installer import install_service
        install_service()
        return
        
    if uninstall:
        from utils.service_installer import uninstall_service
        uninstall_service()
        return
    
    # Setup signal handlers
    setup_signal_handlers(signal_handler)
    
    # Log startup information
    logger.info(f"Starting Migration Service v{settings.version}")
    logger.info(f"Platform: {platform.system()} {platform.release()}")
    logger.info(f"Python: {sys.version}")
    logger.info(f"Debug mode: {settings.debug}")
    
    # Determine mode - default to interactive unless daemon is explicitly set
    run_interactive = interactive or not daemon
    
    if daemon:
        logger.info("Running in daemon mode")
    elif run_interactive:
        logger.info("Running in interactive mode")
    
    # Run the main application
    try:
        asyncio.run(_async_main(settings, run_interactive))
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        console.print_exception()
        sys.exit(1)


@main.group()
def config():
    """Configuration management commands"""
    pass


@config.command()
def list():
    """List all configured services"""
    asyncio.run(_config_list())


@config.command()
@click.argument('service_name')
def show(service_name: str):
    """Show configuration for a specific service"""
    asyncio.run(_config_show(service_name))


@config.command(name='show-all')
def show_all():
    """Show all service configurations"""
    asyncio.run(_config_show_all())


@config.command()
@click.argument('service_name')
@click.argument('config_name')
@click.argument('value')
def set(service_name: str, config_name: str, value: str):
    """Set a configuration value"""
    asyncio.run(_config_set(service_name, config_name, value))


@config.command()
@click.argument('output_file', required=False)
def export(output_file: Optional[str]):
    """Export configuration to JSON file or stdout"""
    asyncio.run(_config_export(output_file))


@config.command(name='import')
@click.argument('input_file')
def import_config(input_file: str):
    """Import configuration from JSON file"""
    asyncio.run(_config_import(input_file))


# Config CLI async functions
async def _config_list():
    cli = ConfigCLI()
    try:
        await cli.initialize()
        await cli.list_services()
    finally:
        await cli.shutdown()


async def _config_show(service_name: str):
    cli = ConfigCLI()
    try:
        await cli.initialize()
        await cli.show_service_config(service_name)
    finally:
        await cli.shutdown()


async def _config_show_all():
    cli = ConfigCLI()
    try:
        await cli.initialize()
        await cli.show_all_configs()
    finally:
        await cli.shutdown()


async def _config_set(service_name: str, config_name: str, value: str):
    cli = ConfigCLI()
    try:
        await cli.initialize()
        await cli.set_config(service_name, config_name, value)
    finally:
        await cli.shutdown()


async def _config_export(output_file: Optional[str]):
    cli = ConfigCLI()
    try:
        await cli.initialize()
        await cli.export_config(output_file)
    finally:
        await cli.shutdown()


async def _config_import(input_file: str):
    cli = ConfigCLI()
    try:
        await cli.initialize()
        await cli.import_config(input_file)
    finally:
        await cli.shutdown()


if __name__ == "__main__":
    main()
