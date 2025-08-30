"""
AI Loop Module - Core AI processing loop

This is the Python equivalent of aiLoop() from the C++ version.
Handles AI model initialization, user input processing, and function calls.
"""

import asyncio
import json
import os
import random
import time
from datetime import datetime
from typing import Dict, Any, Optional, List

import openai
from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM
from transformers import WhisperProcessor, WhisperForConditionalGeneration
import torch

from .config import Settings
from .logging import get_logger
from .database import DatabaseManager
from .redis_manager import RedisManager
from .process_manager import ProcessManager

logger = get_logger(__name__)


class AIService:
    """
    AI Service for processing user commands and interfacing with various AI models
    
    Supports:
    - OpenAI/Anthropic APIs for text processing
    - Local HuggingFace models for offline operation
    - Speech-to-text and text-to-speech
    - Function calling and command processing
    """
    
    def __init__(self, settings: Settings, db_manager: DatabaseManager):
        self.settings = settings
        self.db_manager = db_manager
        self.trust_level = 0
        self.aggression_level = 1
        self.trusted_threshold = 5
        
        # AI Models
        self.openai_client: Optional[openai.AsyncOpenAI] = None
        self.local_model = None
        self.tokenizer = None
        self.speech_model = None
        self.tts_engine = None
        
        # Response tracking
        self.last_responses: List[str] = [""] * 10
        self.response_position = 0
        
        # Thinking words for user feedback
        self.thinking_words = [
            "Thinking...", "Processing...", "Analyzing...", "Computing...",
            "Considering...", "Evaluating...", "Calculating...", "Pondering..."
        ]
        
        logger.info("AI Service initialized")
    
    async def initialize(self) -> None:
        """Initialize AI models and services"""
        try:
            # Initialize OpenAI if API key is available
            if self.settings.openai_api_key:
                self.openai_client = openai.AsyncOpenAI(
                    api_key=self.settings.openai_api_key
                )
                logger.info("OpenAI client initialized")
            
            # Initialize local HuggingFace model for offline operation
            await self._initialize_local_model()
            
            # Initialize speech models
            await self._initialize_speech_models()
            
            # Load saved responses and settings
            await self._load_saved_state()
            
            logger.info("AI Service initialization complete")
            
        except Exception as e:
            logger.error(f"Failed to initialize AI Service: {e}")
            raise
    
    async def _initialize_local_model(self) -> None:
        """Initialize local HuggingFace model for offline operation"""
        try:
            # Use a lightweight model suitable for text processing
            model_name = "microsoft/DialoGPT-medium"
            
            logger.info(f"Loading local model: {model_name}")
            
            # Load tokenizer and model
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.local_model = AutoModelForCausalLM.from_pretrained(model_name)
            
            # Add pad token if it doesn't exist
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
            
            logger.info("Local AI model initialized successfully")
            
        except Exception as e:
            logger.warning(f"Failed to initialize local model: {e}")
            # Continue without local model - will use API only
    
    async def _initialize_speech_models(self) -> None:
        """Initialize speech-to-text and text-to-speech models"""
        try:
            # Initialize Whisper for speech-to-text
            if torch.cuda.is_available():
                device = "cuda"
            else:
                device = "cpu"
            
            # Use a smaller Whisper model for efficiency
            self.speech_processor = WhisperProcessor.from_pretrained("openai/whisper-tiny.en")
            self.speech_model = WhisperForConditionalGeneration.from_pretrained(
                "openai/whisper-tiny.en"
            ).to(device)
            
            logger.info(f"Speech models initialized on {device}")
            
            # Initialize TTS
            try:
                import pyttsx3
                self.tts_engine = pyttsx3.init()
                
                # Configure TTS settings
                voices = self.tts_engine.getProperty('voices')
                if voices:
                    self.tts_engine.setProperty('voice', voices[0].id)  # Use first available voice
                
                self.tts_engine.setProperty('rate', 150)  # Speaking rate
                self.tts_engine.setProperty('volume', 0.8)  # Volume level
                
                logger.info("Text-to-speech engine initialized")
                
            except Exception as e:
                logger.warning(f"Failed to initialize TTS: {e}")
                
        except Exception as e:
            logger.warning(f"Failed to initialize speech models: {e}")
    
    async def _load_saved_state(self) -> None:
        """Load saved responses and settings from database"""
        try:
            # Load last responses
            result = await self.db_manager.execute_query(
                "SELECT value FROM config WHERE name = 'LAST RESPONSES'"
            )
            
            if result and result[0].get('value'):
                responses_json = json.loads(result[0]['value'])
                for i in range(min(len(responses_json), 10)):
                    self.last_responses[i] = responses_json[i]
            
            # Load response position
            result = await self.db_manager.execute_query(
                "SELECT value FROM config WHERE name = 'LAST RESPONSE POSITION'"
            )
            
            if result and result[0].get('value'):
                self.response_position = int(result[0]['value'])
                
            # Load trust level
            result = await self.db_manager.execute_query(
                "SELECT value FROM config WHERE name = 'TRUST LEVEL'"
            )
            
            if result and result[0].get('value'):
                self.trust_level = int(result[0]['value'])
                
        except Exception as e:
            logger.warning(f"Failed to load saved state: {e}")
    
    async def _save_state(self) -> None:
        """Save current state to database"""
        try:
            # Save responses
            responses_json = json.dumps(self.last_responses)
            await self.db_manager.execute_query(
                "INSERT OR REPLACE INTO config (name, value) VALUES (?, ?)",
                ("LAST RESPONSES", responses_json)
            )
            
            # Save position
            await self.db_manager.execute_query(
                "INSERT OR REPLACE INTO config (name, value) VALUES (?, ?)",
                ("LAST RESPONSE POSITION", str(self.response_position))
            )
            
            # Save trust level
            await self.db_manager.execute_query(
                "INSERT OR REPLACE INTO config (name, value) VALUES (?, ?)",
                ("TRUST LEVEL", str(self.trust_level))
            )
            
        except Exception as e:
            logger.warning(f"Failed to save state: {e}")
    
    async def process_input(self, user_input: str) -> str:
        """
        Process user input and return AI response
        
        Args:
            user_input: User's text input
            
        Returns:
            AI response or function result
        """
        if not user_input.strip():
            return "Please provide a command or question."
        
        # Store user input in response history
        self.last_responses[self.response_position] = user_input
        self.response_position = (self.response_position + 1) % 10
        await self._save_state()
        
        # Log the command
        await self.db_manager.execute_query(
            "INSERT OR REPLACE INTO config (name, value) VALUES (?, ?)",
            ("LAST COMMAND", user_input)
        )
        
        # Show thinking indicator
        thinking_word = random.choice(self.thinking_words)
        print(thinking_word, end="", flush=True)
        
        try:
            # Check if this is a direct function call
            function_result = await self._handle_direct_commands(user_input)
            if function_result:
                # Clear thinking indicator
                print("\b" * len(thinking_word), end="", flush=True)
                return function_result
            
            # Process with AI
            if self.trust_level < self.trusted_threshold:
                # Check content moderation for untrusted input
                if not await self._moderate_content(user_input):
                    print("\b" * len(thinking_word), end="", flush=True)
                    return "Content moderation failed. Please rephrase your request."
                else:
                    self.trust_level += 1
            
            # Get AI response
            response = await self._get_ai_response(user_input)
            
            # Clear thinking indicator
            print("\b" * len(thinking_word), end="", flush=True)
            
            return response
            
        except Exception as e:
            print("\b" * len(thinking_word), end="", flush=True)
            logger.error(f"Error processing input: {e}")
            return f"An error occurred while processing your request: {str(e)}"
    
    async def _handle_direct_commands(self, input_text: str) -> Optional[str]:
        """Handle direct commands that don't need AI processing"""
        input_lower = input_text.lower().strip()
        
        # Direct command mappings
        if input_lower == "help":
            return self._get_help()
        elif input_lower == "quit" or input_lower == ".q":
            return "QUIT_REQUESTED"
        elif input_lower == "schema":
            return await self._get_schema()
        elif input_lower.startswith("get_trust"):
            return f"Current trust level: {self.trust_level}"
        elif input_lower.startswith("set_trust "):
            try:
                new_trust = int(input_lower.split(" ", 1)[1])
                self.trust_level = new_trust
                return f"Trust level set to: {self.trust_level}"
            except (ValueError, IndexError):
                return "Invalid trust level. Please provide a number."
        elif input_lower.startswith("get_aggression"):
            return f"Current aggression level: {self.aggression_level}"
        
        return None
    
    async def _get_ai_response(self, user_input: str) -> str:
        """Get response from AI model (OpenAI API or local model)"""
        try:
            if self.openai_client:
                return await self._get_openai_response(user_input)
            elif self.local_model:
                return await self._get_local_model_response(user_input)
            else:
                return "No AI model available. Please check your configuration."
                
        except Exception as e:
            logger.error(f"Error getting AI response: {e}")
            return f"AI service error: {str(e)}"
    
    async def _get_openai_response(self, user_input: str) -> str:
        """Get response from OpenAI API"""
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are an AI assistant for a medical imaging migration service. "
                        "You help with DICOM/HL7 operations, database queries, and system management. "
                        "You can call functions to perform actions. Respond concisely and professionally."
                    )
                },
                {"role": "user", "content": user_input}
            ]
            
            # Add function definitions
            functions = self._get_function_definitions()
            
            response = await self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                functions=functions,
                max_tokens=512,
                temperature=0.5
            )
            
            message = response.choices[0].message
            
            if message.function_call:
                # Handle function call
                function_name = message.function_call.name
                function_args = json.loads(message.function_call.arguments)
                
                result = await self._handle_function_call(function_name, function_args)
                return result
            else:
                return message.content
                
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return f"OpenAI API error: {str(e)}"
    
    async def _get_local_model_response(self, user_input: str) -> str:
        """Get response from local HuggingFace model"""
        try:
            # Encode input
            inputs = self.tokenizer.encode(user_input + self.tokenizer.eos_token, return_tensors='pt')
            
            # Generate response
            with torch.no_grad():
                outputs = self.local_model.generate(
                    inputs,
                    max_length=inputs.shape[1] + 100,
                    num_return_sequences=1,
                    temperature=0.7,
                    do_sample=True,
                    pad_token_id=self.tokenizer.eos_token_id
                )
            
            # Decode response
            response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            
            # Extract only the new part (after the input)
            response = response[len(user_input):].strip()
            
            return response if response else "I'm not sure how to respond to that."
            
        except Exception as e:
            logger.error(f"Local model error: {e}")
            return f"Local model error: {str(e)}"
    
    def _get_function_definitions(self) -> List[Dict[str, Any]]:
        """Get OpenAI function definitions for available commands"""
        return [
            {
                "name": "log",
                "description": "Log a message to the system",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Message to log"}
                    },
                    "required": ["message"]
                }
            },
            {
                "name": "get_migration_status",
                "description": "Get migration status for a site",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sitename": {"type": "string", "description": "Name of the site"}
                    },
                    "required": ["sitename"]
                }
            },
            {
                "name": "discovery",
                "description": "Start DICOM discovery on target system",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ip": {"type": "string", "description": "Target IP address"},
                        "port": {"type": "integer", "description": "Target port"},
                        "ae_title": {"type": "string", "description": "AE Title of target"}
                    },
                    "required": ["ip", "port", "ae_title"]
                }
            },
            {
                "name": "start_scp",
                "description": "Start DICOM SCP listener",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "port": {"type": "integer", "description": "Listening port"},
                        "ae_title": {"type": "string", "description": "Our AE Title"}
                    },
                    "required": ["port"]
                }
            },
            {
                "name": "start_scu",
                "description": "Start DICOM SCU operations",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_ip": {"type": "string", "description": "Target IP"},
                        "target_port": {"type": "integer", "description": "Target port"},
                        "target_ae": {"type": "string", "description": "Target AE Title"}
                    },
                    "required": ["target_ip", "target_port", "target_ae"]
                }
            },
            {
                "name": "select_query",
                "description": "Execute a SELECT SQL query",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "SQL query to execute"}
                    },
                    "required": ["query"]
                }
            }
        ]
    
    async def _handle_function_call(self, function_name: str, arguments: Dict[str, Any]) -> str:
        """Handle function calls from AI"""
        try:
            logger.info(f"Handling function call: {function_name} with args: {arguments}")
            
            if function_name == "log":
                await self._log_message(arguments.get("message", ""))
                return "Message logged successfully."
                
            elif function_name == "get_migration_status":
                return await self._get_migration_status(arguments.get("sitename", ""))
                
            elif function_name == "discovery":
                return await self._start_discovery(
                    arguments.get("ip", ""),
                    arguments.get("port", 104),
                    arguments.get("ae_title", "")
                )
                
            elif function_name == "start_scp":
                return await self._start_scp(
                    arguments.get("port", 104),
                    arguments.get("ae_title", "MIGRATIONSERVICE")
                )
                
            elif function_name == "start_scu":
                return await self._start_scu(
                    arguments.get("target_ip", ""),
                    arguments.get("target_port", 104),
                    arguments.get("target_ae", "")
                )
                
            elif function_name == "select_query":
                return await self._execute_select_query(arguments.get("query", ""))
                
            else:
                return f"Function '{function_name}' is not implemented yet."
                
        except Exception as e:
            logger.error(f"Error handling function call {function_name}: {e}")
            return f"Error executing function: {str(e)}"
    
    async def _log_message(self, message: str) -> None:
        """Log a message from AI"""
        logger.info(f"AI Message: {message}")
    
    async def _get_migration_status(self, sitename: str) -> str:
        """Get migration status for a site"""
        try:
            result = await self.db_manager.execute_query(
                "SELECT status FROM sites WHERE sitename = ?", (sitename,)
            )
            
            if not result:
                return f"No migration found for site: {sitename}"
            
            return f"Migration status for {sitename}: {result[0]['status']}"
            
        except Exception as e:
            logger.error(f"Error getting migration status: {e}")
            return f"Error retrieving migration status: {str(e)}"
    
    async def _start_discovery(self, ip: str, port: int, ae_title: str) -> str:
        """Start DICOM discovery"""
        # This will be implemented when we create the DICOM services
        return f"Starting DICOM discovery on {ip}:{port} (AE: {ae_title}) - Implementation pending"
    
    async def _start_scp(self, port: int, ae_title: str) -> str:
        """Start DICOM SCP listener"""
        # This will be implemented when we create the DICOM services
        return f"Starting DICOM SCP on port {port} (AE: {ae_title}) - Implementation pending"
    
    async def _start_scu(self, target_ip: str, target_port: int, target_ae: str) -> str:
        """Start DICOM SCU operations"""
        # This will be implemented when we create the DICOM services
        return f"Starting DICOM SCU to {target_ip}:{target_port} (AE: {target_ae}) - Implementation pending"
    
    async def _execute_select_query(self, query: str) -> str:
        """Execute a SELECT query"""
        try:
            # Basic security check
            query_lower = query.lower().strip()
            if not query_lower.startswith("select"):
                return "Only SELECT queries are allowed through this function."
            
            result = await self.db_manager.execute_query(query)
            
            if not result:
                return "No results found."
            
            # Format results for display
            output = []
            for row in result[:10]:  # Limit to 10 rows
                output.append(str(dict(row)))
            
            return f"Query results ({len(result)} total rows):\n" + "\n".join(output)
            
        except Exception as e:
            logger.error(f"Error executing query: {e}")
            return f"Query error: {str(e)}"
    
    async def _moderate_content(self, content: str) -> bool:
        """Basic content moderation"""
        # Simple content filtering - can be enhanced with AI moderation
        prohibited_patterns = [
            "drop table", "delete from", "truncate", "alter table",
            "create table", "insert into", "update set"
        ]
        
        content_lower = content.lower()
        for pattern in prohibited_patterns:
            if pattern in content_lower:
                logger.warning(f"Content moderation blocked potentially dangerous content: {pattern}")
                return False
        
        return True
    
    def _get_help(self) -> str:
        """Return help information"""
        return """
Migration Service Commands:

Basic Commands:
- help                    : Show this help message
- quit                   : Exit the service
- schema                 : Show database schema
- get_trust              : Show current trust level
- set_trust <level>      : Set trust level

DICOM Operations:
- discovery <ip>:<port>  : DICOM discovery
- start_scp             : Start DICOM SCP listener  
- start_scu             : Start DICOM SCU operations

Database:
- select_query <SQL>    : Execute SELECT query

AI Features:
- Natural language processing for commands
- Speech-to-text input (when audio is available)
- Function calling for system operations

Simply type your commands or ask questions in natural language.
The AI will interpret your intent and execute the appropriate actions.
        """
    
    async def _get_schema(self) -> str:
        """Get database schema information"""
        try:
            result = await self.db_manager.execute_query(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            
            if not result:
                return "No tables found in database."
            
            tables = [row['name'] for row in result]
            return f"Database tables: {', '.join(tables)}"
            
        except Exception as e:
            logger.error(f"Error getting schema: {e}")
            return f"Schema error: {str(e)}"


async def ai_loop(process_manager: ProcessManager, settings: Settings) -> None:
    """
    Main AI loop - Python equivalent of aiLoop() from C++
    
    Args:
        process_manager: Process manager instance
        settings: Application settings
    """
    logger.info("Starting AI loop...")
    
    try:
        # Initialize AI service
        ai_service = AIService(settings, process_manager.db_manager)
        await ai_service.initialize()
        
        print("\nMigration Service AI Assistant")
        print("Type 'help' for commands or '.q' to quit")
        print("You can also speak naturally - I'll understand your intent.\n")
        
        # Main processing loop
        while True:
            try:
                # Get user input
                user_input = input("> ").strip()
                
                if not user_input:
                    # Use last command if empty input
                    result = await process_manager.db_manager.execute_query(
                        "SELECT value FROM config WHERE name = 'LAST COMMAND'"
                    )
                    if result and result[0].get('value'):
                        user_input = result[0]['value']
                        print(f"Repeating last command: {user_input}")
                    else:
                        continue
                
                # Process input
                response = await ai_service.process_input(user_input)
                
                # Handle special responses
                if response == "QUIT_REQUESTED":
                    print("Goodbye!")
                    break
                
                # Display response
                print(f"\n{response}\n")
                
            except KeyboardInterrupt:
                print("\nReceived interrupt signal. Use 'quit' to exit properly.")
                continue
            except EOFError:
                print("\nExiting...")
                break
            except Exception as e:
                logger.error(f"Error in AI loop: {e}")
                print(f"An error occurred: {str(e)}")
                continue
                
    except Exception as e:
        logger.error(f"Fatal error in AI loop: {e}")
        raise
    finally:
        logger.info("AI loop terminated")


# Export the main function
__all__ = ['ai_loop', 'AIService']
