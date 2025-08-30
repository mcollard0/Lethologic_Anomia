"""
HL7 Processor Service

Processes HL7 messages, manages workflows, and provides message routing
and transformation capabilities for healthcare data integration.
"""

import asyncio
import json
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import hl7

from ...core.logging import get_logger
from ...core.database import DatabaseManager
from ...core.config import Settings
from .fhir_interface import FHIRInterface

logger = get_logger(__name__)


class MessageStatus(Enum):
    """HL7 Message Processing Status"""
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    RETRYING = "retrying"


class WorkflowStep(Enum):
    """HL7 Workflow Processing Steps"""
    VALIDATE = "validate"
    TRANSFORM = "transform"
    ROUTE = "route"
    STORE = "store"
    FHIR_CONVERT = "fhir_convert"
    NOTIFY = "notify"


@dataclass
class MessageWorkflow:
    """HL7 Message Workflow Configuration"""
    workflow_id: str
    message_type: str
    steps: List[WorkflowStep]
    retry_count: int = 3
    retry_delay_seconds: int = 60
    enabled: bool = True


@dataclass
class ProcessingResult:
    """Message Processing Result"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class HL7Processor:
    """
    HL7 Processor Service
    
    Provides comprehensive HL7 message processing:
    - Message validation and transformation
    - Workflow management and routing
    - FHIR conversion integration
    - Message queuing and retry logic
    - Database storage and auditing
    - Performance monitoring
    """
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings, 
                 fhir_interface: Optional[FHIRInterface] = None):
        """
        Initialize HL7 processor
        
        Args:
            db_manager: Database manager instance
            settings: Application settings
            fhir_interface: Optional FHIR interface for conversions
        """
        self.db_manager = db_manager
        self.settings = settings
        self.fhir_interface = fhir_interface
        
        # Configuration
        self.is_configured = False
        self.is_running = False
        
        # Default configuration
        self.config = {
            'max_concurrent_messages': 50,
            'message_timeout_seconds': 300,
            'retry_max_attempts': 3,
            'retry_base_delay': 60,
            'enable_fhir_conversion': True,
            'enable_message_validation': True,
            'workflow_batch_size': 10
        }
        
        # Message processing
        self.message_queue: asyncio.Queue = asyncio.Queue()
        self.processing_tasks: Dict[str, asyncio.Task] = {}
        self.worker_tasks: List[asyncio.Task] = []
        
        # Workflows
        self.workflows: Dict[str, MessageWorkflow] = {}
        self.setup_default_workflows()
        
        # Message handlers
        self.message_handlers: Dict[str, Callable] = {}
        self.setup_message_handlers()
        
        # Processing statistics
        self.messages_queued = 0
        self.messages_processed = 0
        self.messages_failed = 0
        self.processing_errors = 0
        self.fhir_conversions = 0
        self.retry_attempts = 0
        
        logger.info("HL7 Processor Service initialized")
    
    def configure(self, config: Dict[str, Any]) -> bool:
        """
        Configure the HL7 processor
        
        Args:
            config: Configuration dictionary
            
        Returns:
            True if configuration successful
        """
        try:
            self.config.update(config)
            self.is_configured = True
            logger.info(f"HL7 processor configured with {self.config['max_concurrent_messages']} max concurrent messages")
            return True
            
        except Exception as e:
            logger.error(f"Failed to configure HL7 processor: {e}")
            return False
    
    def setup_default_workflows(self):
        """Setup default message workflows"""
        self.workflows = {
            'ADT_default': MessageWorkflow(
                workflow_id='ADT_default',
                message_type='ADT',
                steps=[WorkflowStep.VALIDATE, WorkflowStep.STORE, WorkflowStep.FHIR_CONVERT],
                retry_count=3
            ),
            'ORM_default': MessageWorkflow(
                workflow_id='ORM_default',
                message_type='ORM',
                steps=[WorkflowStep.VALIDATE, WorkflowStep.STORE, WorkflowStep.FHIR_CONVERT],
                retry_count=3
            ),
            'ORU_default': MessageWorkflow(
                workflow_id='ORU_default',
                message_type='ORU',
                steps=[WorkflowStep.VALIDATE, WorkflowStep.STORE, WorkflowStep.FHIR_CONVERT],
                retry_count=3
            ),
            'ACK_simple': MessageWorkflow(
                workflow_id='ACK_simple',
                message_type='ACK',
                steps=[WorkflowStep.VALIDATE, WorkflowStep.STORE],
                retry_count=1
            )
        }
    
    def setup_message_handlers(self):
        """Setup message type handlers"""
        self.message_handlers = {
            'ADT': self._handle_adt_message,
            'ORM': self._handle_orm_message,
            'ORU': self._handle_oru_message,
            'ACK': self._handle_ack_message,
            'QRY': self._handle_qry_message,
            'DSR': self._handle_dsr_message
        }
    
    async def start(self) -> bool:
        """
        Start the HL7 processor service
        
        Returns:
            True if started successfully
        """
        if not self.is_configured:
            # Use default configuration
            if not self.configure({}):
                logger.error("Failed to configure HL7 processor with defaults")
                return False
        
        if self.is_running:
            logger.warning("HL7 processor already running")
            return True
        
        try:
            # Load workflows from database
            await self._load_workflows_from_db()
            
            # Start worker tasks
            worker_count = min(self.config['max_concurrent_messages'], 10)
            for i in range(worker_count):
                task = asyncio.create_task(
                    self._message_worker(f"worker-{i}")
                )
                self.worker_tasks.append(task)
            
            # Start cleanup task
            cleanup_task = asyncio.create_task(self._cleanup_completed_tasks())
            self.worker_tasks.append(cleanup_task)
            
            self.is_running = True
            logger.info(f"HL7 processor started with {worker_count} workers")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start HL7 processor: {e}")
            return False
    
    async def stop(self) -> bool:
        """
        Stop the HL7 processor service
        
        Returns:
            True if stopped successfully
        """
        if not self.is_running:
            return True
        
        try:
            logger.info("Stopping HL7 processor...")
            
            self.is_running = False
            
            # Cancel all worker tasks
            for task in self.worker_tasks:
                if not task.done():
                    task.cancel()
            
            # Wait for tasks to complete
            if self.worker_tasks:
                await asyncio.gather(*self.worker_tasks, return_exceptions=True)
            
            # Cancel any remaining processing tasks
            for task in self.processing_tasks.values():
                if not task.done():
                    task.cancel()
            
            # Clear queues and tasks
            self.worker_tasks.clear()
            self.processing_tasks.clear()
            
            logger.info("HL7 processor stopped")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping HL7 processor: {e}")
            return False
    
    async def process_message(self, hl7_message, source_address: str = "unknown") -> str:
        """
        Queue HL7 message for processing
        
        Args:
            hl7_message: Parsed HL7 message
            source_address: Source address of the message
            
        Returns:
            Processing ID for tracking
        """
        try:
            # Generate processing ID
            processing_id = f"hl7_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self.messages_queued}"
            
            # Create message data
            message_data = {
                'processing_id': processing_id,
                'hl7_message': hl7_message,
                'source_address': source_address,
                'queued_at': datetime.now(),
                'retry_count': 0
            }
            
            # Add to queue
            await self.message_queue.put(message_data)
            self.messages_queued += 1
            
            logger.info(f"Queued HL7 message for processing: {processing_id}")
            return processing_id
            
        except Exception as e:
            logger.error(f"Error queuing HL7 message: {e}")
            self.processing_errors += 1
            raise
    
    async def _message_worker(self, worker_name: str):
        """
        Message processing worker
        
        Args:
            worker_name: Name of the worker
        """
        logger.info(f"HL7 message worker {worker_name} started")
        
        while self.is_running:
            try:
                # Get message from queue with timeout
                try:
                    message_data = await asyncio.wait_for(
                        self.message_queue.get(),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Process the message
                processing_id = message_data['processing_id']
                logger.debug(f"Worker {worker_name} processing message: {processing_id}")
                
                # Create processing task
                task = asyncio.create_task(
                    self._process_message_workflow(message_data)
                )
                self.processing_tasks[processing_id] = task
                
                # Wait for completion
                try:
                    await task
                except Exception as e:
                    logger.error(f"Message processing failed for {processing_id}: {e}")
                    self.processing_errors += 1
                
                # Mark queue task done
                self.message_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {worker_name} error: {e}")
                await asyncio.sleep(1)
        
        logger.info(f"HL7 message worker {worker_name} stopped")
    
    async def _process_message_workflow(self, message_data: Dict[str, Any]):
        """
        Process HL7 message through workflow
        
        Args:
            message_data: Message processing data
        """
        processing_id = message_data['processing_id']
        hl7_message = message_data['hl7_message']
        
        try:
            # Update processing status
            await self._update_processing_status(
                processing_id, MessageStatus.PROCESSING,
                "Starting message processing workflow"
            )
            
            # Get message type
            message_type = self._extract_message_type(hl7_message)
            if not message_type:
                raise ValueError("Could not determine message type")
            
            # Get workflow for message type
            workflow = self._get_workflow_for_message(message_type)
            if not workflow:
                logger.warning(f"No workflow found for message type: {message_type}")
                workflow = self._get_default_workflow()
            
            # Execute workflow steps
            for step in workflow.steps:
                result = await self._execute_workflow_step(
                    step, hl7_message, message_data, workflow
                )
                
                if not result.success:
                    error_msg = f"Workflow step {step.value} failed: {result.error}"
                    logger.error(error_msg)
                    
                    # Check if retry is needed
                    if message_data['retry_count'] < workflow.retry_count:
                        await self._schedule_message_retry(message_data, workflow, error_msg)
                        return
                    else:
                        # Max retries exceeded
                        await self._update_processing_status(
                            processing_id, MessageStatus.FAILED, error_msg
                        )
                        self.messages_failed += 1
                        return
            
            # All steps completed successfully
            await self._update_processing_status(
                processing_id, MessageStatus.PROCESSED,
                "Message processing completed successfully"
            )
            self.messages_processed += 1
            logger.info(f"Successfully processed message: {processing_id}")
            
        except Exception as e:
            error_msg = f"Message processing error: {str(e)}"
            logger.error(f"Processing failed for {processing_id}: {e}")
            
            # Check if retry is needed
            if message_data['retry_count'] < self.config['retry_max_attempts']:
                await self._schedule_message_retry(message_data, None, error_msg)
            else:
                await self._update_processing_status(
                    processing_id, MessageStatus.FAILED, error_msg
                )
                self.messages_failed += 1
    
    async def _execute_workflow_step(self, step: WorkflowStep, hl7_message,
                                   message_data: Dict[str, Any], 
                                   workflow: MessageWorkflow) -> ProcessingResult:
        """
        Execute a single workflow step
        
        Args:
            step: Workflow step to execute
            hl7_message: HL7 message being processed
            message_data: Message processing data
            workflow: Workflow configuration
            
        Returns:
            Processing result
        """
        try:
            if step == WorkflowStep.VALIDATE:
                return await self._validate_message(hl7_message, message_data)
            elif step == WorkflowStep.TRANSFORM:
                return await self._transform_message(hl7_message, message_data)
            elif step == WorkflowStep.ROUTE:
                return await self._route_message(hl7_message, message_data)
            elif step == WorkflowStep.STORE:
                return await self._store_message(hl7_message, message_data)
            elif step == WorkflowStep.FHIR_CONVERT:
                return await self._convert_to_fhir(hl7_message, message_data)
            elif step == WorkflowStep.NOTIFY:
                return await self._notify_stakeholders(hl7_message, message_data)
            else:
                return ProcessingResult(
                    success=False,
                    message=f"Unknown workflow step: {step}",
                    error=f"Step {step} not implemented"
                )
                
        except Exception as e:
            logger.error(f"Workflow step {step} error: {e}")
            return ProcessingResult(
                success=False,
                message=f"Step {step} failed",
                error=str(e)
            )
    
    async def _validate_message(self, hl7_message, message_data: Dict[str, Any]) -> ProcessingResult:
        """Validate HL7 message"""
        try:
            if not self.config['enable_message_validation']:
                return ProcessingResult(success=True, message="Validation skipped")
            
            # Basic validation checks
            if not hl7_message or len(hl7_message) == 0:
                return ProcessingResult(
                    success=False,
                    message="Empty message",
                    error="Message has no segments"
                )
            
            # Check MSH segment
            msh_segment = hl7_message[0]
            if str(msh_segment[0]) != 'MSH':
                return ProcessingResult(
                    success=False,
                    message="Invalid MSH segment",
                    error="First segment is not MSH"
                )
            
            # Additional validation based on message type
            message_type = self._extract_message_type(hl7_message)
            if message_type == 'ADT':
                # Check for PID segment
                has_pid = any(str(seg[0]) == 'PID' for seg in hl7_message)
                if not has_pid:
                    return ProcessingResult(
                        success=False,
                        message="ADT missing PID segment",
                        error="ADT messages require PID segment"
                    )
            
            return ProcessingResult(success=True, message="Message validation passed")
            
        except Exception as e:
            return ProcessingResult(
                success=False,
                message="Validation error",
                error=str(e)
            )
    
    async def _transform_message(self, hl7_message, message_data: Dict[str, Any]) -> ProcessingResult:
        """Transform HL7 message"""
        try:
            # Basic transformation - could be extended for specific transformations
            logger.debug(f"Transforming message: {message_data['processing_id']}")
            
            # For now, just pass through
            return ProcessingResult(success=True, message="Message transformation completed")
            
        except Exception as e:
            return ProcessingResult(
                success=False,
                message="Transformation error",
                error=str(e)
            )
    
    async def _route_message(self, hl7_message, message_data: Dict[str, Any]) -> ProcessingResult:
        """Route HL7 message to appropriate handlers"""
        try:
            message_type = self._extract_message_type(hl7_message)
            handler = self.message_handlers.get(message_type)
            
            if handler:
                success = await handler(hl7_message, message_data)
                if success:
                    return ProcessingResult(success=True, message="Message routed successfully")
                else:
                    return ProcessingResult(
                        success=False,
                        message="Message routing failed",
                        error="Handler returned false"
                    )
            else:
                logger.warning(f"No handler for message type: {message_type}")
                return ProcessingResult(success=True, message="No routing handler, skipped")
                
        except Exception as e:
            return ProcessingResult(
                success=False,
                message="Routing error",
                error=str(e)
            )
    
    async def _store_message(self, hl7_message, message_data: Dict[str, Any]) -> ProcessingResult:
        """Store HL7 message in database"""
        try:
            message_type = self._extract_message_type(hl7_message)
            message_text = str(hl7_message)
            
            await self.db_manager.execute_query(
                """
                INSERT INTO hl7_messages 
                (processing_id, message_type, message_text, source_address, received_at, processed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    message_data['processing_id'],
                    message_type,
                    message_text,
                    message_data['source_address'],
                    message_data['queued_at'].isoformat(),
                    datetime.now().isoformat()
                ]
            )
            
            return ProcessingResult(success=True, message="Message stored in database")
            
        except Exception as e:
            return ProcessingResult(
                success=False,
                message="Storage error",
                error=str(e)
            )
    
    async def _convert_to_fhir(self, hl7_message, message_data: Dict[str, Any]) -> ProcessingResult:
        """Convert HL7 message to FHIR"""
        try:
            if not self.config['enable_fhir_conversion'] or not self.fhir_interface:
                return ProcessingResult(success=True, message="FHIR conversion skipped")
            
            message_type = self._extract_message_type(hl7_message)
            fhir_resource = await self.fhir_interface.convert_hl7_to_fhir(hl7_message, message_type)
            
            if fhir_resource:
                # Try to create the resource
                created_resource = await self.fhir_interface.create_resource(
                    fhir_resource.resource_type,
                    fhir_resource.data
                )
                
                if created_resource:
                    self.fhir_conversions += 1
                    return ProcessingResult(
                        success=True,
                        message="FHIR resource created",
                        data={'fhir_resource_id': created_resource.resource_id}
                    )
                else:
                    return ProcessingResult(
                        success=False,
                        message="FHIR resource creation failed",
                        error="Failed to create FHIR resource"
                    )
            else:
                return ProcessingResult(success=True, message="FHIR conversion not supported for this message type")
                
        except Exception as e:
            return ProcessingResult(
                success=False,
                message="FHIR conversion error",
                error=str(e)
            )
    
    async def _notify_stakeholders(self, hl7_message, message_data: Dict[str, Any]) -> ProcessingResult:
        """Notify stakeholders of message processing"""
        try:
            # Basic notification - could be extended for webhooks, emails, etc.
            logger.debug(f"Notifying stakeholders for message: {message_data['processing_id']}")
            
            return ProcessingResult(success=True, message="Stakeholder notification completed")
            
        except Exception as e:
            return ProcessingResult(
                success=False,
                message="Notification error",
                error=str(e)
            )
    
    async def _schedule_message_retry(self, message_data: Dict[str, Any], 
                                    workflow: Optional[MessageWorkflow], error_msg: str):
        """Schedule message for retry"""
        try:
            processing_id = message_data['processing_id']
            message_data['retry_count'] += 1
            
            # Calculate retry delay
            retry_delay = workflow.retry_delay_seconds if workflow else self.config['retry_base_delay']
            retry_delay *= message_data['retry_count']  # Exponential backoff
            
            # Update status
            await self._update_processing_status(
                processing_id, MessageStatus.RETRYING,
                f"Retry {message_data['retry_count']} scheduled: {error_msg}"
            )
            
            # Schedule retry
            await asyncio.sleep(retry_delay)
            await self.message_queue.put(message_data)
            
            self.retry_attempts += 1
            logger.info(f"Scheduled retry {message_data['retry_count']} for message: {processing_id}")
            
        except Exception as e:
            logger.error(f"Error scheduling retry: {e}")
    
    async def _handle_adt_message(self, hl7_message, message_data: Dict[str, Any]) -> bool:
        """Handle ADT message"""
        try:
            logger.debug(f"Processing ADT message: {message_data['processing_id']}")
            # ADT-specific processing logic here
            return True
        except Exception as e:
            logger.error(f"ADT message handling error: {e}")
            return False
    
    async def _handle_orm_message(self, hl7_message, message_data: Dict[str, Any]) -> bool:
        """Handle ORM message"""
        try:
            logger.debug(f"Processing ORM message: {message_data['processing_id']}")
            # ORM-specific processing logic here
            return True
        except Exception as e:
            logger.error(f"ORM message handling error: {e}")
            return False
    
    async def _handle_oru_message(self, hl7_message, message_data: Dict[str, Any]) -> bool:
        """Handle ORU message"""
        try:
            logger.debug(f"Processing ORU message: {message_data['processing_id']}")
            # ORU-specific processing logic here
            return True
        except Exception as e:
            logger.error(f"ORU message handling error: {e}")
            return False
    
    async def _handle_ack_message(self, hl7_message, message_data: Dict[str, Any]) -> bool:
        """Handle ACK message"""
        try:
            logger.debug(f"Processing ACK message: {message_data['processing_id']}")
            # ACK-specific processing logic here
            return True
        except Exception as e:
            logger.error(f"ACK message handling error: {e}")
            return False
    
    async def _handle_qry_message(self, hl7_message, message_data: Dict[str, Any]) -> bool:
        """Handle QRY message"""
        try:
            logger.debug(f"Processing QRY message: {message_data['processing_id']}")
            # QRY-specific processing logic here
            return True
        except Exception as e:
            logger.error(f"QRY message handling error: {e}")
            return False
    
    async def _handle_dsr_message(self, hl7_message, message_data: Dict[str, Any]) -> bool:
        """Handle DSR message"""
        try:
            logger.debug(f"Processing DSR message: {message_data['processing_id']}")
            # DSR-specific processing logic here
            return True
        except Exception as e:
            logger.error(f"DSR message handling error: {e}")
            return False
    
    def _extract_message_type(self, hl7_message) -> Optional[str]:
        """Extract message type from HL7 message"""
        try:
            if len(hl7_message) > 0 and len(hl7_message[0]) > 8:
                return str(hl7_message[0][8])[:3]  # MSH.9.1
            return None
        except:
            return None
    
    def _get_workflow_for_message(self, message_type: str) -> Optional[MessageWorkflow]:
        """Get workflow for message type"""
        return self.workflows.get(f"{message_type}_default")
    
    def _get_default_workflow(self) -> MessageWorkflow:
        """Get default workflow"""
        return MessageWorkflow(
            workflow_id="default",
            message_type="UNKNOWN",
            steps=[WorkflowStep.VALIDATE, WorkflowStep.STORE],
            retry_count=1
        )
    
    async def _update_processing_status(self, processing_id: str, status: MessageStatus, message: str):
        """Update message processing status"""
        try:
            await self.db_manager.execute_query(
                """
                INSERT OR REPLACE INTO hl7_processing_status 
                (processing_id, status, message, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                [processing_id, status.value, message, datetime.now().isoformat()]
            )
        except Exception as e:
            logger.error(f"Failed to update processing status: {e}")
    
    async def _load_workflows_from_db(self):
        """Load workflows from database"""
        try:
            result = await self.db_manager.execute_query(
                "SELECT workflow_id, message_type, steps, retry_count, retry_delay_seconds, enabled FROM hl7_workflows"
            )
            
            for row in result:
                steps = [WorkflowStep(step) for step in json.loads(row['steps'])]
                workflow = MessageWorkflow(
                    workflow_id=row['workflow_id'],
                    message_type=row['message_type'],
                    steps=steps,
                    retry_count=row['retry_count'],
                    retry_delay_seconds=row['retry_delay_seconds'],
                    enabled=bool(row['enabled'])
                )
                self.workflows[workflow.workflow_id] = workflow
                
            logger.info(f"Loaded {len(result)} workflows from database")
            
        except Exception as e:
            logger.warning(f"Failed to load workflows from database: {e}")
    
    async def _cleanup_completed_tasks(self):
        """Cleanup completed processing tasks"""
        while self.is_running:
            try:
                # Clean up completed tasks every 60 seconds
                await asyncio.sleep(60)
                
                completed_tasks = [
                    task_id for task_id, task in self.processing_tasks.items()
                    if task.done()
                ]
                
                for task_id in completed_tasks:
                    del self.processing_tasks[task_id]
                
                if completed_tasks:
                    logger.debug(f"Cleaned up {len(completed_tasks)} completed processing tasks")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Task cleanup error: {e}")
                await asyncio.sleep(10)
    
    async def get_processing_status(self, processing_id: str) -> Optional[Dict[str, Any]]:
        """
        Get processing status for a message
        
        Args:
            processing_id: Processing ID to check
            
        Returns:
            Processing status information
        """
        try:
            result = await self.db_manager.execute_query(
                "SELECT * FROM hl7_processing_status WHERE processing_id = ? ORDER BY updated_at DESC LIMIT 1",
                [processing_id]
            )
            
            if result:
                return dict(result[0])
            return None
            
        except Exception as e:
            logger.error(f"Error getting processing status: {e}")
            return None
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get HL7 processor statistics"""
        return {
            'is_running': self.is_running,
            'is_configured': self.is_configured,
            'messages_queued': self.messages_queued,
            'messages_processed': self.messages_processed,
            'messages_failed': self.messages_failed,
            'processing_errors': self.processing_errors,
            'fhir_conversions': self.fhir_conversions,
            'retry_attempts': self.retry_attempts,
            'active_processing_tasks': len(self.processing_tasks),
            'queue_size': self.message_queue.qsize(),
            'workflows_loaded': len(self.workflows),
            'config': {
                'max_concurrent_messages': self.config['max_concurrent_messages'],
                'enable_fhir_conversion': self.config['enable_fhir_conversion'],
                'enable_message_validation': self.config['enable_message_validation'],
                'retry_max_attempts': self.config['retry_max_attempts']
            }
        }


__all__ = ['HL7Processor', 'MessageStatus', 'WorkflowStep', 'MessageWorkflow', 'ProcessingResult']
