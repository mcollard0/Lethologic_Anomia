#!/usr/bin/env python3
"""
Lethologic Anomia - Entry Point (Main)

This is a Python port of the C++ DICOM/HL7 Migration Service with AI integration.
Converts the original Windows service to a cross-platform Python application.

C++/Python author: Michael Collard (Yeah, I know, I'm sorry.)
"""

import click, asyncio, json, os, platform, signal, sys; from pathlib import Path; from typing import Any, Dict, Optional; from dotenv import load_dotenv; from rich.console import Console; from rich.traceback import install
install(); # Install rich traceback for better error display

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
from service.web_interface import create_app
from service.ssh_server import SSHServer
from util.platform_utils import detect_os, setup_signal_handlers
from util.process_cleanup import check_and_cleanup_zombies

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
# Core application options
@click.option('--config', '-c', type=click.Path(exists=True), help='Configuration file path')
@click.option('--daemon', '-d', is_flag=True, help='Run as daemon')
@click.option('--interactive', '-i', is_flag=True, help='Force interactive mode (default if not daemon)')
@click.option('--install', is_flag=True, help='Install as system service')
@click.option('--uninstall', is_flag=True, help='Uninstall system service')
@click.option('--debug', is_flag=True, help='Enable debug mode')
@click.option('--help-extended', is_flag=True, help='Show extended help')
@click.option('--force-cleanup', is_flag=True, help='Force cleanup of zombie processes on startup')
# DICOM operations
@click.option('--port', '-p', type=int, help='DICOM port number')
@click.option('--aet', '-a', type=str, help='DICOM AE Title')
@click.option('--start-scp', '-s', is_flag=True, help='Start DICOM Service Class Provider')
@click.option('--start-scu', type=str, metavar='<target>', help='Start DICOM Service Class User with target')
@click.option('--discovery', type=str, metavar='<target>', help='Start DICOM discovery on target')
# Migration management
@click.option('--get-migration-status', type=str, metavar='<site>', help='Get migration status for site')
@click.option('--new-migration', type=str, metavar='<site>', help='Create new migration for site')
# AI model management
@click.option('--set-model', type=str, metavar='<model>', help='Set AI model')
@click.option('--get-model', is_flag=True, help='Get current AI model')
@click.option('--list-models', is_flag=True, help='List available AI models')
# Trust and aggression levels
@click.option('--set-trust', type=int, metavar='<level>', help='Set trust level (-127 to 127)')
@click.option('--get-trust', is_flag=True, help='Get current trust level')
@click.option('--set-aggression', type=int, metavar='<level>', help='Set aggression level (-127 to 127)')
@click.option('--get-aggression', is_flag=True, help='Get current aggression level')
# Database operations
@click.option('--query', type=str, metavar='<sql>', help='Execute database query')
@click.option('--insert-query', type=str, metavar='<sql>', help='Execute database insert/update')
# System operations
@click.option('--start-index', is_flag=True, help='Start DICOM file indexing')
@click.option('--start-parse', is_flag=True, help='Start DICOM file parsing')
@click.option('--schema', is_flag=True, help='Show database schema')
@click.option('--log', type=str, metavar='<message>', help='Add message to log')
def main(ctx, config: Optional[str], daemon: bool, interactive: bool, install: bool, uninstall: bool, 
         debug: bool, help_extended: bool, force_cleanup: bool,
         # DICOM options
         port: Optional[int], aet: Optional[str], start_scp: bool, start_scu: Optional[str], discovery: Optional[str],
         # Migration options
         get_migration_status: Optional[str], new_migration: Optional[str],
         # AI model options
         set_model: Optional[str], get_model: bool, list_models: bool,
         # Trust/aggression options
         set_trust: Optional[int], get_trust: bool, set_aggression: Optional[int], get_aggression: bool,
         # Database options
         query: Optional[str], insert_query: Optional[str],
         # System options
         start_index: bool, start_parse: bool, schema: bool, log: Optional[str]):
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
        
    # Check for zombie processes (unless running a quick command)
    is_quick_command = any([get_model, list_models, get_trust, get_aggression, query, schema, 
            get_migration_status, set_trust is not None, set_aggression is not None, 
            set_model, log, insert_query])
            
    if not is_quick_command:
        # This will prompt user or auto-kill if force_cleanup is True
        # Passed as kwarg to avoid modifying signature if unrelated changes happen
        check_and_cleanup_zombies(auto_kill=force_cleanup)

        # These options require database access but not full service startup
        load_dotenv()
        settings = get_settings(config_file=config)
        if debug:
            settings.debug = True
            os.environ["DEBUG"] = "1"
        
        setup_logging(settings.log_level, settings.log_file)
        
        # Handle these options via async function
        asyncio.run(_handle_immediate_options(
            settings, get_model, list_models, get_trust, get_aggression, query, schema,
            get_migration_status, set_trust, set_aggression, set_model, log, insert_query
        ))
        return
    
    # Handle DICOM operations that require service components
    if any([start_scp, start_scu, discovery, start_index, start_parse, new_migration]):
        # These options require more complex service initialization
        load_dotenv()
        settings = get_settings(config_file=config)
        if debug:
            settings.debug = True
            os.environ["DEBUG"] = "1"
        
        setup_logging(settings.log_level, settings.log_file)
        setup_signal_handlers(signal_handler)
        
        # Store DICOM options in settings for service components to use
        if port:
            settings.scp_port = port
        if aet:
            settings.scp_ae_title = aet
        
        # Handle these via async function with service initialization
        asyncio.run(_handle_service_options(
            settings, start_scp, start_scu, discovery, start_index, start_parse, new_migration
        ))
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

[bold]Granular CLI Options (New!):[/bold]
[yellow]DICOM Operations:[/yellow]
- --port <port>, -p      : Specify DICOM port number
- --aet <title>, -a      : Specify DICOM AE Title
- --start-scp, -s        : Start DICOM Service Class Provider
- --start-scu <target>   : Start DICOM SCU to target
- --discovery <target>   : Run DICOM discovery on target

[yellow]AI Model Management:[/yellow]
- --get-model            : Show current AI model
- --list-models          : List all available AI models
- --set-model <model>    : Set AI model
- --set-trust <level>    : Set AI trust level (-127 to 127)
- --get-trust            : Get current trust level
- --set-aggression <n>   : Set AI aggression level (-127 to 127)
- --get-aggression       : Get current aggression level

[yellow]Database Operations:[/yellow]
- --query <sql>          : Execute database query
- --insert-query <sql>   : Execute database insert/update
- --schema               : Show database schema

[yellow]Migration & System:[/yellow]
- --get-migration-status <site> : Get migration status for site
- --new-migration <site>        : Create new migration for site
- --start-index                 : Start DICOM file indexing
- --start-parse                 : Start DICOM file parsing
- --log <message>               : Add message to log

[bold]Configuration Management:[/bold]
Use the 'config' subcommand to manage database configurations:
- python lethologic_anomia.py config list                      # List all services
- python lethologic_anomia.py config show <service>            # Show service config
- python lethologic_anomia.py config show-all                  # Show all configs
- python lethologic_anomia.py config set <service> <name> <value>  # Set config value
- python lethologic_anomia.py config export [file.json]        # Export to file or stdout
- python lethologic_anomia.py config import <file.json>        # Import from file

[bold]Examples of New CLI Options:[/bold]
- python lethologic_anomia.py --start-scp --port 11112 --aet MY_SCP
- python lethologic_anomia.py --query "SELECT * FROM studies LIMIT 5"
- python lethologic_anomia.py --set-trust 10 --set-aggression -5
- python lethologic_anomia.py --get-model --list-models
- python lethologic_anomia.py --discovery 192.168.1.100:104
- python lethologic_anomia.py --schema
- python lethologic_anomia.py --log "System status check"
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
        from util.service_installer import install_service
        install_service()
        return
        
    if uninstall:
        from util.service_installer import uninstall_service
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


# CLI option handler functions
async def _handle_immediate_options(settings, get_model, list_models, get_trust, get_aggression, 
                                   query, schema, get_migration_status, set_trust, set_aggression, 
                                   set_model, log_message, insert_query):
    """Handle CLI options that only need database access"""
    db_manager = DatabaseManager(settings.database_url)
    await db_manager.initialize()
    
    try:
        # AI Model operations
        if get_model:
            # Get current AI model from config
            result = await db_manager.execute_query(
                "SELECT value FROM config WHERE service = 'AI' AND name = 'CURRENT_MODEL' LIMIT 1"
            )
            if result and len(result) > 0:
                console.print(f"Current AI model: {result[0]['value']}")
            else:
                console.print("No AI model configured")
        
        if list_models:
            # List available models - this would typically come from AI service
            console.print("Available AI models:")
            models = [
                "anthropic/claude-3-opus",
                "anthropic/claude-3-sonnet", 
                "anthropic/claude-3-haiku",
                "openai/gpt-4",
                "openai/gpt-3.5-turbo",
                "xai/grok-beta"
            ]
            for i, model in enumerate(models, 1):
                console.print(f"  {i}. {model}")
        
        if set_model:
            # Set AI model in config
            await db_manager.execute_query(
                "INSERT OR REPLACE INTO config (service, name, value, updated_at) VALUES ('AI', 'CURRENT_MODEL', ?, CURRENT_TIMESTAMP)",
                (set_model,)
            )
            console.print(f"AI model set to: {set_model}")
        
        # Trust/Aggression operations
        if get_trust:
            result = await db_manager.execute_query(
                "SELECT value FROM config WHERE service = 'AI' AND name = 'TRUST_LEVEL' LIMIT 1"
            )
            trust_level = int(result[0]['value']) if result and len(result) > 0 else 0
            console.print(f"Current trust level: {trust_level}")
        
        if get_aggression:
            result = await db_manager.execute_query(
                "SELECT value FROM config WHERE service = 'AI' AND name = 'AGGRESSION_LEVEL' LIMIT 1"
            )
            aggression_level = int(result[0]['value']) if result and len(result) > 0 else 0
            console.print(f"Current aggression level: {aggression_level}")
        
        if set_trust is not None:
            if -127 <= set_trust <= 127:
                await db_manager.execute_query(
                    "INSERT OR REPLACE INTO config (service, name, value, updated_at) VALUES ('AI', 'TRUST_LEVEL', ?, CURRENT_TIMESTAMP)",
                    (str(set_trust),)
                )
                console.print(f"Trust level set to: {set_trust}")
            else:
                console.print("❌ Trust level must be between -127 and 127")
        
        if set_aggression is not None:
            if -127 <= set_aggression <= 127:
                await db_manager.execute_query(
                    "INSERT OR REPLACE INTO config (service, name, value, updated_at) VALUES ('AI', 'AGGRESSION_LEVEL', ?, CURRENT_TIMESTAMP)",
                    (str(set_aggression),)
                )
                console.print(f"Aggression level set to: {set_aggression}")
            else:
                console.print("❌ Aggression level must be between -127 and 127")
        
        # Database operations
        if query:
            console.print(f"Executing query: {query}")
            try:
                result = await db_manager.execute_query(query)
                if result:
                    console.print(f"Query returned {len(result)} rows:")
                    for i, row in enumerate(result[:10]):  # Limit to 10 rows for display
                        console.print(f"  Row {i+1}: {dict(row)}")
                    if len(result) > 10:
                        console.print(f"  ... and {len(result) - 10} more rows")
                else:
                    console.print("Query executed successfully (no results)")
            except Exception as e:
                console.print(f"❌ Query failed: {e}")
        
        if insert_query:
            console.print(f"Executing insert/update: {insert_query}")
            try:
                await db_manager.execute_query(insert_query)
                console.print("✅ Insert/update executed successfully")
            except Exception as e:
                console.print(f"❌ Insert/update failed: {e}")
        
        if schema:
            console.print("Database Schema:")
            tables = await db_manager.execute_query(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            for table in tables:
                table_name = table['name']
                console.print(f"\n📋 Table: {table_name}")
                columns = await db_manager.execute_query(
                    f"PRAGMA table_info({table_name})"
                )
                for col in columns:
                    pk = " (PRIMARY KEY)" if col['pk'] else ""
                    notnull = " NOT NULL" if col['notnull'] else ""
                    console.print(f"  - {col['name']}: {col['type']}{pk}{notnull}")
        
        # Migration operations
        if get_migration_status:
            console.print(f"Migration status for site: {get_migration_status}")
            # This would integrate with the migration system
            console.print("Migration status checking not yet implemented")
        
        # Logging
        if log_message:
            await db_manager.execute_query(
                "INSERT INTO log (timestamp, level, module, message) VALUES (CURRENT_TIMESTAMP, 'INFO', 'CLI', ?)",
                (log_message,)
            )
            console.print(f"✅ Logged message: {log_message}")
    
    finally:
        await db_manager.shutdown()


async def _handle_service_options(settings, start_scp, start_scu, discovery, start_index, 
                                 start_parse, new_migration):
    """Handle CLI options that require service components"""
    # Initialize process manager for service operations
    process_manager = await initialize_services(settings)
    
    try:
        if start_scp:
            port = getattr(settings, 'scp_port', 11112)
            aet = getattr(settings, 'scp_ae_title', 'LETHOLOGIC_SCP')
            console.print(f"🚀 Starting DICOM SCP on port {port} with AE Title '{aet}'...")
            # This would integrate with the DICOM SCP service
            console.print("DICOM SCP service starting (integration pending)")
        
        if start_scu:
            console.print(f"🔍 Starting DICOM SCU to target: {start_scu}")
            console.print("DICOM SCU operation (integration pending)")
        
        if discovery:
            console.print(f"🔍 Starting DICOM discovery on: {discovery}")
            console.print("DICOM discovery (integration pending)")
        
        if start_index:
            console.print("📄 Starting DICOM file indexing...")
            console.print("File indexing (integration pending)")
        
        if start_parse:
            console.print("🔍 Starting DICOM file parsing...")
            console.print("File parsing (integration pending)")
        
        if new_migration:
            console.print(f"📦 Creating new migration for site: {new_migration}")
            console.print("Migration creation (integration pending)")
        
        # Keep service running briefly to allow operation to complete
        await asyncio.sleep(2)
        
    finally:
        await process_manager.shutdown()


if __name__ == "__main__":
    main()
