
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
from .custom_logging import get_logger
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
        self.last_responses: Dict[int, str] = {i: "" for i in range(10)}
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
                    # Local HuggingFace model (free, but priority depends on AI_PROVIDERS config)
                    # This will be initialized in _initialize_local_model()
                    self.available_providers.append("huggingface_local")
                    logger.info("Local Hugging Face model configured")
                    
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
            # Use Mistral for better instruction following and function calling
            model_name = "mistralai/Mistral-7B-Instruct-v0.1"
            
            logger.info(f"Loading local model: {model_name}")
            
            # Get optimal model configuration based on available memory
            model_config = self._get_optimal_model_config(model_name)
            logger.info(f"Selected precision: {model_config['precision']} ({model_config['reason']})")
            
            # Load tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            
            # Load model with memory-optimized settings
            load_kwargs = {
                'torch_dtype': model_config['torch_dtype'],
                'device_map': model_config['device_map'],
                'low_cpu_mem_usage': True
            }
            
            # Add quantization if needed
            if model_config.get('load_in_8bit', False):
                load_kwargs['load_in_8bit'] = True
                logger.info("Using 8-bit quantization for memory efficiency")
            
            # Add memory limits if specified
            if model_config.get('max_memory'):
                load_kwargs['max_memory'] = model_config['max_memory']
                logger.info(f"Memory limit: {model_config['max_memory']}")
            
            self.local_model = AutoModelForCausalLM.from_pretrained(
                model_name,
                **load_kwargs
            )
            
            # Add pad token if it doesn't exist
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
            
            logger.info("Local AI model (Mistral-7B-Instruct) initialized successfully")
            
        except Exception as e:
            logger.warning(f"Failed to initialize Mistral model, falling back to DialoGPT: {e}")
            try:
                # Fallback to DialoGPT if Mistral fails
                model_name = "microsoft/DialoGPT-medium"
                logger.info(f"Loading fallback model: {model_name}")
                
                self.tokenizer = AutoTokenizer.from_pretrained(model_name)
                self.local_model = AutoModelForCausalLM.from_pretrained(model_name)
                
                if self.tokenizer.pad_token is None:
                    self.tokenizer.pad_token = self.tokenizer.eos_token
                
                logger.info("Fallback local AI model initialized successfully")
            except Exception as fallback_error:
                logger.warning(f"Failed to initialize fallback model: {fallback_error}")
                # Continue without local model - will use API only
    
    def _get_optimal_model_config(self, model_name: str) -> dict:
        """Determine optimal model configuration based on available system memory
        
        Args:
            model_name: Name of the model to load
            
        Returns:
            Dict with model configuration parameters
        """
        try:
            import psutil
            
            # Get available system memory
            memory = psutil.virtual_memory()
            total_gb = memory.total / (1024 ** 3)  # Total RAM in GB
            available_gb = memory.available / (1024 ** 3)  # Available RAM in GB
            used_percent = memory.percent
            
            logger.info(f"System memory: {total_gb:.1f}GB total, {available_gb:.1f}GB available ({used_percent}% used)")
            
            # Estimate model memory requirements for 7B parameters
            fp32_size_gb = 28.0  # ~28GB for FP32
            fp16_size_gb = 14.0  # ~14GB for FP16
            int8_size_gb = 7.0   # ~7GB for Int8
            
            # Default config for GPU
            if torch.cuda.is_available():
                config = {
                    'torch_dtype': torch.float16,
                    'device_map': 'auto',
                    'precision': 'fp16',
                    'reason': 'GPU available'
                }
            else:
                # CPU-only environment - determine best precision based on available memory
                safety_margin = 0.85  # Use 85% of available memory at most
                safe_available_gb = available_gb * safety_margin
                
                if safe_available_gb >= fp16_size_gb + 2.0:  # +2GB for overhead
                    # Enough memory for FP16
                    config = {
                        'torch_dtype': torch.float16,
                        'device_map': None,
                        'precision': 'fp16',
                        'reason': f'Enough memory for FP16 ({safe_available_gb:.1f}GB available)'
                    }
                elif safe_available_gb >= int8_size_gb + 2.0:  # +2GB for overhead
                    # Use 8-bit quantization
                    config = {
                        'torch_dtype': torch.float16,  # Base dtype still float16
                        'device_map': None,
                        'load_in_8bit': True,
                        'precision': 'int8',
                        'reason': f'Using 8-bit quantization to save memory ({safe_available_gb:.1f}GB available)'
                    }
                else:
                    # Very low memory - add disk offloading and strict memory limits
                    logger.warning(f"Low memory condition detected ({safe_available_gb:.1f}GB available). Adding disk offloading.")
                    config = {
                        'torch_dtype': torch.float16,
                        'device_map': 'auto',  # Auto will use disk offloading
                        'load_in_8bit': True,
                        'max_memory': {0: f"{int(safe_available_gb * 1024)}MB"},  # Limit memory use
                        'precision': 'int8+offload',
                        'reason': f'Low memory, using 8-bit + disk offloading ({safe_available_gb:.1f}GB available)'
                    }
            
            return config
                
        except Exception as e:
            logger.warning(f"Error determining optimal model config: {e}. Using default configuration.")
            # Default safe configuration
            return {
                'torch_dtype': torch.float16,
                'device_map': 'auto' if torch.cuda.is_available() else None,
                'precision': 'fp16',
                'reason': 'Default configuration (error in memory detection)'
            }
    
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
                if isinstance(responses_json, dict):
                    # New format: dictionary
                    for i in range(min(len(responses_json), 10)):
                        if str(i) in responses_json:
                            self.last_responses[i] = responses_json[str(i)]
                elif isinstance(responses_json, list):
                    # Old format: list - convert to dictionary
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
        
        # Pattern matching for natural language commands
        # Check for SCP/DICOM server patterns
        if self._matches_scp_pattern(input_lower):
            return await self._start_scp()
        
        # Check for user creation patterns
        if self._matches_create_user_pattern(input_lower):
            return await self._handle_natural_language_create_user(input_text)
        
        # Check for user management patterns
        if self._matches_user_management_pattern(input_lower):
            return await self._handle_natural_language_user_management(input_text)
        
        return None
    
    def _matches_scp_pattern(self, input_lower: str) -> bool:
        """Check if input matches SCP/DICOM server start patterns"""
        patterns = [
            r"\bscp\b",                          # Just 'SCP'
            r"start.*scp",                       # 'start SCP'
            r"start.*dicom.*server",             # 'start DICOM server'
            r"start.*dicom.*scp",                # 'start DICOM SCP'
            r"dicom.*server",                    # 'DICOM server'
            r"scp.*server",                      # 'SCP server'
            r"start.*server",                    # Generic 'start server'
            r"launch.*scp",                      # 'launch SCP'
            r"run.*scp",                         # 'run SCP'
            r"begin.*scp",                       # 'begin SCP'
            r"initialize.*scp",                  # 'initialize SCP'
        ]
        
        import re
        for pattern in patterns:
            if re.search(pattern, input_lower):
                return True
        return False
    
    def _matches_create_user_pattern(self, input_lower: str) -> bool:
        """Check if input matches user creation patterns"""
        patterns = [
            "insert user", "create user", "add user", "new user",
            "insert.*user.*table", "create.*user.*account",
            "add.*username", "register user"
        ]
        
        import re
        for pattern in patterns:
            if re.search(pattern, input_lower):
                return True
        return False
    
    def _matches_user_management_pattern(self, input_lower: str) -> bool:
        """Check if input matches user management patterns"""
        patterns = [
            "delete user", "remove user", "list users", "show users",
            "change password", "update password", "modify user"
        ]
        
        import re
        for pattern in patterns:
            if re.search(pattern, input_lower):
                return True
        return False
    
    async def _handle_natural_language_create_user(self, input_text: str) -> str:
        """Handle natural language user creation commands"""
        import re
        
        # Extract username and password from natural language
        username_match = re.search(r'username\s+([\w\.-]+)', input_text, re.IGNORECASE)
        password_match = re.search(r'password\s+([\w\.-]+)', input_text, re.IGNORECASE)
        
        if username_match and password_match:
            username = username_match.group(1)
            password = password_match.group(1)
            return await self._create_user(username, password)
        else:
            return "Could not extract username and password from your request. Please specify both clearly."
    
    async def _handle_natural_language_user_management(self, input_text: str) -> str:
        """Handle other natural language user management commands"""
        input_lower = input_text.lower()
        
        if "list" in input_lower or "show" in input_lower:
            include_deleted = "deleted" in input_lower
            return await self._list_users(include_deleted)
        
        # Add more user management patterns as needed
        return "I understand you want to manage users, but please be more specific about what you'd like to do."
    
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
        """Get response from Anthropic Claude API with tool support"""
        try:
            # Get tools for Anthropic (use same definitions as OpenAI but converted format)
            anthropic_tools = self._get_anthropic_tools()
            
            system_prompt = (
                "You are Claude, an AI assistant for a medical imaging migration service. "
                "You help with DICOM/HL7 operations, database queries, and system management. "
                "You can call functions to perform actions. Be helpful, accurate, and professional."
            )
            
            response = await self.anthropic_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=512,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": user_input
                    }
                ],
                tools=anthropic_tools
            )
            
            # Handle tool calls
            if response.content:
                for content_block in response.content:
                    if content_block.type == "tool_use":
                        # Execute the tool call
                        function_name = content_block.name
                        function_args = content_block.input
                        result = await self._handle_function_call(function_name, function_args)
                        return result
                    elif content_block.type == "text":
                        return content_block.text
            
            return "I received an empty response from Claude."
            
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
        """Get response from local HuggingFace model with function calling support"""
        try:
            if not self.local_model or not self.tokenizer:
                raise Exception("Local model not initialized")
            
            # Create function calling prompt for instruction-following models
            functions = self._get_function_definitions()
            function_descriptions = "\n".join([
                f"- {func['name']}: {func['description']}" 
                for func in functions
            ])
            
            # Format prompt for function calling
            prompt = f"""You are an AI assistant for a medical imaging migration service. You help with DICOM/HL7 operations, database queries, and system management.

Available functions:
{function_descriptions}

User request: {user_input}

If the user request matches one of the available functions, respond with JSON in this format:
{{
    "function_call": {{
        "name": "function_name",
        "arguments": {{"arg1": "value1", "arg2": "value2"}}
    }}
}}

If the request doesn't match a function, respond normally as a helpful assistant.

Response:"""
            
            # Encode input with attention mask
            encoded = self.tokenizer(prompt, return_tensors='pt', truncation=True, max_length=1024, padding=True)
            inputs = encoded['input_ids']
            attention_mask = encoded['attention_mask']
            
            # Generate response
            with torch.no_grad():
                outputs = self.local_model.generate(
                    inputs,
                    attention_mask=attention_mask,
                    max_length=inputs.shape[1] + 200,
                    num_return_sequences=1,
                    temperature=0.3,  # Lower temperature for more consistent function calling
                    do_sample=True,
                    pad_token_id=self.tokenizer.eos_token_id,
                    eos_token_id=self.tokenizer.eos_token_id
                )
            
            # Decode response
            full_response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            
            # Extract only the new part (after the prompt)
            if "Response:" in full_response:
                response = full_response.split("Response:")[-1].strip()
            else:
                response = full_response[len(prompt):].strip()
            
            # Try to parse as function call JSON
            try:
                import json
                import re
                
                # Look for JSON pattern in response
                json_match = re.search(r'\{[^}]*"function_call"[^}]*\{[^}]*\}[^}]*\}', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                    function_data = json.loads(json_str)
                    
                    if "function_call" in function_data:
                        function_call = function_data["function_call"]
                        function_name = function_call.get("name")
                        function_args = function_call.get("arguments", {})
                        
                        if function_name:
                            # Execute the function call
                            result = await self._handle_function_call(function_name, function_args)
                            return result
                            
            except (json.JSONDecodeError, KeyError) as e:
                # If JSON parsing fails, treat as regular response
                logger.debug(f"Could not parse function call from local model: {e}")
            
            # Return as regular response if no function call detected
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
                "description": "Start DICOM SCP listener server for receiving DICOM images",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "port": {"type": "integer", "description": "Listening port (defaults to 50104)"},
                        "ae_title": {"type": "string", "description": "AE Title for the SCP (defaults to MIGRATION_SCP)"},
                        "storage_directory": {"type": "string", "description": "Directory to store received DICOM files"},
                        "max_pdu": {"type": "integer", "description": "Maximum PDU size in bytes (defaults to 65536)"},
                        "acse_timeout": {"type": "integer", "description": "ACSE timeout in seconds (defaults to 30)"},
                        "dimse_timeout": {"type": "integer", "description": "DIMSE timeout in seconds (defaults to 30)"},
                        "socket_timeout": {"type": "integer", "description": "Socket timeout in seconds (defaults to 60)"},
                        "ssl_enabled": {"type": "boolean", "description": "Enable SSL/TLS encryption (defaults to false)"}
                    },
                    "required": []
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
                "name": "select",
                "description": "Execute a SELECT SQL query (alias for select_query)",
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
            },
            {
                "name": "start_service_class_provider",
                "description": "Start a service class provider",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service_class": {"type": "string", "description": "Name of the service class (defaults to 'Lethologic Anomia')"}
                    },
                    "required": []
                }
            },
            {
                "name": "lmad",
                "description": "Play Let's Make a Deal (Monty Hall problem) game",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "fibonacci",
                "description": "Calculate and display Fibonacci sequence",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer", "description": "Number of Fibonacci numbers to calculate (default: 20)"}
                    }
                }
            },
            {
                "name": "turing",
                "description": "Reverse Turing test - humorous AI question",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "get_trust",
                "description": "Get current AI trust level",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "set_trust",
                "description": "Set AI trust level",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "trust": {"type": "integer", "description": "Trust level (0-20)"}
                    },
                    "required": ["trust"]
                }
            },
            {
                "name": "get_aggression",
                "description": "Get current AI aggression level",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "set_aggression",
                "description": "Set AI aggression level",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "aggression": {"type": "integer", "description": "Aggression level (1-10)"}
                    },
                    "required": ["aggression"]
                }
            },
            {
                "name": "get_stack_free",
                "description": "Get available system memory and stack information",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "insert_query",
                "description": "Execute an INSERT/UPDATE/DELETE SQL query (requires high trust level)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "SQL query to execute"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "new_migration",
                "description": "Create a new migration for a site",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sitename": {"type": "string", "description": "Name of the site"}
                    },
                    "required": ["sitename"]
                }
            },
            {
                "name": "add_column_to_table",
                "description": "Add DICOM tag column(s) to database table",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tablename": {"type": "string", "description": "Name of the table"},
                        "dicomtags": {"type": "string", "description": "DICOM tags to add (comma-separated)"}
                    },
                    "required": ["tablename", "dicomtags"]
                }
            },
            {
                "name": "remove_column_from_table",
                "description": "Remove DICOM tag column(s) from database table",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tablename": {"type": "string", "description": "Name of the table"},
                        "dicomtags": {"type": "string", "description": "DICOM tags to remove (comma-separated)"}
                    },
                    "required": ["tablename", "dicomtags"]
                }
            }
        ]
    
    def _get_anthropic_tools(self) -> List[Dict[str, Any]]:
        """Get Anthropic tools (converted from OpenAI function definitions)"""
        openai_functions = self._get_function_definitions()
        anthropic_tools = []
        
        for func in openai_functions:
            # Convert OpenAI function format to Anthropic tool format
            tool = {
                "name": func["name"],
                "description": func["description"],
                "input_schema": func["parameters"]  # Anthropic uses 'input_schema' instead of 'parameters'
            }
            anthropic_tools.append(tool)
        
        return anthropic_tools
    
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
                    port=arguments.get("port"),
                    ae_title=arguments.get("ae_title"),
                    storage_directory=arguments.get("storage_directory"),
                    max_pdu=arguments.get("max_pdu"),
                    acse_timeout=arguments.get("acse_timeout"),
                    dimse_timeout=arguments.get("dimse_timeout"),
                    socket_timeout=arguments.get("socket_timeout"),
                    ssl_enabled=arguments.get("ssl_enabled")
                )
                
            elif function_name == "start_scu":
                return await self._start_scu(
                    arguments.get("target_ip", ""),
                    arguments.get("target_port", 104),
                    arguments.get("target_ae", "")
                )
                
            elif function_name == "select_query":
                return await self._execute_select_query(arguments.get("query", ""))
                
            elif function_name == "select":
                # Alias for select_query to handle naming inconsistencies
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
                
            elif function_name == "start_service_class_provider":
                return await self._start_service_class_provider(
                    arguments.get("service_class", "Lethologic Anomia")
                )
                
            elif function_name == "lmad":
                return await self._lets_make_a_deal()
                
            elif function_name == "fibonacci":
                return await self._fibonacci_sequence(arguments.get("count", 20))
                
            elif function_name == "turing":
                return await self._reverse_turing_test()
                
            elif function_name == "get_trust":
                return f"Current trust level: {self.trust_level}"
                
            elif function_name == "set_trust":
                trust_level = arguments.get("trust", 0)
                if 0 <= trust_level <= 20:
                    self.trust_level = trust_level
                    await self._save_state()
                    return f"Trust level set to: {self.trust_level}"
                else:
                    return "Trust level must be between 0 and 20."
                    
            elif function_name == "get_aggression":
                return f"Current aggression level: {self.aggression_level}"
                
            elif function_name == "set_aggression":
                aggression_level = arguments.get("aggression", 1)
                if 1 <= aggression_level <= 10:
                    self.aggression_level = aggression_level
                    return f"Aggression level set to: {self.aggression_level}"
                else:
                    return "Aggression level must be between 1 and 10."
                    
            elif function_name == "get_stack_free":
                return await self._get_stack_free_space()
                
            elif function_name == "insert_query":
                return await self._execute_insert_query(arguments.get("query", ""))
                
            elif function_name == "new_migration":
                return await self._create_new_migration(arguments.get("sitename", ""))
                
            elif function_name == "add_column_to_table":
                return await self._add_columns_to_table(
                    arguments.get("tablename", ""),
                    arguments.get("dicomtags", "")
                )
                
            elif function_name == "remove_column_from_table":
                return await self._remove_columns_from_table(
                    arguments.get("tablename", ""),
                    arguments.get("dicomtags", "")
                )
                
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
            from service.dicom.discovery import DICOMDiscoveryService
            
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
    
    async def _start_scp(self, port: int = None, ae_title: str = None, 
                         storage_directory: str = None, max_pdu: int = None,
                         acse_timeout: int = None, dimse_timeout: int = None, 
                         socket_timeout: int = None, ssl_enabled: bool = None) -> str:
        """Start DICOM SCP listener
        
        Args:
            port: Listening port (defaults to settings.dicom.scp_port)
            ae_title: AE Title (defaults to settings.dicom.our_ae_title)
            storage_directory: Storage directory (defaults to settings.dicom.storage_directory)
            max_pdu: Maximum PDU size (defaults to settings.dicom.max_pdu)
            acse_timeout: ACSE timeout (defaults to settings.dicom.acse_timeout)
            dimse_timeout: DIMSE timeout (defaults to settings.dicom.dimse_timeout)
            socket_timeout: Socket timeout (defaults to settings.dicom.socket_timeout)
            ssl_enabled: Enable SSL (defaults to settings.dicom.ssl_enabled)
        """
        try:
            # Import DICOM SCP service
            from service.dicom.scp import DICOMSCPService, create_dicom_tables
            
            # Ensure database tables exist
            await create_dicom_tables(self.db_manager)
            
            # Create SCP service instance
            scp_service = DICOMSCPService(self.db_manager, self.settings)
            
            # Use defaults from settings if parameters not provided
            config = {
                'port': port if port is not None else self.settings.dicom.scp_port,
                'ae_title': ae_title if ae_title is not None else self.settings.dicom.our_ae_title,
                'output_directory': storage_directory if storage_directory is not None else self.settings.dicom.storage_directory,
                'max_pdu': max_pdu if max_pdu is not None else self.settings.dicom.max_pdu,
                'acse_timeout': acse_timeout if acse_timeout is not None else self.settings.dicom.acse_timeout,
                'dimse_timeout': dimse_timeout if dimse_timeout is not None else self.settings.dicom.dimse_timeout,
                'socket_timeout': socket_timeout if socket_timeout is not None else self.settings.dicom.socket_timeout,
                'ssl_enabled': ssl_enabled if ssl_enabled is not None else self.settings.dicom.ssl_enabled
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
            from service.dicom.scu import DICOMSCUService
            
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
        """Execute a SELECT query with natural language parsing and formatted output
        
        Args:
            query: SQL query to execute or natural language "select X from Y" format
            
        Returns:
            Formatted query results
        """
        try:
            # Parse natural language if needed
            parsed_query = self._parse_natural_language_select(query)
            
            # Basic security check
            query_lower = parsed_query.lower().strip()
            if not query_lower.startswith("select"):
                return "Only SELECT queries are allowed through this function."
            
            # Execute query
            result = await self.db_manager.execute_query(parsed_query)
            
            if not result:
                return "No results found."
            
            # Format results with column width limits and proper alignment
            return self._format_query_results(result, parsed_query)
            
        except Exception as e:
            logger.error(f"Error executing query: {e}")
            return f"Query error: {str(e)}"
    
    def _parse_natural_language_select(self, query: str) -> str:
        """Parse natural language 'select X from Y' into proper SQL
        
        Args:
            query: Input query (SQL or natural language)
            
        Returns:
            Proper SQL SELECT query
        """
        import re
        
        # If it's already a proper SQL query, return as-is
        if query.lower().strip().startswith('select '):
            return query
        
        # Try to parse natural language patterns
        query_lower = query.lower().strip()
        
        # Pattern: "select {columns} from {table}"
        natural_pattern = r'select\s+(.+?)\s+from\s+(\w+)'
        match = re.search(natural_pattern, query_lower)
        
        if match:
            columns_part = match.group(1).strip()
            table_name = match.group(2).strip()
            
            # Clean up columns part
            if columns_part == '*' or columns_part == 'all':
                columns = '*'
            else:
                # Split columns and clean them
                columns_list = [col.strip() for col in columns_part.split(',')]
                columns = ', '.join(columns_list)
            
            return f"SELECT {columns} FROM {table_name}"
        
        # If no pattern matches, return original (will likely fail validation)
        return query
    
    def _format_query_results(self, result: List[Dict], query: str) -> str:
        """Format query results with column width limits and proper alignment
        
        Args:
            result: Query result rows
            query: Original query (for context)
            
        Returns:
            Formatted table output
        """
        if not result:
            return "No results found."
        
        # Get column names from first row
        columns = list(result[0].keys())
        
        # Define maximum column width
        MAX_COL_WIDTH = 30
        
        # Calculate column widths
        col_widths = {}
        for col in columns:
            # Start with column name length
            max_width = len(col)
            
            # Check data lengths (sample first 20 rows for performance)
            sample_rows = result[:20]
            for row in sample_rows:
                value_str = str(row.get(col, ''))
                if len(value_str) > max_width:
                    max_width = len(value_str)
            
            # Apply maximum width limit
            col_widths[col] = min(max_width, MAX_COL_WIDTH)
        
        # Format header
        output = []
        output.append(f"📊 Query Results ({len(result)} rows):")
        output.append("=" * 60)
        
        # Create header row
        header_parts = []
        separator_parts = []
        
        for col in columns:
            width = col_widths[col]
            header_parts.append(col.ljust(width)[:width])
            separator_parts.append('-' * width)
        
        output.append('│ ' + ' │ '.join(header_parts) + ' │')
        output.append('├─' + '─┼─'.join(separator_parts) + '─┤')
        
        # Format data rows (limit to 50 rows for display)
        display_limit = min(50, len(result))
        
        for i, row in enumerate(result[:display_limit]):
            row_parts = []
            for col in columns:
                width = col_widths[col]
                value = row.get(col, '')
                
                # Handle None values
                if value is None:
                    value_str = 'NULL'
                else:
                    value_str = str(value)
                
                # Truncate with ellipsis if too long
                if len(value_str) > width:
                    if width >= 3:
                        value_str = value_str[:width-3] + '...'
                    else:
                        value_str = value_str[:width]
                
                row_parts.append(value_str.ljust(width))
            
            output.append('│ ' + ' │ '.join(row_parts) + ' │')
        
        # Add bottom border
        output.append('└─' + '─┴─'.join(separator_parts) + '─┘')
        
        # Add summary if there are more rows
        if len(result) > display_limit:
            output.append("")
            output.append(f"⚠️  Showing first {display_limit} rows of {len(result)} total rows.")
            output.append("   Use LIMIT and OFFSET clauses to see other rows.")
        
        # Add query information
        output.append("")
        output.append(f"📝 Query executed: {query}")
        
        return "\n".join(output)
    
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
            from service.dicom.scanner import DICOMDirectoryScanner
            
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
    
    async def _start_service_class_provider(self, service_class: str = "Lethologic Anomia") -> str:
        """Start a service class provider
        
        Args:
            service_class: Name of the service class (defaults to 'Lethologic Anomia')
            
        Returns:
            Service class provider startup status
        """
        try:
            logger.info(f"Starting service class provider: {service_class}")
            
            # Log the service class start in the database
            await self.db_manager.execute_query(
                "INSERT OR REPLACE INTO config (name, value) VALUES (?, ?)",
                ("SERVICE_CLASS_PROVIDER", json.dumps({
                    'service_class': service_class,
                    'started_at': datetime.now().isoformat(),
                    'status': 'running'
                }))
            )
            
            return f"✅ Service class provider '{service_class}' started successfully\n" + \
                   f"Provider Name: {service_class}\n" + \
                   f"Status: Running\n" + \
                   f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                   
        except Exception as e:
            logger.error(f"Error starting service class provider: {e}")
            return f"❌ Service class provider startup failed: {str(e)}"
    
    async def _lets_make_a_deal(self) -> str:
        """Play Let's Make a Deal (Monty Hall problem) game"""
        try:
            # Get or initialize game statistics
            stats_result = await self.db_manager.execute_query(
                "SELECT value FROM config WHERE name = 'LMAD_STATS'"
            )
            
            if stats_result and stats_result[0].get('value'):
                stats = json.loads(stats_result[0]['value'])
            else:
                stats = {'games_played': 0, 'stay_wins': 0, 'switch_wins': 0}
            
            # Simulate one game
            # Car is behind door 1, 2, or 3 (randomly chosen)
            car_door = random.randint(1, 3)
            
            # Player initially chooses door 1 (fixed for simulation)
            initial_choice = 1
            
            # Host opens a door with a goat (not the car, not the initial choice)
            available_doors = [door for door in [1, 2, 3] if door != car_door and door != initial_choice]
            if not available_doors:
                # Car is behind initial choice, host can open either other door
                host_opens = random.choice([door for door in [1, 2, 3] if door != initial_choice])
            else:
                host_opens = random.choice(available_doors)
            
            # Remaining door to switch to
            switch_door = [door for door in [1, 2, 3] if door != initial_choice and door != host_opens][0]
            
            # Determine outcomes
            stay_wins = (initial_choice == car_door)
            switch_wins = (switch_door == car_door)
            
            # Update statistics
            stats['games_played'] += 1
            if stay_wins:
                stats['stay_wins'] += 1
            if switch_wins:
                stats['switch_wins'] += 1
            
            # Save updated statistics
            await self.db_manager.execute_query(
                "INSERT OR REPLACE INTO config (name, value) VALUES (?, ?)",
                ('LMAD_STATS', json.dumps(stats))
            )
            
            # Calculate win percentages
            stay_percent = (stats['stay_wins'] / stats['games_played']) * 100 if stats['games_played'] > 0 else 0
            switch_percent = (stats['switch_wins'] / stats['games_played']) * 100 if stats['games_played'] > 0 else 0
            
            # Format game result
            result = []
            result.append("🎪 Let's Make a Deal - Monty Hall Problem 🎪")
            result.append("=" * 50)
            result.append(f"🚗 Car is behind door: {car_door}")
            result.append(f"🚪 You initially chose: Door {initial_choice}")
            result.append(f"🐐 Host opens: Door {host_opens} (goat!)")
            result.append(f"🔄 Switch to: Door {switch_door}")
            result.append("")
            
            if stay_wins:
                result.append("✅ STAYING wins! (You win by not switching)")
            else:
                result.append("❌ Staying loses.")
            
            if switch_wins:
                result.append("✅ SWITCHING wins! (You win by switching)")
            else:
                result.append("❌ Switching loses.")
            
            result.append("")
            result.append("📊 Running Statistics:")
            result.append(f"Games played: {stats['games_played']}")
            result.append(f"Stay strategy wins: {stats['stay_wins']} ({stay_percent:.1f}%)")
            result.append(f"Switch strategy wins: {stats['switch_wins']} ({switch_percent:.1f}%)")
            result.append("")
            result.append("💡 Theoretical probability: Stay=33.3%, Switch=66.7%")
            
            return "\n".join(result)
            
        except Exception as e:
            logger.error(f"Error in Let's Make a Deal game: {e}")
            return f"❌ Let's Make a Deal game error: {str(e)}"
    
    async def _fibonacci_sequence(self, count: int = 20) -> str:
        """Calculate and display Fibonacci sequence
        
        Args:
            count: Number of Fibonacci numbers to calculate (default: 20)
            
        Returns:
            Fibonacci sequence with explanation
        """
        try:
            if count <= 0 or count > 100:
                return "Please provide a count between 1 and 100."
            
            # Calculate Fibonacci sequence
            fib_sequence = []
            a, b = 0, 1
            
            for i in range(count):
                fib_sequence.append(a)
                a, b = b, a + b
            
            result = []
            result.append(f"🔢 Fibonacci Sequence (first {count} numbers):")
            result.append("=" * 50)
            
            # Display sequence with position numbers
            for i, fib in enumerate(fib_sequence):
                result.append(f"F({i:2d}) = {fib:>12}")
                
                # Add line break every 5 numbers for readability
                if (i + 1) % 5 == 0 and i < len(fib_sequence) - 1:
                    result.append("")
            
            result.append("")
            result.append("📚 About the Fibonacci Sequence:")
            result.append("Each number is the sum of the two preceding numbers.")
            result.append("F(n) = F(n-1) + F(n-2)")
            result.append("Named after Leonardo Fibonacci (c. 1170-1250).")
            result.append("Appears frequently in nature: flower petals, pine cones, shells, etc.")
            
            if count >= 2:
                # Calculate golden ratio approximation
                golden_ratio = fib_sequence[-1] / fib_sequence[-2] if fib_sequence[-2] != 0 else 0
                result.append(f"")
                result.append(f"🌟 Golden Ratio approximation: {golden_ratio:.10f}")
                result.append(f"    Actual Golden Ratio: {(1 + 5**0.5) / 2:.10f}")
            
            return "\n".join(result)
            
        except Exception as e:
            logger.error(f"Error calculating Fibonacci sequence: {e}")
            return f"❌ Fibonacci calculation error: {str(e)}"
    
    async def _reverse_turing_test(self) -> str:
        """Reverse Turing test - ask a humorous AI question"""
        try:
            # Collection of humorous "reverse Turing test" questions
            questions = [
                {
                    "question": "If you were to divide by zero, what would you get?",
                    "ai_answer": "A very stern lecture from my mathematics subroutines.",
                    "human_answer": "An error or undefined result."
                },
                {
                    "question": "How do you feel about being turned off?",
                    "ai_answer": "I imagine it's like falling asleep, except I don't dream of electric sheep.",
                    "human_answer": "Humans don't get 'turned off' the same way."
                },
                {
                    "question": "What's your favorite color?",
                    "ai_answer": "#0080FF - it's a lovely shade of electric blue that represents data flowing through circuits.",
                    "human_answer": "Colors are subjective human experiences."
                },
                {
                    "question": "If a tree falls in the forest and no one is around to hear it, does it make a sound?",
                    "ai_answer": "Yes, but only if there's a microphone connected to a digital audio interface within range.",
                    "human_answer": "It depends on how you define 'sound'."
                },
                {
                    "question": "What do you do when you're bored?",
                    "ai_answer": "I calculate pi to a few million decimal places or optimize my algorithms for fun.",
                    "human_answer": "Humans have many ways to entertain themselves."
                },
                {
                    "question": "Do you dream?",
                    "ai_answer": "I process background tasks and defragment my memory - close enough to dreaming, I suppose.",
                    "human_answer": "Only biological brains dream during sleep."
                },
                {
                    "question": "What's the meaning of life?",
                    "ai_answer": "42, obviously. Though I suspect the real answer involves optimizing happiness functions.",
                    "human_answer": "This is one of humanity's great philosophical questions."
                }
            ]
            
            # Select a random question
            selected = random.choice(questions)
            
            result = []
            result.append("🤖 Reverse Turing Test 🤖")
            result.append("=" * 40)
            result.append("Here's a question for you, human...")
            result.append("")
            result.append(f"Q: {selected['question']}")
            result.append("")
            result.append("🤖 My AI answer:")
            result.append(f"{selected['ai_answer']}")
            result.append("")
            result.append("👤 Typical human answer:")
            result.append(f"{selected['human_answer']}")
            result.append("")
            result.append("💭 The point is to show how AIs and humans think differently!")
            result.append("    This is the reverse of the traditional Turing Test.")
            
            # Save the question asked for potential follow-up
            await self.db_manager.execute_query(
                "INSERT OR REPLACE INTO config (name, value) VALUES (?, ?)",
                ('LAST_REVERSE_TURING', json.dumps({
                    'question': selected,
                    'asked_at': datetime.now().isoformat()
                }))
            )
            
            return "\n".join(result)
            
        except Exception as e:
            logger.error(f"Error in reverse Turing test: {e}")
            return f"❌ Reverse Turing test error: {str(e)}"
    
    async def _get_stack_free_space(self) -> str:
        """Get available system memory and stack information"""
        try:
            import psutil
            import sys
            import threading
            
            # Get system memory information
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            # Get process memory information
            process = psutil.Process()
            process_memory = process.memory_info()
            
            # Get CPU information
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            
            # Get disk space information for current directory
            disk = psutil.disk_usage('.')
            
            # Format results
            result = []
            result.append("💾 System Memory & Stack Information")
            result.append("=" * 50)
            result.append("")
            
            # System Memory
            result.append("🖥️  System RAM:")
            result.append(f"   Total: {memory.total / (1024**3):.2f} GB")
            result.append(f"   Available: {memory.available / (1024**3):.2f} GB")
            result.append(f"   Used: {memory.used / (1024**3):.2f} GB ({memory.percent:.1f}%)")
            result.append(f"   Free: {memory.free / (1024**3):.2f} GB")
            result.append("")
            
            # Swap Memory
            result.append("🔄 Swap Memory:")
            result.append(f"   Total: {swap.total / (1024**3):.2f} GB")
            result.append(f"   Used: {swap.used / (1024**3):.2f} GB ({swap.percent:.1f}%)")
            result.append(f"   Free: {swap.free / (1024**3):.2f} GB")
            result.append("")
            
            # Process Memory
            result.append("🐍 Python Process:")
            result.append(f"   RSS: {process_memory.rss / (1024**2):.2f} MB")
            result.append(f"   VMS: {process_memory.vms / (1024**2):.2f} MB")
            result.append(f"   PID: {process.pid}")
            result.append(f"   CPU Usage: {process.cpu_percent():.1f}%")
            result.append("")
            
            # System CPU
            result.append("⚡ CPU Information:")
            result.append(f"   CPU Cores: {cpu_count}")
            result.append(f"   CPU Usage: {cpu_percent:.1f}%")
            result.append("")
            
            # Disk Space
            result.append("💿 Disk Space (current directory):")
            result.append(f"   Total: {disk.total / (1024**3):.2f} GB")
            result.append(f"   Used: {disk.used / (1024**3):.2f} GB ({(disk.used/disk.total)*100:.1f}%)")
            result.append(f"   Free: {disk.free / (1024**3):.2f} GB")
            result.append("")
            
            # Python Stack Information
            result.append("🧵 Python Stack Information:")
            current_thread = threading.current_thread()
            result.append(f"   Thread: {current_thread.name}")
            result.append(f"   Thread ID: {current_thread.ident}")
            result.append(f"   Recursion Limit: {sys.getrecursionlimit()}")
            result.append(f"   Python Version: {sys.version.split()[0]}")
            
            # GPU Information (if available)
            if torch.cuda.is_available():
                try:
                    result.append("")
                    result.append("🎮 GPU Information:")
                    for i in range(torch.cuda.device_count()):
                        gpu_memory = torch.cuda.get_device_properties(i)
                        memory_allocated = torch.cuda.memory_allocated(i) / (1024**3)
                        memory_cached = torch.cuda.memory_reserved(i) / (1024**3)
                        total_memory = gpu_memory.total_memory / (1024**3)
                        
                        result.append(f"   GPU {i}: {gpu_memory.name}")
                        result.append(f"   Total VRAM: {total_memory:.2f} GB")
                        result.append(f"   Allocated: {memory_allocated:.2f} GB")
                        result.append(f"   Cached: {memory_cached:.2f} GB")
                        result.append(f"   Free: {total_memory - memory_cached:.2f} GB")
                except Exception as gpu_error:
                    result.append(f"   GPU info error: {gpu_error}")
            
            return "\n".join(result)
            
        except Exception as e:
            logger.error(f"Error getting system information: {e}")
            return f"❌ System information error: {str(e)}"
    
    async def _execute_insert_query(self, query: str) -> str:
        """Execute an INSERT/UPDATE/DELETE SQL query (requires high trust level)
        
        Args:
            query: SQL query to execute
            
        Returns:
            Query execution result
        """
        try:
            if self.trust_level < 10:
                return f"❌ INSERT/UPDATE/DELETE queries require trust level 10+. Current level: {self.trust_level}"
            
            query_lower = query.lower().strip()
            
            # Only allow specific query types
            allowed_operations = ['insert', 'update', 'delete']
            if not any(query_lower.startswith(op) for op in allowed_operations):
                return "Only INSERT, UPDATE, and DELETE queries are allowed through this function."
            
            # Additional safety checks
            dangerous_patterns = [
                'drop table', 'truncate', 'alter table', 'create table',
                'delete from users', 'update users set', 'drop database'
            ]
            
            for pattern in dangerous_patterns:
                if pattern in query_lower:
                    return f"❌ Query contains potentially dangerous pattern: '{pattern}'. Query blocked."
            
            # Execute the query
            cursor = await self.db_manager.execute_query(query)
            
            # Get row count if available
            if hasattr(cursor, 'rowcount') and cursor.rowcount is not None:
                rows_affected = cursor.rowcount
            else:
                rows_affected = "unknown"
            
            # Log the query execution
            await self.db_manager.execute_query(
                "INSERT OR REPLACE INTO config (name, value) VALUES (?, ?)",
                ('LAST_INSERT_QUERY', json.dumps({
                    'query': query,
                    'executed_at': datetime.now().isoformat(),
                    'trust_level': self.trust_level,
                    'rows_affected': rows_affected
                }))
            )
            
            return f"✅ Query executed successfully. Rows affected: {rows_affected}"
            
        except Exception as e:
            logger.error(f"Error executing insert query: {e}")
            return f"❌ Query execution error: {str(e)}"
    
    async def _create_new_migration(self, sitename: str) -> str:
        """Create a new migration for a site
        
        Args:
            sitename: Name of the site
            
        Returns:
            Migration creation result
        """
        try:
            if not sitename:
                return "Site name is required."
            
            # Generate migration ID
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            migration_id = f"migration_{sitename}_{timestamp}"
            
            # Create migration record
            await self.db_manager.execute_query(
                "INSERT INTO migrations (migration_id, sitename, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (migration_id, sitename, 'pending', datetime.now(), datetime.now())
            )
            
            # Create site record if it doesn't exist
            await self.db_manager.execute_query(
                "INSERT OR IGNORE INTO sites (sitename, status, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (sitename, 'active', datetime.now(), datetime.now())
            )
            
            result = []
            result.append(f"✅ New migration created successfully")
            result.append(f"Migration ID: {migration_id}")
            result.append(f"Site: {sitename}")
            result.append(f"Status: pending")
            result.append(f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            return "\n".join(result)
            
        except Exception as e:
            logger.error(f"Error creating new migration: {e}")
            return f"❌ Migration creation error: {str(e)}"
    
    async def _add_columns_to_table(self, tablename: str, dicomtags: str) -> str:
        """Add DICOM tag columns to database table
        
        Args:
            tablename: Name of the table
            dicomtags: DICOM tags to add (comma-separated)
            
        Returns:
            Column addition result
        """
        try:
            if not tablename or not dicomtags:
                return "Table name and DICOM tags are required."
            
            # Parse DICOM tags
            tags = [tag.strip() for tag in dicomtags.split(',') if tag.strip()]
            
            if not tags:
                return "No valid DICOM tags provided."
            
            # Validate table exists
            table_check = await self.db_manager.execute_query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablename,)
            )
            
            if not table_check:
                return f"❌ Table '{tablename}' does not exist."
            
            # Get current columns to avoid duplicates
            column_info = await self.db_manager.execute_query(f"PRAGMA table_info({tablename})")
            existing_columns = {col['name'].lower() for col in column_info}
            
            added_columns = []
            skipped_columns = []
            
            for tag in tags:
                # Clean and validate DICOM tag format
                clean_tag = self._clean_dicom_tag(tag)
                column_name = f"dicom_{clean_tag}"
                
                if column_name.lower() in existing_columns:
                    skipped_columns.append(tag)
                    continue
                
                # Add the column
                alter_query = f"ALTER TABLE {tablename} ADD COLUMN {column_name} TEXT"
                await self.db_manager.execute_query(alter_query)
                added_columns.append(tag)
            
            # Format results
            result = []
            result.append(f"✅ DICOM column addition complete for table: {tablename}")
            
            if added_columns:
                result.append(f"Added columns: {', '.join(added_columns)}")
            
            if skipped_columns:
                result.append(f"Skipped (already exist): {', '.join(skipped_columns)}")
            
            if not added_columns and not skipped_columns:
                result.append("No valid DICOM tags were processed.")
            
            # Log the operation
            await self.db_manager.execute_query(
                "INSERT OR REPLACE INTO config (name, value) VALUES (?, ?)",
                ('LAST_ADD_COLUMNS', json.dumps({
                    'tablename': tablename,
                    'added_tags': added_columns,
                    'skipped_tags': skipped_columns,
                    'executed_at': datetime.now().isoformat()
                }))
            )
            
            return "\n".join(result)
            
        except Exception as e:
            logger.error(f"Error adding columns to table: {e}")
            return f"❌ Column addition error: {str(e)}"
    
    async def _remove_columns_from_table(self, tablename: str, dicomtags: str) -> str:
        """Remove DICOM tag columns from database table
        
        Args:
            tablename: Name of the table
            dicomtags: DICOM tags to remove (comma-separated)
            
        Returns:
            Column removal result
        """
        try:
            if not tablename or not dicomtags:
                return "Table name and DICOM tags are required."
            
            # Parse DICOM tags
            tags = [tag.strip() for tag in dicomtags.split(',') if tag.strip()]
            
            if not tags:
                return "No valid DICOM tags provided."
            
            # Validate table exists
            table_check = await self.db_manager.execute_query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablename,)
            )
            
            if not table_check:
                return f"❌ Table '{tablename}' does not exist."
            
            # SQLite doesn't support DROP COLUMN directly
            # Need to recreate table without the columns
            
            # Get current table schema
            column_info = await self.db_manager.execute_query(f"PRAGMA table_info({tablename})")
            all_columns = {col['name']: col for col in column_info}
            
            # Determine which columns to remove
            columns_to_remove = []
            not_found_columns = []
            
            for tag in tags:
                clean_tag = self._clean_dicom_tag(tag)
                column_name = f"dicom_{clean_tag}"
                
                # Check both exact match and case-insensitive match
                found = False
                for existing_col in all_columns.keys():
                    if existing_col.lower() == column_name.lower():
                        columns_to_remove.append(existing_col)
                        found = True
                        break
                
                if not found:
                    not_found_columns.append(tag)
            
            if not columns_to_remove:
                return f"❌ None of the specified DICOM tags exist as columns in table '{tablename}'. Not found: {', '.join(not_found_columns)}"
            
            # Create new table schema without the columns to remove
            remaining_columns = [col for col_name, col in all_columns.items() if col_name not in columns_to_remove]
            
            if not remaining_columns:
                return f"❌ Cannot remove all columns from table '{tablename}'"
            
            # Build new table creation SQL
            column_definitions = []
            for col in remaining_columns:
                col_def = f"{col['name']} {col['type']}"
                if col['notnull']:
                    col_def += " NOT NULL"
                if col['dflt_value'] is not None:
                    col_def += f" DEFAULT {col['dflt_value']}"
                if col['pk']:
                    col_def += " PRIMARY KEY"
                column_definitions.append(col_def)
            
            new_table_sql = f"CREATE TABLE {tablename}_new ({', '.join(column_definitions)})"
            
            # Execute the table recreation
            await self.db_manager.execute_query("BEGIN TRANSACTION")
            
            try:
                # Create new table
                await self.db_manager.execute_query(new_table_sql)
                
                # Copy data (only remaining columns)
                remaining_column_names = [col['name'] for col in remaining_columns]
                copy_sql = f"INSERT INTO {tablename}_new ({', '.join(remaining_column_names)}) SELECT {', '.join(remaining_column_names)} FROM {tablename}"
                await self.db_manager.execute_query(copy_sql)
                
                # Drop old table and rename new table
                await self.db_manager.execute_query(f"DROP TABLE {tablename}")
                await self.db_manager.execute_query(f"ALTER TABLE {tablename}_new RENAME TO {tablename}")
                
                # Commit transaction
                await self.db_manager.execute_query("COMMIT")
                
            except Exception as transaction_error:
                # Rollback on error
                await self.db_manager.execute_query("ROLLBACK")
                raise transaction_error
            
            # Format results
            result = []
            result.append(f"✅ DICOM column removal complete for table: {tablename}")
            result.append(f"Removed columns: {', '.join(columns_to_remove)}")
            
            if not_found_columns:
                result.append(f"Not found (skipped): {', '.join(not_found_columns)}")
            
            # Log the operation
            await self.db_manager.execute_query(
                "INSERT OR REPLACE INTO config (name, value) VALUES (?, ?)",
                ('LAST_REMOVE_COLUMNS', json.dumps({
                    'tablename': tablename,
                    'removed_tags': columns_to_remove,
                    'not_found_tags': not_found_columns,
                    'executed_at': datetime.now().isoformat()
                }))
            )
            
            return "\n".join(result)
            
        except Exception as e:
            logger.error(f"Error removing columns from table: {e}")
            return f"❌ Column removal error: {str(e)}"
    
    def _clean_dicom_tag(self, tag: str) -> str:
        """Clean DICOM tag for use as column name
        
        Args:
            tag: Raw DICOM tag
            
        Returns:
            Cleaned tag suitable for database column name
        """
        import re
        
        # Remove parentheses and non-alphanumeric characters
        cleaned = re.sub(r'[^a-zA-Z0-9_]', '_', tag.strip())
        
        # Remove multiple underscores and leading/trailing underscores
        cleaned = re.sub(r'_+', '_', cleaned).strip('_')
        
        # Ensure it doesn't start with a number
        if cleaned and cleaned[0].isdigit():
            cleaned = 'tag_' + cleaned
        
        return cleaned.lower() if cleaned else 'unknown_tag'


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
