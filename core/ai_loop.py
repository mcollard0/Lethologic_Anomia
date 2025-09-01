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
import anthropic
import requests
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
        
        # AI Provider clients
        self.openai_client: Optional[openai.AsyncOpenAI] = None
        self.anthropic_client: Optional[anthropic.AsyncAnthropic] = None
        self.xai_client: Optional[openai.AsyncOpenAI] = None  # XAI uses OpenAI-compatible API
        self.local_model = None
        self.tokenizer = None
        
        # Speech models
        self.speech_model = None
        self.tts_engine = None
        
        # Provider availability tracking
        self.available_providers = []
        
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
            # Initialize AI providers in priority order
            await self._initialize_ai_providers()
            
            # Initialize local HuggingFace model (primary)
            await self._initialize_local_model()
            
            # Initialize speech models
            await self._initialize_speech_models()
            
            # Load saved responses and settings
            await self._load_saved_state()
            
            logger.info("AI Service initialization complete")
            logger.info(f"Available AI providers: {', '.join(self.available_providers)}")
            
        except Exception as e:
            logger.error(f"Failed to initialize AI Service: {e}")
            raise
    
    async def _initialize_ai_providers(self) -> None:
        """Initialize all AI providers based on priority order"""
        self.available_providers = []
        
        # Initialize providers in priority order from settings
        for provider in self.settings.ai.ai_providers:
            try:
                if provider == "huggingface_local":
                    # Local HuggingFace model (highest priority, free)
                    # This will be initialized in _initialize_local_model()
                    self.available_providers.append("huggingface_local")
                    logger.info("Local Hugging Face model configured (priority #1)")
                    
                elif provider == "xai" and self.settings.ai.xai_api_key:
                    # XAI uses OpenAI-compatible API
                    self.xai_client = openai.AsyncOpenAI(
                        api_key=self.settings.ai.xai_api_key,
                        base_url=self.settings.ai.xai_base_url
                    )
                    self.available_providers.append("xai")
                    logger.info("XAI (Grok) client initialized from environment variable")
                    
                elif provider == "anthropic" and self.settings.ai.anthropic_api_key:
                    self.anthropic_client = anthropic.AsyncAnthropic(
                        api_key=self.settings.ai.anthropic_api_key
                    )
                    self.available_providers.append("anthropic")
                    logger.info("Anthropic client initialized from environment variable")
                    
                elif provider == "openai" and self.settings.ai.openai_api_key:
                    self.openai_client = openai.AsyncOpenAI(
                        api_key=self.settings.ai.openai_api_key
                    )
                    self.available_providers.append("openai")
                    logger.info("OpenAI client initialized from environment variable")
                    
                elif provider == "huggingface_api" and self.settings.ai.huggingface_api_key:
                    # Hugging Face API (lowest priority, paid service)
                    self.available_providers.append("huggingface_api")
                    logger.info("Hugging Face API configured from environment variable (paid service - last priority)")
                    
                elif provider in ["xai", "anthropic", "openai", "huggingface_api"]:
                    # Provider requested but no API key found
                    logger.info(f"Provider {provider} requested but no API key found in environment variables")
                    
            except Exception as e:
                logger.warning(f"Failed to initialize {provider}: {e}")
                continue
    
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
        """Get response from AI model using fallback priority order"""
        last_error = None
        
        # Try each available provider in priority order
        for provider in self.available_providers:
            try:
                if provider == "huggingface_api":
                    response = await self._get_huggingface_api_response(user_input)
                elif provider == "huggingface_local":
                    response = await self._get_local_model_response(user_input)
                elif provider == "xai":
                    response = await self._get_xai_response(user_input)
                elif provider == "anthropic":
                    response = await self._get_anthropic_response(user_input)
                elif provider == "openai":
                    response = await self._get_openai_response(user_input)
                else:
                    continue
                
                if response and response.strip():
                    logger.info(f"Successfully got response from {provider}")
                    return response
                    
            except Exception as e:
                logger.warning(f"Provider {provider} failed: {e}")
                last_error = e
                continue
        
        # If all providers failed, return error
        error_msg = f"All AI providers failed. Last error: {last_error}" if last_error else "No AI providers available."
        logger.error(error_msg)
        return error_msg
    
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
    
    async def _get_xai_response(self, user_input: str) -> str:
        """Get response from XAI (Grok) API"""
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are Grok, an AI assistant for a medical imaging migration service. "
                        "You help with DICOM/HL7 operations, database queries, and system management. "
                        "You can call functions to perform actions. Be witty, engaging, but professional."
                    )
                },
                {"role": "user", "content": user_input}
            ]
            
            # XAI uses OpenAI-compatible API but with different model names
            response = await self.xai_client.chat.completions.create(
                model="grok-beta",  # XAI's model name
                messages=messages,
                max_tokens=512,
                temperature=0.7
            )
            
            message = response.choices[0].message
            return message.content if message.content else "I received an empty response from Grok."
            
        except Exception as e:
            logger.error(f"XAI API error: {e}")
            raise  # Re-raise to trigger fallback
    
    async def _get_anthropic_response(self, user_input: str) -> str:
        """Get response from Anthropic Claude API"""
        try:
            response = await self.anthropic_client.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=512,
                messages=[
                    {
                        "role": "user",
                        "content": f"""
You are Claude, an AI assistant for a medical imaging migration service. 
You help with DICOM/HL7 operations, database queries, and system management.
Be helpful, accurate, and professional.

User query: {user_input}"""
                    }
                ]
            )
            
            return response.content[0].text if response.content else "I received an empty response from Claude."
            
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            raise  # Re-raise to trigger fallback
    
    async def _get_huggingface_api_response(self, user_input: str) -> str:
        """Get response from Hugging Face API"""
        try:
            headers = {
                "Authorization": f"Bearer {self.settings.huggingface_api_key}",
                "Content-Type": "application/json"
            }
            
            # Use a conversational model available on HF API
            api_url = "https://api-inference.huggingface.co/models/microsoft/DialoGPT-large"
            
            payload = {
                "inputs": user_input,
                "parameters": {
                    "max_new_tokens": 250,
                    "temperature": 0.7,
                    "do_sample": True
                }
            }
            
            async with requests.Session() as session:
                response = session.post(api_url, headers=headers, json=payload)
                
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, list) and len(result) > 0:
                    generated_text = result[0].get("generated_text", "")
                    # Remove the input from the generated text
                    if generated_text.startswith(user_input):
                        response_text = generated_text[len(user_input):].strip()
                    else:
                        response_text = generated_text
                    
                    return response_text if response_text else "I'm not sure how to respond to that."
                else:
                    return "Received unexpected response format from Hugging Face API."
            else:
                logger.error(f"Hugging Face API error: {response.status_code} - {response.text}")
                raise Exception(f"API request failed with status {response.status_code}")
                
        except Exception as e:
            logger.error(f"Hugging Face API error: {e}")
            raise  # Re-raise to trigger fallback
    
    async def _get_local_model_response(self, user_input: str) -> str:
        """Get response from local HuggingFace model"""
        try:
            if not self.local_model or not self.tokenizer:
                raise Exception("Local model not initialized")
                
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
            raise  # Re-raise to trigger fallback
    
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
            },
            {
                "name": "fizzbuzz",
                "description": "Play the FizzBuzz game up to a specified number",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "max_number": {"type": "integer", "description": "Maximum number to count to (default 100)"}
                    }
                }
            },
            {
                "name": "math_quiz",
                "description": "Generate a simple math quiz",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "difficulty": {"type": "string", "description": "Difficulty level: easy, medium, hard"}
                    }
                }
            },
            {
                "name": "start_index",
                "description": "Start file indexing operation",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "directory": {"type": "string", "description": "Directory to index"}
                    }
                }
            },
            {
                "name": "start_parse",
                "description": "Start DICOM parsing operation",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "directory": {"type": "string", "description": "Directory to parse"}
                    }
                }
            },
            {
                "name": "create_user",
                "description": "Create a new user account",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "username": {"type": "string", "description": "Username for new account"},
                        "password": {"type": "string", "description": "Password for new account"}
                    },
                    "required": ["username", "password"]
                }
            },
            {
                "name": "delete_user",
                "description": "Delete a user account",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "username": {"type": "string", "description": "Username to delete"}
                    },
                    "required": ["username"]
                }
            },
            {
                "name": "change_password",
                "description": "Change a user's password",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "username": {"type": "string", "description": "Username whose password to change"},
                        "old_password": {"type": "string", "description": "Current password"},
                        "new_password": {"type": "string", "description": "New password"}
                    },
                    "required": ["username", "old_password", "new_password"]
                }
            },
            {
                "name": "list_users",
                "description": "List all user accounts",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "include_deleted": {"type": "boolean", "description": "Include deleted users (default: false)"}
                    }
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
                
            elif function_name == "fizzbuzz":
                return await self._fizzbuzz_game(arguments.get("max_number", 100))
                
            elif function_name == "math_quiz":
                return await self._math_quiz(arguments.get("difficulty", "easy"))
                
            elif function_name == "start_index":
                return await self._start_index(arguments.get("directory", "."))
                
            elif function_name == "start_parse":
                return await self._start_parse(arguments.get("directory", "."))
                
            elif function_name == "create_user":
                return await self._create_user(
                    arguments.get("username", ""),
                    arguments.get("password", "")
                )
                
            elif function_name == "delete_user":
                return await self._delete_user(arguments.get("username", ""))
                
            elif function_name == "change_password":
                return await self._change_password(
                    arguments.get("username", ""),
                    arguments.get("old_password", ""),
                    arguments.get("new_password", "")
                )
                
            elif function_name == "list_users":
                return await self._list_users(arguments.get("include_deleted", False))
                
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
        try:
            # Import DICOM discovery service
            from ..services.dicom.discovery import DICOMDiscoveryService
            
            # Create discovery service instance
            discovery_service = DICOMDiscoveryService(self.db_manager, self.settings)
            
            # Discover the specified host
            result = await discovery_service.discover_single_host(ip, port, ae_title)
            
            if result:
                return f"✅ DICOM service discovered at {ip}:{port}\n" + \
                       f"AE Title: {result['ae_title']}\n" + \
                       f"Response Time: {result['response_time']:.3f}s\n" + \
                       f"Service Type: {result['service_type']}"
            else:
                return f"❌ No DICOM service found at {ip}:{port} (AE: {ae_title})"
                
        except Exception as e:
            logger.error(f"Error during DICOM discovery: {e}")
            return f"❌ DICOM discovery failed: {str(e)}"
    
    async def _start_scp(self, port: int, ae_title: str) -> str:
        """Start DICOM SCP listener"""
        try:
            # Import DICOM SCP service
            from ..services.dicom.scp import DICOMSCPService, create_dicom_tables
            
            # Ensure database tables exist
            await create_dicom_tables(self.db_manager)
            
            # Create SCP service instance
            scp_service = DICOMSCPService(self.db_manager, self.settings)
            
            # Configure SCP
            config = {
                'port': port,
                'ae_title': ae_title,
                'output_directory': self.settings.dicom.storage_directory,
                'max_pdu': self.settings.dicom.max_pdu,
                'acse_timeout': self.settings.dicom.acse_timeout,
                'dimse_timeout': self.settings.dicom.dimse_timeout,
                'socket_timeout': self.settings.dicom.socket_timeout
            }
            
            if not scp_service.configure(config):
                return f"❌ Failed to configure DICOM SCP service"
            
            # Start the service
            if scp_service.start():
                return f"✅ DICOM SCP started successfully\n" + \
                       f"Port: {port}\n" + \
                       f"AE Title: {ae_title}\n" + \
                       f"Storage Directory: {config['output_directory']}"
            else:
                return f"❌ Failed to start DICOM SCP service"
                
        except Exception as e:
            logger.error(f"Error starting DICOM SCP: {e}")
            return f"❌ DICOM SCP startup failed: {str(e)}"
    
    async def _start_scu(self, target_ip: str, target_port: int, target_ae: str) -> str:
        """Start DICOM SCU operations"""
        try:
            # Import DICOM SCU service
            from ..services.dicom.scu import DICOMSCUService
            
            # Create SCU service instance
            scu_service = DICOMSCUService(self.db_manager, self.settings)
            
            # Configure SCU
            config = {
                'target_ip': target_ip,
                'target_port': target_port,
                'target_ae_title': target_ae,
                'ae_title': self.settings.dicom.our_ae_title,
                'max_pdu': self.settings.dicom.max_pdu,
                'acse_timeout': self.settings.dicom.acse_timeout,
                'dimse_timeout': self.settings.dicom.dimse_timeout,
                'network_timeout': self.settings.dicom.socket_timeout
            }
            
            if not scu_service.configure(config):
                return f"❌ Failed to configure DICOM SCU service"
            
            # Start the service
            if scu_service.start():
                return f"✅ DICOM SCU configured successfully\n" + \
                       f"Target: {target_ip}:{target_port}\n" + \
                       f"Target AE: {target_ae}\n" + \
                       f"Ready for C-FIND, C-STORE, and C-MOVE operations"
            else:
                return f"❌ Failed to start DICOM SCU service"
                
        except Exception as e:
            logger.error(f"Error starting DICOM SCU: {e}")
            return f"❌ DICOM SCU startup failed: {str(e)}"
    
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
    
    async def _fizzbuzz_game(self, max_number: int) -> str:
        """
        Play the classic FizzBuzz game
        
        Args:
            max_number: Maximum number to count to (default 100)
            
        Returns:
            FizzBuzz game output
        """
        try:
            if max_number <= 0 or max_number > 1000:
                return "Please provide a number between 1 and 1000."
            
            result = []
            result.append(f"Playing FizzBuzz up to {max_number}:\n")
            
            for i in range(1, max_number + 1):
                if i % 15 == 0:
                    result.append("FizzBuzz")
                elif i % 3 == 0:
                    result.append("Fizz")
                elif i % 5 == 0:
                    result.append("Buzz")
                else:
                    result.append(str(i))
                
                # Add line breaks every 10 items for readability
                if i % 10 == 0 and i < max_number:
                    result.append("\n")
                elif i < max_number:
                    result.append(", ")
            
            return "".join(result)
            
        except Exception as e:
            logger.error(f"Error in FizzBuzz game: {e}")
            return f"FizzBuzz game error: {str(e)}"
    
    async def _math_quiz(self, difficulty: str = "easy") -> str:
        """
        Generate a simple math quiz
        
        Args:
            difficulty: Difficulty level (easy, medium, hard)
            
        Returns:
            Math quiz problem and answer
        """
        try:
            difficulty = difficulty.lower()
            
            if difficulty == "easy":
                # Single digit addition and subtraction
                a = random.randint(1, 9)
                b = random.randint(1, 9)
                operation = random.choice(['+', '-'])
                if operation == '+' or a >= b:
                    answer = a + b if operation == '+' else a - b
                else:
                    a, b = b, a  # Ensure positive result
                    answer = a - b
                problem = f"{a} {operation} {b}"
                
            elif difficulty == "medium":
                # Two digit numbers with multiplication and division
                if random.choice([True, False]):  # Multiplication
                    a = random.randint(2, 12)
                    b = random.randint(2, 12)
                    operation = '×'
                    answer = a * b
                    problem = f"{a} {operation} {b}"
                else:  # Division
                    answer = random.randint(2, 12)
                    b = random.randint(2, 12)
                    a = answer * b
                    operation = '÷'
                    problem = f"{a} {operation} {b}"
                    
            elif difficulty == "hard":
                # More complex operations
                operation_type = random.choice(['power', 'sqrt', 'complex'])
                if operation_type == 'power':
                    base = random.randint(2, 10)
                    exp = random.randint(2, 4)
                    answer = base ** exp
                    problem = f"{base}^{exp}"
                elif operation_type == 'sqrt':
                    answer = random.randint(1, 15)
                    square = answer ** 2
                    problem = f"√{square}"
                else:  # complex arithmetic
                    a = random.randint(5, 25)
                    b = random.randint(2, 8)
                    c = random.randint(1, 10)
                    answer = (a * b) + c
                    problem = f"({a} × {b}) + {c}"
            else:
                return "Invalid difficulty level. Please use 'easy', 'medium', or 'hard'."
            
            # Store the quiz in database for potential follow-up
            quiz_data = {
                'problem': problem,
                'answer': str(answer),
                'difficulty': difficulty,
                'created_at': datetime.now().isoformat()
            }
            
            await self.db_manager.execute_query(
                "INSERT OR REPLACE INTO config (name, value) VALUES (?, ?)",
                ("LAST_MATH_QUIZ", json.dumps(quiz_data))
            )
            
            return f"Math Quiz ({difficulty.capitalize()} level):\n\nSolve: {problem}\n\n(Answer: {answer})"
            
        except Exception as e:
            logger.error(f"Error generating math quiz: {e}")
            return f"Math quiz error: {str(e)}"
    
    async def _start_index(self, directory: str = ".") -> str:
        """
        Start file indexing operation
        
        Args:
            directory: Directory to index (default current directory)
            
        Returns:
            Indexing operation status
        """
        try:
            if not os.path.exists(directory):
                return f"Directory does not exist: {directory}"
            
            if not os.path.isdir(directory):
                return f"Path is not a directory: {directory}"
            
            # Count files by type
            file_counts = {}
            total_files = 0
            total_size = 0
            
            for root, dirs, files in os.walk(directory):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        # Get file extension
                        _, ext = os.path.splitext(file)
                        ext = ext.lower() if ext else 'no_extension'
                        
                        # Count by extension
                        file_counts[ext] = file_counts.get(ext, 0) + 1
                        total_files += 1
                        
                        # Add file size
                        total_size += os.path.getsize(file_path)
                        
                    except (OSError, IOError) as e:
                        logger.warning(f"Could not access file {file_path}: {e}")
                        continue
            
            # Format results
            result = []
            result.append(f"File indexing complete for: {directory}")
            result.append(f"Total files: {total_files}")
            result.append(f"Total size: {total_size / (1024*1024):.2f} MB")
            result.append("\nFile types:")
            
            # Sort by count descending
            sorted_counts = sorted(file_counts.items(), key=lambda x: x[1], reverse=True)
            for ext, count in sorted_counts[:10]:  # Show top 10 file types
                result.append(f"  {ext}: {count} files")
            
            # Store index results in database
            index_data = {
                'directory': directory,
                'total_files': total_files,
                'total_size': total_size,
                'file_counts': file_counts,
                'indexed_at': datetime.now().isoformat()
            }
            
            await self.db_manager.execute_query(
                "INSERT OR REPLACE INTO config (name, value) VALUES (?, ?)",
                (f"INDEX_{directory.replace('/', '_')}", json.dumps(index_data))
            )
            
            return "\n".join(result)
            
        except Exception as e:
            logger.error(f"Error in file indexing: {e}")
            return f"File indexing error: {str(e)}"
    
    async def _start_parse(self, directory: str = ".") -> str:
        """
        Start DICOM parsing operation using the comprehensive scanner service
        
        Args:
            directory: Directory to parse for DICOM files
            
        Returns:
            DICOM parsing operation status
        """
        try:
            if not os.path.exists(directory):
                return f"Directory does not exist: {directory}"
            
            if not os.path.isdir(directory):
                return f"Path is not a directory: {directory}"
            
            # Import DICOM scanner service
            from ..services.dicom.scanner import DICOMDirectoryScanner
            
            # Create scanner instance
            scanner = DICOMDirectoryScanner(self.db_manager, self.settings)
            
            # Start scanning the directory
            result = await scanner.scan_directory(directory)
            
            # Format results
            output = []
            output.append(f"✅ DICOM directory scan complete for: {directory}")
            output.append(f"📁 Files processed: {result['files_processed']}")
            output.append(f"📋 DICOM files found: {result['dicom_files']}")
            output.append(f"🔍 DICONDE files found: {result['diconde_files']}")
            output.append(f"🎯 DICOS files found: {result['dicos_files']}")
            output.append(f"❌ Errors encountered: {result['errors']}")
            output.append(f"⏱️ Scan duration: {result['duration']:.2f} seconds")
            
            if result['errors'] > 0:
                output.append(f"\n⚠️  Some files had errors during processing.")
                output.append(f"Check logs for detailed error information.")
            
            if result['dicom_files'] + result['diconde_files'] + result['dicos_files'] > 0:
                output.append(f"\n📊 All metadata has been stored in the database.")
                output.append(f"Use SQL queries to explore the extracted metadata.")
            else:
                output.append(f"\n💡 No DICOM/DICONDE/DICOS files found.")
                output.append(f"Supported formats: .dcm, .dicom, .ima, .img, and files without extensions.")
            
            return "\n".join(output)
            
        except Exception as e:
            logger.error(f"Error in DICOM parsing: {e}")
            return f"❌ DICOM parsing failed: {str(e)}"
    
    async def _create_user(self, username: str, password: str) -> str:
        """Create a new user account"""
        try:
            if not username or not password:
                return "Username and password are required."
            
            success = await self.db_manager.create_user(username, password)
            
            if success:
                return f"✅ User '{username}' created successfully."
            else:
                return f"❌ Failed to create user '{username}'. Username may already exist."
                
        except Exception as e:
            logger.error(f"Error creating user {username}: {e}")
            return f"❌ Error creating user: {str(e)}"
    
    async def _delete_user(self, username: str) -> str:
        """Delete a user account"""
        try:
            if not username:
                return "Username is required."
            
            success = await self.db_manager.delete_user(username)
            
            if success:
                return f"✅ User '{username}' deleted successfully."
            else:
                return f"❌ Failed to delete user '{username}'. User may not exist."
                
        except Exception as e:
            logger.error(f"Error deleting user {username}: {e}")
            return f"❌ Error deleting user: {str(e)}"
    
    async def _change_password(self, username: str, old_password: str, new_password: str) -> str:
        """Change user password"""
        try:
            if not username or not old_password or not new_password:
                return "Username, old password, and new password are all required."
            
            success = await self.db_manager.change_password(username, old_password, new_password)
            
            if success:
                return f"✅ Password changed successfully for user '{username}'."
            else:
                return f"❌ Failed to change password for user '{username}'. Check current password and ensure user exists."
                
        except Exception as e:
            logger.error(f"Error changing password for user {username}: {e}")
            return f"❌ Error changing password: {str(e)}"
    
    async def _list_users(self, include_deleted: bool = False) -> str:
        """List all user accounts"""
        try:
            users = await self.db_manager.list_users(include_deleted)
            
            if not users:
                return "No users found in the database."
            
            output = []
            output.append(f"User Accounts ({len(users)} total):")
            output.append("=" * 50)
            
            for user in users:
                status = "🟢 Active" if user.get('enabled') else "🔴 Disabled"
                if user.get('deleted'):
                    status = "🗑️ Deleted"
                
                created = user.get('created_at')
                if isinstance(created, datetime):
                    created_str = created.strftime('%Y-%m-%d %H:%M')
                else:
                    created_str = str(created)
                
                output.append(f"• {user['username']} ({status})")
                output.append(f"  ID: {user['id']}, Created: {created_str}")
            
            return "\n".join(output)
            
        except Exception as e:
            logger.error(f"Error listing users: {e}")
            return f"❌ Error listing users: {str(e)}"


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
