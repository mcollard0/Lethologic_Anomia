#!/usr/bin/env python3
"""
Lethologic Anomia - Entry Point (Main)

This is a Python port of the C++ DICOM/HL7 Migration Service with AI integration.
Converts the original Windows service to a cross-platform Python application.

C++/Python author: Michael Collard
"""

import asyncio
import os
import platform
import signal
import sys
from pathlib import Path
from typing import Optional

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


async def start_web_interface(settings: Settings, process_manager: ProcessManager):
    """Start the FastAPI web interface"""
    if settings.web_interface_enabled:
        app = create_app(process_manager)
        import uvicorn
        
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=settings.web_port,
            ssl_keyfile=settings.ssl_keyfile if settings.ssl_enabled else None,
            ssl_certfile=settings.ssl_certfile if settings.ssl_enabled else None,
            log_config=None,  # Use our custom logging
        )
        server = uvicorn.Server(config)
        
        logger.info(f"Starting web interface on {'https' if settings.ssl_enabled else 'http'}://0.0.0.0:{settings.web_port}")
        asyncio.create_task(server.serve())


async def start_ssh_server(settings: Settings, process_manager: ProcessManager):
    """Start the SSH server"""
    if settings.ssh_enabled:
        ssh_server = SSHServer(settings, process_manager)
        await ssh_server.start()
        logger.info(f"SSH server started on port {settings.ssh_port}")


async def run_main_loop(settings: Settings, process_manager: ProcessManager):
    """Main application loop - equivalent to aiLoop() in C++"""
    try:
        # Start web interface
        await start_web_interface(settings, process_manager)
        
        # Start SSH server
        await start_ssh_server(settings, process_manager)
        
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
        # Console interface is available via SSH
        logger.info("Service running in daemon mode. Use SSH or web interface for interaction.")
        
        # Wait for shutdown signal
        await _shutdown_event.wait()
        
        logger.info("Shutdown signal received, stopping services...")
        
        # Stop process manager
        await process_manager.shutdown()
        
        logger.info("All services stopped successfully")
        
    except Exception as e:
        logger.error(f"Error in main loop: {e}")
        raise


@click.command()
@click.option('--config', '-c', type=click.Path(exists=True), help='Configuration file path')
@click.option('--daemon', '-d', is_flag=True, help='Run as daemon')
@click.option('--interactive', '-i', is_flag=True, help='Force interactive mode (default if not daemon)')
@click.option('--install', is_flag=True, help='Install as system service')
@click.option('--uninstall', is_flag=True, help='Uninstall system service')
@click.option('--debug', is_flag=True, help='Enable debug mode')
@click.option('--help-extended', is_flag=True, help='Show extended help')
def main(config: Optional[str], daemon: bool, interactive: bool, install: bool, uninstall: bool, 
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


if __name__ == "__main__":
    main()
