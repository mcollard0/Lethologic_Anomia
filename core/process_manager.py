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
from .logging import get_logger, LogPollingService

logger = get_logger(__name__)


class ProcessState(Enum):
    """Process states"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class ProcessType(Enum):
    """Process types"""
    WEB_INTERFACE = "web_interface"
    SSH_SERVER = "ssh_server"
    DICOM_SCP = "dicom_scp"
    DICOM_SCU = "dicom_scu"
    DICOM_SEARCH = "dicom_search"
    DICOM_PARSER = "dicom_parser"
    HL7_LISTENER = "hl7_listener"
    HL7_PROCESSOR = "hl7_processor"
    AI_PROCESSOR = "ai_processor"
    LOG_POLLER = "log_poller"


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
        # For now, create placeholder tasks that will be implemented later
        # This allows the process manager to work without requiring all services to be implemented
        
        async def placeholder_service():
            """Placeholder service that runs indefinitely"""
            logger.info(f"Starting placeholder service for {process_type.value}")
            try:
                while True:
                    await asyncio.sleep(60)  # Sleep for 1 minute
                    logger.debug(f"Placeholder service {process_type.value} heartbeat")
            except asyncio.CancelledError:
                logger.info(f"Placeholder service {process_type.value} cancelled")
                raise
            except Exception as e:
                logger.error(f"Placeholder service {process_type.value} error: {e}")
                raise
        
        return asyncio.create_task(placeholder_service(), name=f"{process_type.value}_{process_id}")
    
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
                
                # Update heartbeats for all managed processes
                for process_info in self.processes.values():
                    if process_info.state == ProcessState.RUNNING:
                        process_info.last_heartbeat = datetime.now()
                
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


# Export commonly used classes
__all__ = [
    'ProcessManager',
    'ProcessState',
    'ProcessType',
    'ProcessInfo'
]
