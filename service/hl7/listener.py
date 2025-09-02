"""
HL7 Listener Service

Listens for incoming HL7 messages from healthcare systems and processes
ADT (Admission, Discharge, Transfer) and Order messages.
"""

import asyncio
import socket
import threading
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime
import hl7

from ...core.logging import get_logger
from ...core.database import DatabaseManager
from ...core.config import Settings

logger = get_logger(__name__)


class HL7Listener:
    """
    HL7 Listener Service
    
    Listens for HL7 messages over TCP/IP and processes healthcare data:
    - ADT messages (patient admissions, discharges, transfers)
    - ORM messages (orders)
    - ORU messages (results)
    - ACK acknowledgments
    """
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        """
        Initialize HL7 listener
        
        Args:
            db_manager: Database manager instance
            settings: Application settings
        """
        self.db_manager = db_manager
        self.settings = settings
        
        # Configuration
        self.is_configured = False
        self.is_running = False
        
        # Default configuration
        self.config = {
            'port': 59999,
            'host': '0.0.0.0',
            'max_connections': 100,
            'message_timeout': 30,
            'encoding': 'utf-8'
        }
        
        # Server components
        self.server_socket: Optional[socket.socket] = None
        self.server_thread: Optional[threading.Thread] = None
        
        # Message processing
        self.message_handlers: Dict[str, Callable] = {}
        self.setup_message_handlers()
        
        # Statistics
        self.messages_received = 0
        self.messages_processed = 0
        self.messages_failed = 0
        self.connections_accepted = 0
        self.active_connections = 0
        
        logger.info("HL7 Listener Service initialized")
    
    def configure(self, config: Dict[str, Any]) -> bool:
        """
        Configure the HL7 listener
        
        Args:
            config: Configuration dictionary
            
        Returns:
            True if configuration successful
        """
        try:
            self.config.update(config)
            self.is_configured = True
            logger.info(f"HL7 listener configured on {self.config['host']}:{self.config['port']}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to configure HL7 listener: {e}")
            return False
    
    def setup_message_handlers(self):
        """Setup message type handlers"""
        self.message_handlers = {
            'ADT': self._handle_adt_message,  # Admission/Discharge/Transfer
            'ORM': self._handle_orm_message,  # Order Message
            'ORU': self._handle_oru_message,  # Observation Result
            'ACK': self._handle_ack_message,  # Acknowledgment
            'QRY': self._handle_qry_message,  # Query
            'DSR': self._handle_dsr_message   # Display Response
        }
    
    def start(self) -> bool:
        """
        Start the HL7 listener service
        
        Returns:
            True if started successfully
        """
        if not self.is_configured:
            # Use default configuration
            if not self.configure({}):
                logger.error("Failed to configure HL7 listener with defaults")
                return False
        
        if self.is_running:
            logger.warning("HL7 listener already running")
            return True
        
        try:
            # Create server socket
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.config['host'], self.config['port']))
            self.server_socket.listen(self.config['max_connections'])
            
            # Start server thread
            self.server_thread = threading.Thread(
                target=self._run_server,
                daemon=True,
                name=f"HL7Listener-{self.config['port']}"
            )
            self.server_thread.start()
            
            self.is_running = True
            logger.info(f"HL7 listener started on {self.config['host']}:{self.config['port']}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start HL7 listener: {e}")
            return False
    
    def _run_server(self):
        """Run the HL7 server loop"""
        try:
            while self.is_running:
                try:
                    # Accept connection with timeout
                    self.server_socket.settimeout(1.0)
                    client_socket, address = self.server_socket.accept()
                    self.server_socket.settimeout(None)
                    
                    logger.info(f"HL7 connection from {address}")
                    
                    # Handle connection in separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client_socket, address),
                        daemon=True
                    )
                    client_thread.start()
                    
                    self.connections_accepted += 1
                    
                except socket.timeout:
                    # Timeout is expected, continue loop
                    continue
                except Exception as e:
                    if self.is_running:  # Only log if we're supposed to be running
                        logger.error(f"Error accepting HL7 connection: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"HL7 server error: {e}")
        finally:
            if self.server_socket:
                self.server_socket.close()
    
    def _handle_client(self, client_socket: socket.socket, address: tuple):
        """Handle HL7 client connection"""
        try:
            self.active_connections += 1
            client_socket.settimeout(self.config['message_timeout'])
            
            # Read HL7 message
            message_data = b""
            while True:
                try:
                    chunk = client_socket.recv(4096)
                    if not chunk:
                        break
                    
                    message_data += chunk
                    
                    # Check for message terminator (usually \r or \x1c\r)
                    if b'\r' in message_data or b'\x1c\r' in message_data:
                        break
                        
                except socket.timeout:
                    logger.warning(f"HL7 message timeout from {address}")
                    break
                except Exception as e:
                    logger.error(f"Error receiving HL7 message from {address}: {e}")
                    break
            
            if message_data:
                # Process the HL7 message
                self._process_hl7_message(message_data, client_socket, address)
                
        except Exception as e:
            logger.error(f"HL7 client error from {address}: {e}")
        finally:
            self.active_connections -= 1
            try:
                client_socket.close()
            except:
                pass
    
    def _process_hl7_message(self, message_data: bytes, client_socket: socket.socket, address: tuple):
        """Process received HL7 message"""
        try:
            # Decode message
            message_text = message_data.decode(self.config['encoding']).strip()
            
            # Remove message delimiters
            if message_text.startswith('\x0b'):
                message_text = message_text[1:]
            if message_text.endswith('\x1c\r'):
                message_text = message_text[:-2]
            elif message_text.endswith('\r'):
                message_text = message_text[:-1]
            
            logger.debug(f"Received HL7 message from {address}: {message_text[:100]}...")
            
            # Parse HL7 message
            try:
                hl7_message = hl7.parse(message_text)
            except Exception as e:
                logger.error(f"Failed to parse HL7 message from {address}: {e}")
                self._send_nak(client_socket, "Invalid HL7 format")
                self.messages_failed += 1
                return
            
            self.messages_received += 1
            
            # Get message type
            message_type = None
            if len(hl7_message) > 0 and len(hl7_message[0]) > 8:
                message_type = str(hl7_message[0][8])[:3]  # MSH.9.1
            
            if not message_type:
                logger.warning(f"Could not determine HL7 message type from {address}")
                self._send_nak(client_socket, "Unknown message type")
                self.messages_failed += 1
                return
            
            # Handle message based on type
            handler = self.message_handlers.get(message_type)
            if handler:
                success = handler(hl7_message, address)
                if success:
                    self._send_ack(client_socket, hl7_message)
                    self.messages_processed += 1
                else:
                    self._send_nak(client_socket, "Processing failed")
                    self.messages_failed += 1
            else:
                logger.warning(f"No handler for HL7 message type {message_type} from {address}")
                self._send_ack(client_socket, hl7_message)  # Still acknowledge
                
        except Exception as e:
            logger.error(f"Error processing HL7 message from {address}: {e}")
            try:
                self._send_nak(client_socket, str(e))
            except:
                pass
            self.messages_failed += 1
    
    def _send_ack(self, client_socket: socket.socket, original_message):
        """Send ACK (acknowledgment) message"""
        try:
            # Build ACK message
            ack = hl7.Message(
                "MSH",  # Message Header
                [
                    ["MSH", "|^~\\&", "Migration Service", "MS", "Source System", "SS", 
                     datetime.now().strftime("%Y%m%d%H%M%S"), "", "ACK", 
                     self._get_control_id(original_message), "P", "2.5"],
                    ["MSA", "AA", self._get_control_id(original_message), "Message accepted"]
                ]
            )
            
            ack_text = str(ack) + "\r"
            client_socket.send(ack_text.encode(self.config['encoding']))
            
        except Exception as e:
            logger.error(f"Failed to send ACK: {e}")
    
    def _send_nak(self, client_socket: socket.socket, error_message: str):
        """Send NAK (negative acknowledgment) message"""
        try:
            # Build NAK message
            nak = hl7.Message(
                "MSH",
                [
                    ["MSH", "|^~\\&", "Migration Service", "MS", "Source System", "SS",
                     datetime.now().strftime("%Y%m%d%H%M%S"), "", "ACK", 
                     "NAK001", "P", "2.5"],
                    ["MSA", "AE", "NAK001", error_message]
                ]
            )
            
            nak_text = str(nak) + "\r"
            client_socket.send(nak_text.encode(self.config['encoding']))
            
        except Exception as e:
            logger.error(f"Failed to send NAK: {e}")
    
    def _get_control_id(self, message) -> str:
        """Extract control ID from HL7 message"""
        try:
            if len(message) > 0 and len(message[0]) > 9:
                return str(message[0][9])  # MSH.10
            return "UNKNOWN"
        except:
            return "UNKNOWN"
    
    def _handle_adt_message(self, message, address: tuple) -> bool:
        """Handle ADT (Admission/Discharge/Transfer) message"""
        try:
            logger.info(f"Processing ADT message from {address}")
            
            # Extract patient information from PID segment
            pid_segment = None
            for segment in message:
                if str(segment[0]) == 'PID':
                    pid_segment = segment
                    break
            
            if pid_segment:
                patient_id = str(pid_segment[3]) if len(pid_segment) > 3 else ""
                patient_name = str(pid_segment[5]) if len(pid_segment) > 5 else ""
                dob = str(pid_segment[7]) if len(pid_segment) > 7 else ""
                sex = str(pid_segment[8]) if len(pid_segment) > 8 else ""
                
                logger.info(f"ADT Patient: ID={patient_id}, Name={patient_name}")
                
                # Store in database (run in event loop)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    loop.run_until_complete(
                        self.db_manager.execute_query(
                            "INSERT OR REPLACE INTO hl7_adt (patient_id, name, dob, sex, received_at) VALUES (?, ?, ?, ?, ?)",
                            [patient_id, patient_name, dob, sex, datetime.now().isoformat()]
                        )
                    )
                finally:
                    loop.close()
                
                return True
            else:
                logger.warning("ADT message missing PID segment")
                return False
                
        except Exception as e:
            logger.error(f"Error handling ADT message: {e}")
            return False
    
    def _handle_orm_message(self, message, address: tuple) -> bool:
        """Handle ORM (Order) message"""
        try:
            logger.info(f"Processing ORM message from {address}")
            
            # Extract order information from ORC and OBR segments
            orc_segment = None
            obr_segment = None
            
            for segment in message:
                segment_type = str(segment[0])
                if segment_type == 'ORC':
                    orc_segment = segment
                elif segment_type == 'OBR':
                    obr_segment = segment
            
            if orc_segment or obr_segment:
                order_control = str(orc_segment[1]) if orc_segment and len(orc_segment) > 1 else ""
                order_number = str(orc_segment[2]) if orc_segment and len(orc_segment) > 2 else ""
                
                if obr_segment:
                    procedure_code = str(obr_segment[4]) if len(obr_segment) > 4 else ""
                    
                logger.info(f"ORM Order: Control={order_control}, Number={order_number}")
                
                # Store in database
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    loop.run_until_complete(
                        self.db_manager.execute_query(
                            "INSERT INTO hl7_order (order_number, order_control, procedure_code, received_at) VALUES (?, ?, ?, ?)",
                            [order_number, order_control, procedure_code, datetime.now().isoformat()]
                        )
                    )
                finally:
                    loop.close()
                
                return True
            else:
                logger.warning("ORM message missing ORC/OBR segments")
                return False
                
        except Exception as e:
            logger.error(f"Error handling ORM message: {e}")
            return False
    
    def _handle_oru_message(self, message, address: tuple) -> bool:
        """Handle ORU (Observation Result) message"""
        try:
            logger.info(f"Processing ORU message from {address}")
            
            # Extract observation results from OBX segments
            obx_count = 0
            for segment in message:
                if str(segment[0]) == 'OBX':
                    obx_count += 1
                    observation_id = str(segment[3]) if len(segment) > 3 else ""
                    observation_value = str(segment[5]) if len(segment) > 5 else ""
                    
                    logger.debug(f"ORU Observation: ID={observation_id}, Value={observation_value}")
            
            logger.info(f"ORU message contained {obx_count} observations")
            return True
                
        except Exception as e:
            logger.error(f"Error handling ORU message: {e}")
            return False
    
    def _handle_ack_message(self, message, address: tuple) -> bool:
        """Handle ACK (Acknowledgment) message"""
        try:
            logger.info(f"Received ACK message from {address}")
            return True
                
        except Exception as e:
            logger.error(f"Error handling ACK message: {e}")
            return False
    
    def _handle_qry_message(self, message, address: tuple) -> bool:
        """Handle QRY (Query) message"""
        try:
            logger.info(f"Processing QRY message from {address}")
            # Query processing would go here
            return True
                
        except Exception as e:
            logger.error(f"Error handling QRY message: {e}")
            return False
    
    def _handle_dsr_message(self, message, address: tuple) -> bool:
        """Handle DSR (Display Response) message"""
        try:
            logger.info(f"Processing DSR message from {address}")
            # Display response processing would go here
            return True
                
        except Exception as e:
            logger.error(f"Error handling DSR message: {e}")
            return False
    
    def stop(self) -> bool:
        """
        Stop the HL7 listener service
        
        Returns:
            True if stopped successfully
        """
        if not self.is_running:
            return True
        
        try:
            logger.info("Stopping HL7 listener...")
            
            self.is_running = False
            
            # Close server socket
            if self.server_socket:
                self.server_socket.close()
                self.server_socket = None
            
            # Wait for server thread to finish
            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=10)
            
            logger.info("HL7 listener stopped")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping HL7 listener: {e}")
            return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get HL7 listener statistics"""
        return {
            'is_running': self.is_running,
            'is_configured': self.is_configured,
            'messages_received': self.messages_received,
            'messages_processed': self.messages_processed,
            'messages_failed': self.messages_failed,
            'connections_accepted': self.connections_accepted,
            'active_connections': self.active_connections,
            'config': {
                'port': self.config['port'],
                'host': self.config['host'],
                'max_connections': self.config['max_connections']
            }
        }


__all__ = ['HL7Listener']
