"""
Process Manager for the Migration Service

Orchestrates all services and processes in the migration service.
Manages DICOM services, web interface, SSH server, and AI components.
Uses Redis for process coordination and database for persistent storage.
"""

import asyncio
import json
import os
import signal
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass

from .config import Settings
from .database import DatabaseManager
from .redis_manager import RedisManager, RedisLock
from .custom_logging import get_logger, LogPollingService
from .config_manager import DatabaseConfigManager

logger = get_logger(__name__)


class ProcessState(Enum):
    """Process states"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class ExecutionMode(Enum):
    """Process execution modes"""
    THREAD = "thread"      # Run in thread (good for I/O bound, limited by GIL)
    PROCESS = "process"    # Run in separate process (good for CPU bound, bypasses GIL)
    ASYNCIO = "asyncio"    # Run as async task (good for async I/O)


class ProcessType(Enum):
    """Process types"""
    WEB_INTERFACE = "web_interface"
    SSH_SERVER = "ssh_server"
    DICOM_SCP = "dicom_scp"
    DICOM_SCU = "dicom_scu"
    DICOM_DISCOVERY = "dicom_discovery"  # Added discovery service
    DICOM_SEARCH = "dicom_search"
    DICOM_PARSER = "dicom_parser"
    HL7_LISTENER = "hl7_listener"
    HL7_PROCESSOR = "hl7_processor"
    AI_PROCESSOR = "ai_processor"
    LOG_POLLER = "log_poller"
    
    @classmethod
    def get_default_execution_mode(cls, process_type: 'ProcessType') -> ExecutionMode:
        """Get default execution mode for process type"""
        # Services that should run in separate processes to avoid GIL
        process_based = {
            cls.DICOM_SCU,         # CPU intensive DICOM operations
            cls.DICOM_DISCOVERY,   # Network intensive discovery
            cls.DICOM_SEARCH,      # Database intensive search
            cls.DICOM_PARSER,      # CPU intensive file parsing
            cls.AI_PROCESSOR       # CPU intensive AI operations
        }
        
        # Services that work well with async/threads
        thread_based = {
            cls.WEB_INTERFACE,     # FastAPI works well with asyncio
            cls.SSH_SERVER,        # I/O bound
            cls.DICOM_SCP,         # I/O bound server
            cls.HL7_LISTENER,      # I/O bound server
            cls.HL7_PROCESSOR,     # Mixed, but can be threaded
            cls.LOG_POLLER         # I/O bound
        }
        
        if process_type in process_based:
            return ExecutionMode.PROCESS
        elif process_type in thread_based:
            return ExecutionMode.THREAD
        else:
            return ExecutionMode.THREAD  # Default to thread


@dataclass
class ProcessInfo:
    """Process information"""
    process_id: str
    process_type: ProcessType
    state: ProcessState
    pid: Optional[int] = None
    started_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    metadata: Dict[str, Any] = None
    task: Optional[asyncio.Task] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class ProcessManager:
    """
    Main process manager for the Migration Service
    
    Manages all service processes including:
    - Web interface (FastAPI)
    - SSH server
    - DICOM services (SCP, SCU, Search, Parser)
    - HL7/FHIR services
    - AI processing
    - Log polling service
    """
    
    def __init__(
        self,
        db_manager: DatabaseManager,
        redis_manager: RedisManager,
        settings: Settings
    ):
        """
        Initialize process manager
        
        Args:
            db_manager: Database manager instance
            redis_manager: Redis manager instance
            settings: Application settings
        """
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.settings = settings
        self.config_manager = DatabaseConfigManager(db_manager)
        
        # Process tracking
        self.processes: Dict[str, ProcessInfo] = {}
        self.process_types: Dict[ProcessType, Set[str]] = {ptype: set() for ptype in ProcessType}
        
        # Manager state
        self._manager_id = str(uuid.uuid4())
        self._running = False
        self._shutdown_event = asyncio.Event()
        
        # Background services
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._monitoring_task: Optional[asyncio.Task] = None
        self._log_polling_service: Optional[LogPollingService] = None
        
        logger.info(f"Process manager initialized with ID: {self._manager_id}")
    
    async def initialize(self) -> None:
        """Initialize the process manager"""
        try:
            # Initialize config manager first
            await self.config_manager.initialize()
            
            # Register this manager process in Redis (if available)
            await self.redis_manager.register_process(
                "process_manager",
                {"manager_id": self._manager_id}
            )
            
            # Start background services
            self._heartbeat_task = asyncio.create_task(self._heartbeat_worker())
            self._monitoring_task = asyncio.create_task(self._monitoring_worker())
            
            # Initialize log polling service if Redis is connected
            redis_connected = await self.redis_manager.is_connected()
            if redis_connected and (self.settings.log_file or self.db_manager):
                self._log_polling_service = LogPollingService(
                    redis_manager=self.redis_manager,
                    db_manager=self.db_manager,
                    log_file=self.settings.log_file,
                    poll_interval=60,
                    batch_size=100
                )
                await self._log_polling_service.start()
                logger.info("Log polling service started")
            elif not redis_connected:
                logger.info("Log polling service disabled (Redis not available)")
            
            self._running = True
            logger.info("Process manager initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize process manager: {e}")
            raise
    
    async def shutdown(self) -> None:
        """Shutdown the process manager"""
        logger.info("Shutting down process manager...")
        
        # Signal shutdown
        self._running = False
        self._shutdown_event.set()
        
        # Stop all managed processes
        await self._stop_all_processes()
        
        # Stop log polling service
        if self._log_polling_service:
            await self._log_polling_service.stop()
            logger.info("Log polling service stopped")
        
        # Cancel background tasks
        for task in [self._heartbeat_task, self._monitoring_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Cleanup Redis registration
        try:
            await self.redis_manager.unregister_process()
        except Exception as e:
            logger.warning(f"Failed to unregister from Redis: {e}")
        
        logger.info("Process manager shutdown complete")
    
    async def start_process(
        self,
        process_type: ProcessType,
        config: Optional[Dict[str, Any]] = None,
        force_restart: bool = False
    ) -> str:
        """
        Start a new process
        
        Args:
            process_type: Type of process to start
            config: Process configuration
            force_restart: Whether to force restart if already running
            
        Returns:
            Process ID of started process
        """
        config = config or {}
        
        # Check if process is already running
        existing_processes = self.process_types[process_type]
        if existing_processes and not force_restart:
            # Return first running process ID
            for process_id in existing_processes:
                if self.processes[process_id].state == ProcessState.RUNNING:
                    logger.warning(f"Process {process_type.value} already running: {process_id}")
                    return process_id
        
        # Generate process ID
        process_id = f"{process_type.value}_{uuid.uuid4().hex[:8]}"
        
        # Create process info
        process_info = ProcessInfo(
            process_id=process_id,
            process_type=process_type,
            state=ProcessState.STARTING,
            pid=os.getpid(),
            started_at=datetime.now(),
            metadata=config
        )
        
        try:
            # Register in Redis with distributed lock
            async with RedisLock(self.redis_manager, f"process_start_{process_type.value}", timeout=30):
                # Start the actual process
                task = await self._create_process_task(process_type, process_id, config)
                process_info.task = task
                process_info.state = ProcessState.RUNNING
                
                # Store process info
                self.processes[process_id] = process_info
                self.process_types[process_type].add(process_id)
                
                # Register in Redis
                await self.redis_manager.register_process(
                    f"{process_type.value}_{process_id}",
                    {
                        "process_id": process_id,
                        "process_type": process_type.value,
                        "manager_id": self._manager_id,
                        "config": config
                    }
                )
                
                logger.info(f"Started process {process_type.value} with ID: {process_id}")
                return process_id
                
        except Exception as e:
            logger.error(f"Failed to start process {process_type.value}: {e}")
            process_info.state = ProcessState.ERROR
            raise
    
    async def stop_process(self, process_id: str) -> bool:
        """
        Stop a process
        
        Args:
            process_id: Process ID to stop
            
        Returns:
            True if process was stopped successfully
        """
        if process_id not in self.processes:
            logger.warning(f"Process not found: {process_id}")
            return False
        
        process_info = self.processes[process_id]
        
        if process_info.state == ProcessState.STOPPED:
            logger.warning(f"Process already stopped: {process_id}")
            return True
        
        try:
            process_info.state = ProcessState.STOPPING
            
            # Cancel the process task
            if process_info.task and not process_info.task.done():
                process_info.task.cancel()
                try:
                    await process_info.task
                except asyncio.CancelledError:
                    pass
            
            # Update state
            process_info.state = ProcessState.STOPPED
            process_info.task = None
            
            # Remove from tracking
            self.process_types[process_info.process_type].discard(process_id)
            
            # Unregister from Redis (if available)
            try:
                if self.redis_manager.redis_available and self.redis_manager.redis_client:
                    await self.redis_manager.redis_client.hdel(
                        "migration:processes",
                        f"{process_info.process_type.value}_{process_id}"
                    )
            except Exception as e:
                logger.warning(f"Failed to unregister process from Redis: {e}")
            
            logger.info(f"Stopped process: {process_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop process {process_id}: {e}")
            process_info.state = ProcessState.ERROR
            return False
    
    async def get_process_status(self, process_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get status of processes
        
        Args:
            process_id: Specific process ID or None for all processes
            
        Returns:
            Process status information
        """
        if process_id:
            if process_id in self.processes:
                process_info = self.processes[process_id]
                return {
                    "process_id": process_info.process_id,
                    "process_type": process_info.process_type.value,
                    "state": process_info.state.value,
                    "pid": process_info.pid,
                    "started_at": process_info.started_at.isoformat() if process_info.started_at else None,
                    "last_heartbeat": process_info.last_heartbeat.isoformat() if process_info.last_heartbeat else None,
                    "metadata": process_info.metadata
                }
            else:
                return {"error": f"Process not found: {process_id}"}
        else:
            # Return all processes
            status = {
                "manager_id": self._manager_id,
                "total_processes": len(self.processes),
                "processes": {}
            }
            
            for proc_id, proc_info in self.processes.items():
                status["processes"][proc_id] = {
                    "process_type": proc_info.process_type.value,
                    "state": proc_info.state.value,
                    "pid": proc_info.pid,
                    "started_at": proc_info.started_at.isoformat() if proc_info.started_at else None,
                    "last_heartbeat": proc_info.last_heartbeat.isoformat() if proc_info.last_heartbeat else None
                }
            
            # Add process counts by type
            status["by_type"] = {}
            for process_type, process_set in self.process_types.items():
                running_count = sum(
                    1 for pid in process_set 
                    if self.processes[pid].state == ProcessState.RUNNING
                )
                status["by_type"][process_type.value] = {
                    "total": len(process_set),
                    "running": running_count
                }
            
            return status
    
    async def _create_process_task(
        self,
        process_type: ProcessType,
        process_id: str,
        config: Dict[str, Any]
    ) -> asyncio.Task:
        """
        Create and start a process task
        
        Args:
            process_type: Type of process
            process_id: Process ID
            config: Process configuration
            
        Returns:
            Asyncio task for the process
        """
        # Create actual service implementations based on process type
        if process_type == ProcessType.DICOM_SCP:
            return asyncio.create_task(
                self._run_dicom_scp_service(process_id, config),
                name=f"{process_type.value}_{process_id}"
            )
        elif process_type == ProcessType.WEB_INTERFACE:
            return asyncio.create_task(
                self._run_web_interface_service(process_id, config),
                name=f"{process_type.value}_{process_id}"
            )
        elif process_type == ProcessType.SSH_SERVER:
            return asyncio.create_task(
                self._run_ssh_server_service(process_id, config),
                name=f"{process_type.value}_{process_id}"
            )
        elif process_type == ProcessType.HL7_LISTENER:
            return asyncio.create_task(
                self._run_hl7_listener_service(process_id, config),
                name=f"{process_type.value}_{process_id}"
            )
        else:
            # For other process types, use placeholder service
            return asyncio.create_task(
                self._run_placeholder_service(process_type, process_id),
                name=f"{process_type.value}_{process_id}"
            )
    
    async def _stop_all_processes(self) -> None:
        """
        Stop all managed processes
        """
        logger.info("Stopping all processes...")
        
        # Create list of process IDs to avoid dict modification during iteration
        process_ids = list(self.processes.keys())
        
        # Stop processes in parallel
        stop_tasks = [self.stop_process(pid) for pid in process_ids]
        
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)
        
        logger.info(f"Stopped {len(process_ids)} processes")
    
    async def _heartbeat_worker(self) -> None:
        """
        Background worker to send heartbeats and update process status
        """
        while self._running and not self._shutdown_event.is_set():
            try:
                # Update heartbeat for this manager
                await self.redis_manager.update_heartbeat()
                
                # Update heartbeats and pings for all managed processes
                for process_id, process_info in self.processes.items():
                    if process_info.state == ProcessState.RUNNING:
                        process_info.last_heartbeat = datetime.now()
                        # Update service ping in database
                        await self.update_service_ping(process_id)
                
                # Clean up stale services periodically (every 10 heartbeats)
                if hasattr(self, '_heartbeat_count'):
                    self._heartbeat_count += 1
                else:
                    self._heartbeat_count = 1
                
                if self._heartbeat_count % 10 == 0:
                    await self._cleanup_stale_services()
                
                # Wait for next heartbeat interval
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.settings.redis.heartbeat_interval
                )
                
            except asyncio.TimeoutError:
                # Timeout is expected, continue loop
                continue
            except Exception as e:
                logger.error(f"Heartbeat worker error: {e}")
                await asyncio.sleep(30)
    
    async def _monitoring_worker(self) -> None:
        """
        Background worker to monitor process health
        """
        while self._running and not self._shutdown_event.is_set():
            try:
                # Check process health
                dead_processes = []
                
                for process_id, process_info in self.processes.items():
                    if process_info.task and process_info.task.done():
                        if process_info.task.cancelled():
                            logger.info(f"Process {process_id} was cancelled")
                        elif process_info.task.exception():
                            logger.error(f"Process {process_id} failed: {process_info.task.exception()}")
                            process_info.state = ProcessState.ERROR
                        else:
                            logger.info(f"Process {process_id} completed normally")
                        
                        dead_processes.append(process_id)
                
                # Clean up dead processes
                for process_id in dead_processes:
                    await self.stop_process(process_id)
                
                # Wait before next monitoring cycle
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=60  # Check every minute
                )
                
            except asyncio.TimeoutError:
                # Timeout is expected, continue loop
                continue
            except Exception as e:
                logger.error(f"Monitoring worker error: {e}")
                await asyncio.sleep(30)
    
    async def _run_dicom_scp_service(self, process_id: str, config: Dict[str, Any]) -> None:
        """
        Run DICOM SCP service
        
        Args:
            process_id: Process ID
            config: Service configuration
        """
        try:
            from service.dicom.scp import DICOMSCPService, create_dicom_tables
            
            logger.info(f"Starting DICOM SCP service {process_id}")
            
            # Ensure database tables exist
            await create_dicom_tables(self.db_manager)
            
            # Create and configure SCP service
            scp_service = DICOMSCPService(self.db_manager, self.settings)
            
            # Get database configuration with fallback to settings/config
            db_config = await self.config_manager.get_dicom_scp_config(self.settings)
            
            # Merge: provided config > database config > settings defaults
            scp_config = {
                'port': config.get('port') or db_config.get('port', self.settings.dicom.scp_port),
                'ae_title': config.get('ae_title') or db_config.get('ae_title', self.settings.dicom.our_ae_title),
                'output_directory': config.get('output_directory') or db_config.get('storage_directory', self.settings.dicom.storage_directory),
                'max_pdu': config.get('max_pdu') or db_config.get('max_pdu', self.settings.dicom.max_pdu),
                'acse_timeout': config.get('acse_timeout') or db_config.get('acse_timeout', self.settings.dicom.acse_timeout),
                'dimse_timeout': config.get('dimse_timeout') or db_config.get('dimse_timeout', self.settings.dicom.dimse_timeout),
                'socket_timeout': config.get('socket_timeout') or db_config.get('socket_timeout', self.settings.dicom.socket_timeout)
            }
            
            # Configure SSL if enabled
            ssl_enabled = config.get('ssl') or db_config.get('ssl_enabled', self.settings.dicom.ssl_enabled)
            if ssl_enabled:
                scp_config['port'] = config.get('port') or db_config.get('ssl_port', self.settings.dicom.scp_ssl_port)
                scp_config['ssl_enabled'] = True
                scp_config['ssl_cert_file'] = db_config.get('ssl_cert_file', self.settings.dicom.ssl_cert_file)
                scp_config['ssl_key_file'] = db_config.get('ssl_key_file', self.settings.dicom.ssl_key_file)
            
            if not scp_service.configure(scp_config):
                raise RuntimeError("Failed to configure DICOM SCP service")
            
            if not scp_service.start():
                raise RuntimeError("Failed to start DICOM SCP service")
            
            logger.info(f"DICOM SCP service {process_id} started successfully on port {scp_config['port']}")
            
            # Keep service running until cancelled
            try:
                while True:
                    await asyncio.sleep(30)
                    if not scp_service.is_running:
                        logger.warning(f"DICOM SCP service {process_id} stopped unexpectedly")
                        break
            except asyncio.CancelledError:
                logger.info(f"DICOM SCP service {process_id} cancellation requested")
                raise
            finally:
                scp_service.stop()
                logger.info(f"DICOM SCP service {process_id} stopped")
                
        except Exception as e:
            logger.error(f"DICOM SCP service {process_id} error: {e}")
            raise
    
    async def _run_web_interface_service(self, process_id: str, config: Dict[str, Any]) -> None:
        """
        Run web interface service
        
        Args:
            process_id: Process ID
            config: Service configuration
        """
        try:
            from service.web_interface import create_app
            import uvicorn
            
            logger.info(f"Starting web interface service {process_id}")
            
            # Get database configuration with fallback to settings
            db_config = await self.config_manager.get_web_interface_config(self.settings)
            
            # Create FastAPI app
            app = create_app(self)
            
            # Merge configuration: provided > database > settings
            host = config.get('host') or db_config.get('host', '0.0.0.0')
            port = config.get('port') or db_config.get('port', self.settings.web.web_port)
            ssl_enabled = db_config.get('ssl_enabled', self.settings.web.ssl_enabled)
            
            # Configure uvicorn
            uvicorn_config = uvicorn.Config(
                app,
                host=host,
                port=port,
                ssl_keyfile=db_config.get('ssl_key_file', self.settings.web.ssl_keyfile) if ssl_enabled else None,
                ssl_certfile=db_config.get('ssl_cert_file', self.settings.web.ssl_certfile) if ssl_enabled else None,
                log_config=None,  # Use our custom logging
                access_log=False  # Disable uvicorn access log
            )
            
            server = uvicorn.Server(uvicorn_config)
            
            logger.info(f"Web interface service {process_id} starting on {'https' if ssl_enabled else 'http'}://{host}:{port}")
            
            # Run server
            await server.serve()
            
        except Exception as e:
            logger.error(f"Web interface service {process_id} error: {e}")
            raise
    
    async def _run_ssh_server_service(self, process_id: str, config: Dict[str, Any]) -> None:
        """
        Run SSH server service
        
        Args:
            process_id: Process ID
            config: Service configuration
        """
        try:
            from service.ssh_server import SSHServer
            
            logger.info(f"Starting SSH server service {process_id}")
            
            # Get database configuration with fallback to settings
            db_config = await self.config_manager.get_ssh_server_config(self.settings)
            
            # Create SSH server with merged configuration
            ssh_server = SSHServer(self.settings, self)
            
            # Start SSH server
            await ssh_server.start()
            
            # Get final port configuration
            ssh_port = config.get('port') or db_config.get('port', self.settings.ssh.ssh_port)
            logger.info(f"SSH server service {process_id} started on port {ssh_port}")
            
            # Keep service running until cancelled
            try:
                while True:
                    await asyncio.sleep(30)
                    # Could add health checks here
            except asyncio.CancelledError:
                logger.info(f"SSH server service {process_id} cancellation requested")
                raise
            finally:
                await ssh_server.stop()
                logger.info(f"SSH server service {process_id} stopped")
                
        except Exception as e:
            logger.error(f"SSH server service {process_id} error: {e}")
            raise
    
    async def _run_hl7_listener_service(self, process_id: str, config: Dict[str, Any]) -> None:
        """
        Run HL7/FHIR listener service
        
        Args:
            process_id: Process ID
            config: Service configuration
        """
        try:
            logger.info(f"Starting HL7 listener service {process_id}")
            
            # Get database configuration with fallback to settings
            db_config = await self.config_manager.get_hl7_listener_config(self.settings)
            
            # Merge configuration: provided > database > settings
            host = config.get('host') or db_config.get('host', '0.0.0.0')
            port = config.get('port') or db_config.get('port', self.settings.hl7.hl7_port)
            max_connections = db_config.get('max_connections', 50)
            
            # Create a basic HL7 listener (placeholder for now)
            import socket
            
            # Create socket for HL7 listener
            hl7_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            hl7_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            hl7_socket.bind((host, port))
            hl7_socket.listen(max_connections)
            hl7_socket.setblocking(False)
            
            logger.info(f"HL7 listener service {process_id} listening on {host}:{port} (max connections: {max_connections})")
            
            # Keep service running until cancelled
            try:
                while True:
                    await asyncio.sleep(30)
                    # Add HL7 message processing here
            except asyncio.CancelledError:
                logger.info(f"HL7 listener service {process_id} cancellation requested")
                raise
            finally:
                hl7_socket.close()
                logger.info(f"HL7 listener service {process_id} stopped")
                
        except Exception as e:
            logger.error(f"HL7 listener service {process_id} error: {e}")
            raise
    
    async def _run_placeholder_service(self, process_type: ProcessType, process_id: str) -> None:
        """
        Run placeholder service for unimplemented process types
        
        Args:
            process_type: Process type
            process_id: Process ID
        """
        logger.info(f"Starting placeholder service for {process_type.value} {process_id}")
        try:
            while True:
                await asyncio.sleep(60)  # Sleep for 1 minute
                logger.debug(f"Placeholder service {process_type.value} {process_id} heartbeat")
        except asyncio.CancelledError:
            logger.info(f"Placeholder service {process_type.value} {process_id} cancelled")
            raise
        except Exception as e:
            logger.error(f"Placeholder service {process_type.value} {process_id} error: {e}")
            raise
    
    async def auto_start_core_services(self) -> List[str]:
        """
        Auto-start core services based on database configuration
        
        Returns:
            List of started process IDs
        """
        started_processes = []
        
        try:
            # Get configurations from database
            dicom_config = await self.config_manager.get_dicom_scp_config(self.settings)
            web_config = await self.config_manager.get_web_interface_config(self.settings)
            ssh_config = await self.config_manager.get_ssh_server_config(self.settings)
            hl7_config = await self.config_manager.get_hl7_listener_config(self.settings)
            
            # Start DICOM SCP service (standard port)
            if dicom_config.get('auto_start', self.settings.dicom.auto_start_scp):
                try:
                    port = dicom_config.get('port', self.settings.dicom.scp_port)
                    if port > 0:
                        process_id = await self.start_process(
                            ProcessType.DICOM_SCP,
                            {'port': port, 'ssl': False}
                        )
                        started_processes.append(process_id)
                        logger.info(f"Auto-started DICOM SCP service: {process_id} on port {port}")
                except Exception as e:
                    logger.error(f"Failed to auto-start DICOM SCP: {e}")
            
            # Start DICOM SSL SCP service
            ssl_enabled = dicom_config.get('ssl_enabled', self.settings.dicom.ssl_enabled)
            if ssl_enabled:
                try:
                    ssl_port = dicom_config.get('ssl_port', self.settings.dicom.scp_ssl_port)
                    if ssl_port > 0:
                        process_id = await self.start_process(
                            ProcessType.DICOM_SCP,
                            {'port': ssl_port, 'ssl': True}
                        )
                        started_processes.append(process_id)
                        logger.info(f"Auto-started DICOM SSL SCP service: {process_id} on port {ssl_port}")
                except Exception as e:
                    logger.error(f"Failed to auto-start DICOM SSL SCP: {e}")
            
            # Start Web Interface service (includes FHIR endpoints)
            if web_config.get('enabled', self.settings.web.web_interface_enabled):
                try:
                    port = web_config.get('port', self.settings.web.web_port)
                    process_id = await self.start_process(
                        ProcessType.WEB_INTERFACE,
                        {'port': port}
                    )
                    started_processes.append(process_id)
                    logger.info(f"Auto-started web interface service (GUI + FHIR): {process_id} on port {port}")
                except Exception as e:
                    logger.error(f"Failed to auto-start web interface: {e}")
            
            # Start SSH server service
            if ssh_config.get('enabled', self.settings.ssh.ssh_enabled):
                try:
                    port = ssh_config.get('port', self.settings.ssh.ssh_port)
                    process_id = await self.start_process(
                        ProcessType.SSH_SERVER,
                        {'port': port}
                    )
                    started_processes.append(process_id)
                    logger.info(f"Auto-started SSH server service: {process_id} on port {port}")
                except Exception as e:
                    logger.error(f"Failed to auto-start SSH server: {e}")
            
            # Start HL7/FHIR listener service
            if hl7_config.get('enabled', self.settings.hl7.hl7_enabled):
                try:
                    port = hl7_config.get('port', self.settings.hl7.hl7_port)
                    process_id = await self.start_process(
                        ProcessType.HL7_LISTENER,
                        {'port': port}
                    )
                    started_processes.append(process_id)
                    logger.info(f"Auto-started HL7/FHIR listener service: {process_id} on port {port}")
                except Exception as e:
                    logger.error(f"Failed to auto-start HL7 listener: {e}")
            
            # Record auto-started services in database for persistence
            await self._record_auto_started_services(started_processes)
            
            logger.info(f"Auto-started {len(started_processes)} core services")
            return started_processes
            
        except Exception as e:
            logger.error(f"Error during auto-start of core services: {e}")
            return started_processes
    
    async def _record_auto_started_services(self, process_ids: List[str]) -> None:
        """
        Record auto-started services in database
        
        Args:
            process_ids: List of process IDs that were auto-started
        """
        try:
            # Create services table if not exists
            create_table_query = """
                CREATE TABLE IF NOT EXISTS service (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service_id TEXT UNIQUE NOT NULL,
                    instance_id TEXT NOT NULL,
                    service_type TEXT NOT NULL,
                    service_name TEXT,
                    auto_started BOOLEAN DEFAULT FALSE,
                    execution_mode TEXT DEFAULT 'thread',
                    host TEXT DEFAULT '0.0.0.0',
                    port INTEGER,
                    ssl_enabled BOOLEAN DEFAULT FALSE,
                    target_host TEXT,
                    target_port INTEGER,
                    config_json TEXT,
                    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_heartbeat DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_ping DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'running',
                    pid INTEGER,
                    manager_id TEXT
                )
            """
            await self.db_manager.execute_query(create_table_query)
            
            # Create indexes for efficient querying
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_service_type ON service(service_type)",
                "CREATE INDEX IF NOT EXISTS idx_service_id ON service(service_id)",
                "CREATE INDEX IF NOT EXISTS idx_status ON service(status)",
                "CREATE INDEX IF NOT EXISTS idx_instance_id ON service(instance_id)",
                "CREATE INDEX IF NOT EXISTS idx_manager_id ON service(manager_id)",
                "CREATE INDEX IF NOT EXISTS idx_service_name ON service(service_name)",
                "CREATE INDEX IF NOT EXISTS idx_last_ping ON service(last_ping)"
            ]
            
            for index_query in indexes:
                await self.db_manager.execute_query(index_query)
            
            # Record each auto-started service
            for process_id in process_ids:
                if process_id in self.processes:
                    process_info = self.processes[process_id]
                    
                    # Generate instance ID for this service instance
                    instance_id = f"{process_info.process_type.value}_{uuid.uuid4().hex[:8]}"
                    
                current_time = datetime.now().isoformat()
                await self.db_manager.execute_query(
                    """
                    INSERT OR REPLACE INTO service 
                    (service_id, instance_id, service_type, service_name, auto_started, 
                     execution_mode, port, ssl_enabled, config_json, last_ping, status, pid, manager_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        process_id,
                        instance_id,
                        process_info.process_type.value,
                        f"{process_info.process_type.value}_auto",
                        True,
                        'thread',  # Default to thread for now
                        process_info.metadata.get('port'),
                        process_info.metadata.get('ssl', False),
                        json.dumps(process_info.metadata),
                        current_time,
                        'running',
                        os.getpid(),
                        self._manager_id
                    )
                )
            
            logger.info(f"Recorded {len(process_ids)} auto-started services in database")
            
        except Exception as e:
            logger.error(f"Failed to record auto-started services: {e}")
    
    async def start_service_instances(
        self,
        process_type: ProcessType,
        instance_configs: List[Dict[str, Any]],
        execution_mode: Optional[ExecutionMode] = None
    ) -> List[str]:
        """
        Start multiple service instances with specific configurations
        
        Args:
            process_type: Type of service to start
            instance_configs: List of instance configurations, each with 'name' and other config
            execution_mode: How to execute the services (thread/process/asyncio)
            
        Returns:
            List of service IDs of started instances
        """
        started_services = []
        
        # First check for and clean up stale services
        await self._cleanup_stale_services()
        
        # Determine execution mode
        if execution_mode is None:
            execution_mode = ProcessType.get_default_execution_mode(process_type)
        
        for config in instance_configs:
            try:
                instance_name = config.get('name', f"{process_type.value}_{uuid.uuid4().hex[:6]}")
                
                # Generate unique service ID
                service_id = f"{process_type.value}_{uuid.uuid4().hex[:8]}"
                instance_id = f"{instance_name}_{uuid.uuid4().hex[:6]}"
                
                # Add execution mode to config
                config['execution_mode'] = execution_mode.value
                config['instance_name'] = instance_name
                
                # Start the process using existing start_process method
                process_id = await self.start_process(process_type, config)
                
                # Update the database record with instance information
                current_time = datetime.now().isoformat()
                await self.db_manager.execute_query(
                    """
                    INSERT OR REPLACE INTO service 
                    (service_id, instance_id, service_type, service_name, auto_started, 
                     execution_mode, host, port, ssl_enabled, target_host, target_port,
                     config_json, last_ping, status, pid, manager_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        process_id,
                        instance_id,
                        process_type.value,
                        instance_name,
                        False,  # Not auto-started
                        execution_mode.value,
                        config.get('host', '0.0.0.0'),
                        config.get('port'),
                        config.get('ssl', False),
                        config.get('target_host'),
                        config.get('target_port'),
                        json.dumps(config),
                        current_time,
                        'running',
                        os.getpid(),
                        self._manager_id
                    )
                )
                
                started_services.append(process_id)
                logger.info(f"Started service instance: {instance_name} ({process_type.value}) with ID: {process_id}")
                
            except Exception as e:
                logger.error(f"Failed to start service instance {config.get('name', 'unnamed')}: {e}")
                continue
        
        logger.info(f"Started {len(started_services)} of {len(instance_configs)} requested {process_type.value} instances")
        return started_services
    
    async def stop_service_instances(self, identifiers: List[str]) -> Dict[str, bool]:
        """
        Stop multiple service instances by various identifiers
        
        Args:
            identifiers: List of service IDs, instance names, or service types to stop
                       Examples: ['service_id_123', 'hl7_listener', 'emergency_scp']
            
        Returns:
            Dict mapping each identifier to success status
        """
        results = {}
        services_to_stop = set()
        
        try:
            # Get all current services from database
            all_services = await self.db_manager.execute_query(
                "SELECT service_id, instance_id, service_type, service_name FROM service WHERE status = 'running'"
            )
            
            # Build lookup maps
            service_map = {row['service_id']: row for row in all_services}
            name_map = {row['service_name']: row for row in all_services if row['service_name']}
            type_map = {}
            for row in all_services:
                if row['service_type'] not in type_map:
                    type_map[row['service_type']] = []
                type_map[row['service_type']].append(row)
            
            # Resolve identifiers to service IDs
            for identifier in identifiers:
                # Check if it's a direct service ID
                if identifier in service_map:
                    services_to_stop.add(identifier)
                    results[identifier] = None  # Will be updated after stopping
                # Check if it's a service name
                elif identifier in name_map:
                    service_id = name_map[identifier]['service_id']
                    services_to_stop.add(service_id)
                    results[identifier] = None
                # Check if it's a service type (stop all of that type)
                elif identifier in type_map:
                    for service in type_map[identifier]:
                        services_to_stop.add(service['service_id'])
                    results[identifier] = None
                else:
                    results[identifier] = False
                    logger.warning(f"No services found matching identifier: {identifier}")
            
            # Stop all identified services
            stop_results = await asyncio.gather(
                *[self._stop_single_service(service_id) for service_id in services_to_stop],
                return_exceptions=True
            )
            
            # Update results based on stop outcomes
            service_ids_list = list(services_to_stop)
            for i, result in enumerate(stop_results):
                service_id = service_ids_list[i]
                success = result if isinstance(result, bool) else False
                
                # Find which identifier(s) this service_id corresponds to
                for identifier in identifiers:
                    if identifier in service_map and service_map[identifier]['service_id'] == service_id:
                        results[identifier] = success
                    elif identifier in name_map and name_map[identifier]['service_id'] == service_id:
                        results[identifier] = success
                    elif identifier in type_map:
                        for service in type_map[identifier]:
                            if service['service_id'] == service_id:
                                results[identifier] = success
                                break
            
            logger.info(f"Stopped {sum(1 for r in results.values() if r)} of {len(services_to_stop)} identified services")
            return results
            
        except Exception as e:
            logger.error(f"Failed to stop service instances: {e}")
            # Return failure for all identifiers
            return {identifier: False for identifier in identifiers}
    
    async def _stop_single_service(self, service_id: str) -> bool:
        """
        Stop a single service by ID
        
        Args:
            service_id: Service ID to stop
            
        Returns:
            True if stopped successfully
        """
        try:
            # Stop the process
            success = await self.stop_process(service_id)
            
            if success:
                # Update database record
                current_time = datetime.now().isoformat()
                await self.db_manager.execute_query(
                    "UPDATE service SET status = 'stopped', last_ping = ? WHERE service_id = ?",
                    (current_time, service_id)
                )
                
                logger.info(f"Stopped service instance: {service_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to stop service instance {service_id}: {e}")
            return False
    
    async def list_service_instances(
        self,
        service_type: Optional[ProcessType] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List service instances
        
        Args:
            service_type: Filter by service type
            status: Filter by status
            
        Returns:
            List of service instance information
        """
        try:
            query = "SELECT * FROM service WHERE 1=1"
            params = []
            
            if service_type:
                query += " AND service_type = ?"
                params.append(service_type.value)
            
            if status:
                query += " AND status = ?"
                params.append(status)
            
            query += " ORDER BY started_at DESC"
            
            result = await self.db_manager.execute_query(query, params)
            
            instances = []
            for row in result:
                instance_info = dict(row)
                # Parse config JSON
                if instance_info['config_json']:
                    try:
                        instance_info['config'] = json.loads(instance_info['config_json'])
                    except json.JSONDecodeError:
                        instance_info['config'] = {}
                instances.append(instance_info)
            
            return instances
            
        except Exception as e:
            logger.error(f"Failed to list service instances: {e}")
            return []
    
    async def start_multiple_dicom_scp_instances(self, configs: List[Dict[str, Any]]) -> List[str]:
        """
        Start multiple DICOM SCP instances with different configurations
        
        Args:
            configs: List of SCP configurations, each containing port, ae_title, etc.
            
        Returns:
            List of started service IDs
        """
        # Ensure each config has a name
        for i, config in enumerate(configs):
            if 'name' not in config:
                config['name'] = f"scp_instance_{i+1}"
        
        return await self.start_service_instances(ProcessType.DICOM_SCP, configs)
    
    async def start_multiple_hl7_listeners(self, configs: List[Dict[str, Any]]) -> List[str]:
        """
        Start multiple HL7 listener instances on different ports
        
        Args:
            configs: List of HL7 configurations, each containing port, etc.
            
        Returns:
            List of started service IDs
        """
        # Ensure each config has a name
        for i, config in enumerate(configs):
            if 'name' not in config:
                config['name'] = f"hl7_listener_{i+1}"
        
        return await self.start_service_instances(ProcessType.HL7_LISTENER, configs)
    
    async def _cleanup_stale_services(self) -> int:
        """
        Clean up services that haven't sent a ping in 4*heartbeat_interval
        
        Returns:
            Number of stale services cleaned up
        """
        try:
            # Calculate stale threshold (4 times heartbeat interval)
            heartbeat_interval = getattr(self.settings.redis, 'heartbeat_interval', 30)
            stale_threshold_seconds = 4 * heartbeat_interval
            
            # Find stale services
            stale_query = """
                SELECT service_id, service_name, service_type, last_ping 
                FROM service 
                WHERE status = 'running' 
                AND datetime(last_ping) < datetime('now', '-{} seconds')
            """.format(stale_threshold_seconds)
            
            stale_services = await self.db_manager.execute_query(stale_query)
            
            cleaned_count = 0
            for row in stale_services:
                service_id = row['service_id']
                service_name = row['service_name']
                last_ping = row['last_ping']
                
                logger.warning(f"Found stale service: {service_name} ({service_id}) - last ping: {last_ping}")
                
                # Stop the stale service
                success = await self._stop_single_service(service_id)
                if success:
                    # Mark as stale in database
                    await self.db_manager.execute_query(
                        "UPDATE service SET status = 'stale', last_ping = ? WHERE service_id = ?",
                        (datetime.now().isoformat(), service_id)
                    )
                    cleaned_count += 1
            
            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} stale services")
            
            return cleaned_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup stale services: {e}")
            return 0
    
    async def update_service_ping(self, service_id: str) -> bool:
        """
        Update the last ping time for a service
        
        Args:
            service_id: Service ID to update
            
        Returns:
            True if updated successfully
        """
        try:
            current_time = datetime.now().isoformat()
            result = await self.db_manager.execute_query(
                "UPDATE service SET last_ping = ? WHERE service_id = ? AND status = 'running'",
                (current_time, service_id)
            )
            
            # Check if any rows were affected
            if hasattr(result, 'rowcount') and result.rowcount > 0:
                return True
            else:
                # Try to check if service exists but is not running
                service_check = await self.db_manager.execute_query(
                    "SELECT status FROM service WHERE service_id = ?",
                    (service_id,)
                )
                if service_check:
                    logger.debug(f"Service {service_id} exists but status is: {service_check[0]['status']}")
                return False
            
        except Exception as e:
            logger.error(f"Failed to update service ping for {service_id}: {e}")
            return False
    
    async def cleanup_stopped_services(self) -> int:
        """
        Clean up database records for stopped services that are no longer in memory
        
        Returns:
            Number of records cleaned up
        """
        try:
            # Remove stopped services that are no longer in memory
            stopped_services = await self.db_manager.execute_query(
                "SELECT service_id FROM service WHERE status IN ('stopped', 'stale')"
            )
            
            cleaned_count = 0
            for row in stopped_services:
                service_id = row['service_id']
                if service_id not in self.processes:
                    await self.db_manager.execute_query(
                        "DELETE FROM service WHERE service_id = ?",
                        (service_id,)
                    )
                    cleaned_count += 1
            
            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} stopped service records")
            
            return cleaned_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup stopped services: {e}")
            return 0
    
    # Configuration management methods
    async def get_service_config(self, service_name: str) -> Dict[str, Any]:
        """
        Get configuration for a service
        
        Args:
            service_name: Name of the service
            
        Returns:
            Service configuration dictionary
        """
        return await self.config_manager.get_service_config(service_name, self.settings)
    
    async def set_service_config(self, service_name: str, config_name: str, value: Any) -> bool:
        """
        Set a service configuration value
        
        Args:
            service_name: Name of the service
            config_name: Configuration parameter name
            value: Value to set
            
        Returns:
            True if successful
        """
        return await self.config_manager.set_config_value(service_name, config_name, value)
    
    async def list_all_configs(self) -> Dict[str, Dict[str, Any]]:
        """
        List all service configurations
        
        Returns:
            All service configurations
        """
        return await self.config_manager.get_all_service_configs()
    
    # Convenience methods for single instance operations
    async def start_service_instance(
        self,
        process_type: ProcessType,
        instance_name: str,
        config: Dict[str, Any],
        execution_mode: Optional[ExecutionMode] = None
    ) -> str:
        """
        Start a single service instance
        
        Args:
            process_type: Type of service to start
            instance_name: Human-readable name for this instance
            config: Service-specific configuration
            execution_mode: How to execute the service (thread/process/asyncio)
            
        Returns:
            Service ID of started instance
        """
        config['name'] = instance_name
        result = await self.start_service_instances(process_type, [config], execution_mode)
        return result[0] if result else None
    
    async def stop_service_instance(self, identifier: str) -> bool:
        """
        Stop a single service instance
        
        Args:
            identifier: Service ID, instance name, or service type
            
        Returns:
            True if stopped successfully
        """
        results = await self.stop_service_instances([identifier])
        return results.get(identifier, False)


# Export commonly used classes
__all__ = [
    'ProcessManager',
    'ProcessState',
    'ProcessType',
    'ProcessInfo',
    'ExecutionMode'
]
