"""
Speech Service

Provides speech-to-text and text-to-speech capabilities using various
AI models and services for voice interface functionality.
"""

import asyncio
import os
import io
import json
import tempfile
import wave
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import numpy as np

# Speech processing libraries
try:
    import speech_recognition as sr
    SPEECH_RECOGNITION_AVAILABLE = True
except ImportError:
    SPEECH_RECOGNITION_AVAILABLE = False

try:
    import pydub
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

try:
    import gtts
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

try:
    from transformers import pipeline
    import torch
    TRANSFORMERS_SPEECH_AVAILABLE = True
except ImportError:
    TRANSFORMERS_SPEECH_AVAILABLE = False

from ...core.logging import get_logger
from ...core.database import DatabaseManager
from ...core.config import Settings

logger = get_logger(__name__)


class SpeechEngine(Enum):
    """Speech Processing Engines"""
    GOOGLE = "google"
    WHISPER = "whisper"
    AZURE = "azure"
    AWS = "aws"
    SPHINX = "sphinx"
    GTTS = "gtts"


class AudioFormat(Enum):
    """Supported Audio Formats"""
    WAV = "wav"
    MP3 = "mp3"
    FLAC = "flac"
    M4A = "m4a"
    OGG = "ogg"


class ProcessingStatus(Enum):
    """Speech Processing Status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SpeechRequest:
    """Speech Processing Request"""
    request_id: str
    request_type: str  # "stt" or "tts"
    input_data: Union[bytes, str]
    engine: SpeechEngine
    parameters: Dict[str, Any]
    created_at: datetime
    status: ProcessingStatus = ProcessingStatus.PENDING


@dataclass
class SpeechResult:
    """Speech Processing Result"""
    request_id: str
    success: bool
    result: Optional[Union[str, bytes]] = None
    confidence: Optional[float] = None
    error: Optional[str] = None
    processing_time: Optional[float] = None
    engine_used: Optional[str] = None


class SpeechService:
    """
    Speech Service
    
    Provides comprehensive speech processing capabilities:
    - Speech-to-text (STT) transcription
    - Text-to-speech (TTS) synthesis
    - Multiple engine support (Google, Whisper, Azure, AWS)
    - Audio format conversion
    - Batch processing
    - Voice interface integration
    - Medical terminology support
    """
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        """
        Initialize speech service
        
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
            'temp_directory': './temp/speech/',
            'max_concurrent_requests': 5,
            'default_stt_engine': SpeechEngine.GOOGLE,
            'default_tts_engine': SpeechEngine.GTTS,
            'default_language': 'en-US',
            'audio_timeout_seconds': 30,
            'phrase_timeout_seconds': 5,
            'enable_noise_reduction': True,
            'sample_rate': 16000,
            'chunk_size': 1024
        }
        
        # Speech engines
        self.recognizers: Dict[SpeechEngine, Any] = {}
        self.tts_engines: Dict[SpeechEngine, Any] = {}
        self.setup_engines()
        
        # Processing queue
        self.request_queue: asyncio.Queue = asyncio.Queue()
        self.processing_tasks: Dict[str, asyncio.Task] = {}
        self.worker_tasks: List[asyncio.Task] = []
        
        # Statistics
        self.stt_requests_processed = 0
        self.tts_requests_processed = 0
        self.requests_failed = 0
        self.total_processing_time = 0.0
        self.total_audio_duration = 0.0
        
        logger.info("Speech Service initialized")
    
    def configure(self, config: Dict[str, Any]) -> bool:
        """
        Configure the speech service
        
        Args:
            config: Configuration dictionary
            
        Returns:
            True if configuration successful
        """
        try:
            self.config.update(config)
            
            # Create directories
            os.makedirs(self.config['temp_directory'], exist_ok=True)
            
            self.is_configured = True
            logger.info(f"Speech service configured (STT: {self.config['default_stt_engine']}, TTS: {self.config['default_tts_engine']})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to configure speech service: {e}")
            return False
    
    def setup_engines(self):
        """Setup speech processing engines"""
        try:
            # Speech recognition engines
            if SPEECH_RECOGNITION_AVAILABLE:
                recognizer = sr.Recognizer()
                recognizer.energy_threshold = 300
                recognizer.dynamic_energy_threshold = True
                recognizer.pause_threshold = 0.8
                recognizer.phrase_threshold = 0.3
                
                self.recognizers[SpeechEngine.GOOGLE] = recognizer
                self.recognizers[SpeechEngine.SPHINX] = recognizer
                
            # TTS engines
            if GTTS_AVAILABLE:
                self.tts_engines[SpeechEngine.GTTS] = gTTS
                
            # Whisper model for advanced STT
            if TRANSFORMERS_SPEECH_AVAILABLE:
                try:
                    self.recognizers[SpeechEngine.WHISPER] = pipeline(
                        "automatic-speech-recognition",
                        model="openai/whisper-base",
                        device=0 if torch.cuda.is_available() else -1
                    )
                except Exception as e:
                    logger.warning(f"Failed to load Whisper model: {e}")
                    
        except Exception as e:
            logger.error(f"Failed to setup speech engines: {e}")
    
    async def start(self) -> bool:
        """
        Start the speech service
        
        Returns:
            True if started successfully
        """
        if not self.is_configured:
            # Use default configuration
            if not self.configure({}):
                logger.error("Failed to configure speech service with defaults")
                return False
        
        if self.is_running:
            logger.warning("Speech service already running")
            return True
        
        try:
            # Check dependencies
            if not SPEECH_RECOGNITION_AVAILABLE:
                logger.warning("SpeechRecognition library not available")
            if not GTTS_AVAILABLE:
                logger.warning("gTTS library not available")
            if not PYDUB_AVAILABLE:
                logger.warning("pydub library not available - limited audio format support")
            
            # Start worker tasks
            worker_count = self.config['max_concurrent_requests']
            for i in range(worker_count):
                task = asyncio.create_task(
                    self._processing_worker(f"speech-worker-{i}")
                )
                self.worker_tasks.append(task)
            
            # Start cleanup task
            cleanup_task = asyncio.create_task(self._cleanup_temp_files())
            self.worker_tasks.append(cleanup_task)
            
            self.is_running = True
            logger.info(f"Speech service started with {worker_count} workers")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start speech service: {e}")
            return False
    
    async def stop(self) -> bool:
        """
        Stop the speech service
        
        Returns:
            True if stopped successfully
        """
        if not self.is_running:
            return True
        
        try:
            logger.info("Stopping speech service...")
            
            self.is_running = False
            
            # Cancel all worker tasks
            for task in self.worker_tasks:
                if not task.done():
                    task.cancel()
            
            # Wait for tasks to complete
            if self.worker_tasks:
                await asyncio.gather(*self.worker_tasks, return_exceptions=True)
            
            # Cancel processing tasks
            for task in self.processing_tasks.values():
                if not task.done():
                    task.cancel()
            
            # Clear queues and tasks
            self.worker_tasks.clear()
            self.processing_tasks.clear()
            
            logger.info("Speech service stopped")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping speech service: {e}")
            return False
    
    async def speech_to_text(self, audio_data: bytes, 
                           engine: Optional[SpeechEngine] = None,
                           language: Optional[str] = None,
                           parameters: Optional[Dict[str, Any]] = None) -> str:
        """
        Convert speech audio to text
        
        Args:
            audio_data: Audio data in bytes
            engine: Speech recognition engine to use
            language: Language code for recognition
            parameters: Additional processing parameters
            
        Returns:
            Processing request ID
        """
        try:
            # Generate request ID
            request_id = f"stt_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.processing_tasks)}"
            
            # Use default engine if not specified
            if not engine:
                engine = self.config['default_stt_engine']
            
            # Prepare parameters
            params = {
                'language': language or self.config['default_language'],
                'enable_noise_reduction': self.config['enable_noise_reduction']
            }
            if parameters:
                params.update(parameters)
            
            # Create processing request
            request = SpeechRequest(
                request_id=request_id,
                request_type="stt",
                input_data=audio_data,
                engine=engine,
                parameters=params,
                created_at=datetime.now()
            )
            
            # Add to queue
            await self.request_queue.put(request)
            
            logger.info(f"Queued STT request: {request_id}")
            return request_id
            
        except Exception as e:
            logger.error(f"Error queuing STT request: {e}")
            raise
    
    async def text_to_speech(self, text: str, 
                           engine: Optional[SpeechEngine] = None,
                           language: Optional[str] = None,
                           voice: Optional[str] = None,
                           parameters: Optional[Dict[str, Any]] = None) -> str:
        """
        Convert text to speech audio
        
        Args:
            text: Text to synthesize
            engine: TTS engine to use
            language: Language code for synthesis
            voice: Voice model to use
            parameters: Additional processing parameters
            
        Returns:
            Processing request ID
        """
        try:
            # Generate request ID
            request_id = f"tts_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.processing_tasks)}"
            
            # Use default engine if not specified
            if not engine:
                engine = self.config['default_tts_engine']
            
            # Prepare parameters
            params = {
                'language': language or self.config['default_language'],
                'voice': voice,
                'speed': 1.0,
                'pitch': 0.0
            }
            if parameters:
                params.update(parameters)
            
            # Create processing request
            request = SpeechRequest(
                request_id=request_id,
                request_type="tts",
                input_data=text,
                engine=engine,
                parameters=params,
                created_at=datetime.now()
            )
            
            # Add to queue
            await self.request_queue.put(request)
            
            logger.info(f"Queued TTS request: {request_id}")
            return request_id
            
        except Exception as e:
            logger.error(f"Error queuing TTS request: {e}")
            raise
    
    async def _processing_worker(self, worker_name: str):
        """
        Speech processing worker
        
        Args:
            worker_name: Name of the worker
        """
        logger.info(f"Speech processing worker {worker_name} started")
        
        while self.is_running:
            try:
                # Get request from queue with timeout
                try:
                    request = await asyncio.wait_for(
                        self.request_queue.get(),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Process the request
                logger.debug(f"Worker {worker_name} processing request: {request.request_id}")
                
                # Create processing task
                task = asyncio.create_task(
                    self._process_speech_request(request)
                )
                self.processing_tasks[request.request_id] = task
                
                # Wait for completion
                try:
                    await task
                except Exception as e:
                    logger.error(f"Speech processing failed for {request.request_id}: {e}")
                    self.requests_failed += 1
                
                # Mark queue task done
                self.request_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Speech worker {worker_name} error: {e}")
                await asyncio.sleep(1)
        
        logger.info(f"Speech processing worker {worker_name} stopped")
    
    async def _process_speech_request(self, request: SpeechRequest):
        """
        Process speech request
        
        Args:
            request: Speech processing request
        """
        start_time = datetime.now()
        
        try:
            # Update request status
            request.status = ProcessingStatus.PROCESSING
            await self._store_processing_status(request)
            
            # Process based on request type
            if request.request_type == "stt":
                result_data, confidence = await self._process_speech_to_text(request)
            elif request.request_type == "tts":
                result_data, confidence = await self._process_text_to_speech(request)
            else:
                raise ValueError(f"Unknown request type: {request.request_type}")
            
            # Calculate processing time
            processing_time = (datetime.now() - start_time).total_seconds()
            self.total_processing_time += processing_time
            
            # Create successful result
            result = SpeechResult(
                request_id=request.request_id,
                success=True,
                result=result_data,
                confidence=confidence,
                processing_time=processing_time,
                engine_used=request.engine.value
            )
            
            # Update statistics
            if request.request_type == "stt":
                self.stt_requests_processed += 1
            else:
                self.tts_requests_processed += 1
            
            # Update status
            request.status = ProcessingStatus.COMPLETED
            await self._store_processing_result(result)
            await self._store_processing_status(request)
            
            logger.info(f"Successfully processed speech request: {request.request_id}")
            
        except Exception as e:
            # Calculate processing time for failed request
            processing_time = (datetime.now() - start_time).total_seconds()
            
            # Create failure result
            result = SpeechResult(
                request_id=request.request_id,
                success=False,
                error=str(e),
                processing_time=processing_time,
                engine_used=request.engine.value
            )
            
            # Update status
            request.status = ProcessingStatus.FAILED
            await self._store_processing_result(result)
            await self._store_processing_status(request)
            
            self.requests_failed += 1
            logger.error(f"Speech processing failed for {request.request_id}: {e}")
    
    async def _process_speech_to_text(self, request: SpeechRequest) -> tuple:
        """Process speech-to-text request"""
        try:
            # Save audio data to temporary file
            temp_file = await self._save_audio_to_temp_file(
                request.input_data, 
                request.request_id
            )
            
            try:
                # Process based on engine
                if request.engine == SpeechEngine.GOOGLE:
                    text, confidence = await self._stt_google(temp_file, request.parameters)
                elif request.engine == SpeechEngine.WHISPER:
                    text, confidence = await self._stt_whisper(temp_file, request.parameters)
                elif request.engine == SpeechEngine.SPHINX:
                    text, confidence = await self._stt_sphinx(temp_file, request.parameters)
                else:
                    raise ValueError(f"Unsupported STT engine: {request.engine}")
                
                return text, confidence
                
            finally:
                # Clean up temporary file
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    
        except Exception as e:
            logger.error(f"STT processing error: {e}")
            raise
    
    async def _process_text_to_speech(self, request: SpeechRequest) -> tuple:
        """Process text-to-speech request"""
        try:
            # Process based on engine
            if request.engine == SpeechEngine.GTTS:
                audio_data = await self._tts_gtts(request.input_data, request.parameters)
            else:
                raise ValueError(f"Unsupported TTS engine: {request.engine}")
            
            return audio_data, None  # TTS doesn't have confidence score
            
        except Exception as e:
            logger.error(f"TTS processing error: {e}")
            raise
    
    async def _stt_google(self, audio_file: str, parameters: Dict[str, Any]) -> tuple:
        """Process STT using Google Speech Recognition"""
        try:
            if not SPEECH_RECOGNITION_AVAILABLE:
                raise ValueError("SpeechRecognition library not available")
            
            recognizer = self.recognizers.get(SpeechEngine.GOOGLE)
            if not recognizer:
                raise ValueError("Google recognizer not available")
            
            # Load audio file
            with sr.AudioFile(audio_file) as source:
                # Adjust for ambient noise if enabled
                if parameters.get('enable_noise_reduction', False):
                    recognizer.adjust_for_ambient_noise(source)
                
                # Record audio
                audio_data = recognizer.record(source)
            
            # Recognize speech
            language = parameters.get('language', 'en-US')
            text = recognizer.recognize_google(audio_data, language=language)
            
            # Google API doesn't return confidence in free version
            confidence = None
            
            return text, confidence
            
        except sr.UnknownValueError:
            return "", 0.0
        except sr.RequestError as e:
            raise ValueError(f"Google Speech Recognition error: {e}")
        except Exception as e:
            logger.error(f"Google STT error: {e}")
            raise
    
    async def _stt_whisper(self, audio_file: str, parameters: Dict[str, Any]) -> tuple:
        """Process STT using Whisper model"""
        try:
            whisper_pipeline = self.recognizers.get(SpeechEngine.WHISPER)
            if not whisper_pipeline:
                raise ValueError("Whisper model not available")
            
            # Process audio file
            result = whisper_pipeline(audio_file)
            text = result.get('text', '')
            
            # Whisper doesn't provide confidence scores in pipeline
            confidence = None
            
            return text, confidence
            
        except Exception as e:
            logger.error(f"Whisper STT error: {e}")
            raise
    
    async def _stt_sphinx(self, audio_file: str, parameters: Dict[str, Any]) -> tuple:
        """Process STT using CMU Sphinx"""
        try:
            if not SPEECH_RECOGNITION_AVAILABLE:
                raise ValueError("SpeechRecognition library not available")
            
            recognizer = self.recognizers.get(SpeechEngine.SPHINX)
            if not recognizer:
                raise ValueError("Sphinx recognizer not available")
            
            # Load audio file
            with sr.AudioFile(audio_file) as source:
                audio_data = recognizer.record(source)
            
            # Recognize speech using PocketSphinx
            text = recognizer.recognize_sphinx(audio_data)
            confidence = None  # Sphinx doesn't provide confidence in this interface
            
            return text, confidence
            
        except sr.UnknownValueError:
            return "", 0.0
        except sr.RequestError as e:
            raise ValueError(f"Sphinx Speech Recognition error: {e}")
        except Exception as e:
            logger.error(f"Sphinx STT error: {e}")
            raise
    
    async def _tts_gtts(self, text: str, parameters: Dict[str, Any]) -> bytes:
        """Process TTS using Google Text-to-Speech"""
        try:
            if not GTTS_AVAILABLE:
                raise ValueError("gTTS library not available")
            
            language = parameters.get('language', 'en-US')
            # Convert language code if needed
            if language.startswith('en-'):
                lang_code = 'en'
            else:
                lang_code = language.split('-')[0]
            
            # Create TTS object
            tts = gTTS(text=text, lang=lang_code, slow=False)
            
            # Save to temporary buffer
            mp3_buffer = io.BytesIO()
            tts.write_to_fp(mp3_buffer)
            mp3_buffer.seek(0)
            
            # Convert to WAV if pydub is available
            if PYDUB_AVAILABLE:
                audio = AudioSegment.from_mp3(mp3_buffer)
                wav_buffer = io.BytesIO()
                audio.export(wav_buffer, format="wav")
                wav_buffer.seek(0)
                return wav_buffer.read()
            else:
                # Return MP3 data
                return mp3_buffer.read()
                
        except Exception as e:
            logger.error(f"gTTS error: {e}")
            raise
    
    async def _save_audio_to_temp_file(self, audio_data: bytes, request_id: str) -> str:
        """Save audio data to temporary file"""
        try:
            temp_file = os.path.join(
                self.config['temp_directory'],
                f"{request_id}.wav"
            )
            
            # If it's raw audio data, assume it's WAV format
            with open(temp_file, 'wb') as f:
                f.write(audio_data)
            
            # Try to convert to proper WAV format if pydub is available
            if PYDUB_AVAILABLE:
                try:
                    # Load and convert to standard WAV format
                    audio = AudioSegment.from_file(temp_file)
                    audio = audio.set_frame_rate(self.config['sample_rate'])
                    audio = audio.set_channels(1)  # Mono
                    audio.export(temp_file, format="wav")
                except Exception as e:
                    logger.warning(f"Audio conversion warning: {e}")
            
            return temp_file
            
        except Exception as e:
            logger.error(f"Failed to save audio to temp file: {e}")
            raise
    
    async def _cleanup_temp_files(self):
        """Cleanup temporary files periodically"""
        while self.is_running:
            try:
                await asyncio.sleep(300)  # Clean up every 5 minutes
                
                temp_dir = self.config['temp_directory']
                if os.path.exists(temp_dir):
                    now = datetime.now()
                    
                    for filename in os.listdir(temp_dir):
                        filepath = os.path.join(temp_dir, filename)
                        if os.path.isfile(filepath):
                            # Remove files older than 1 hour
                            file_age = now - datetime.fromtimestamp(os.path.getmtime(filepath))
                            if file_age.total_seconds() > 3600:  # 1 hour
                                try:
                                    os.remove(filepath)
                                    logger.debug(f"Cleaned up temp file: {filename}")
                                except Exception as e:
                                    logger.warning(f"Failed to remove temp file {filename}: {e}")
                                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Temp file cleanup error: {e}")
                await asyncio.sleep(60)
    
    async def _store_processing_status(self, request: SpeechRequest):
        """Store processing status in database"""
        try:
            await self.db_manager.execute_query(
                """
                INSERT OR REPLACE INTO speech_processing_status 
                (request_id, request_type, engine, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    request.request_id,
                    request.request_type,
                    request.engine.value,
                    request.status.value,
                    request.created_at.isoformat()
                ]
            )
        except Exception as e:
            logger.error(f"Failed to store speech processing status: {e}")
    
    async def _store_processing_result(self, result: SpeechResult):
        """Store processing result in database"""
        try:
            # For TTS results (audio data), we might want to store as file reference
            result_data = result.result
            if isinstance(result_data, bytes):
                # Save audio data and store file reference
                filename = f"{result.request_id}_output.wav"
                filepath = os.path.join(self.config['temp_directory'], filename)
                with open(filepath, 'wb') as f:
                    f.write(result_data)
                result_data = filepath
            
            await self.db_manager.execute_query(
                """
                INSERT OR REPLACE INTO speech_processing_results 
                (request_id, success, result_data, confidence, error, processing_time, engine_used, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    result.request_id,
                    result.success,
                    result_data if isinstance(result_data, str) else str(result_data),
                    result.confidence,
                    result.error,
                    result.processing_time,
                    result.engine_used,
                    datetime.now().isoformat()
                ]
            )
        except Exception as e:
            logger.error(f"Failed to store speech processing result: {e}")
    
    async def get_processing_result(self, request_id: str) -> Optional[Dict[str, Any]]:
        """
        Get processing result for a request
        
        Args:
            request_id: Processing request ID
            
        Returns:
            Processing result or None
        """
        try:
            result = await self.db_manager.execute_query(
                "SELECT * FROM speech_processing_results WHERE request_id = ?",
                [request_id]
            )
            
            if result:
                row = result[0]
                result_data = row['result_data']
                
                # If result is a file path, read the audio data
                if result_data and os.path.exists(result_data) and result_data.endswith('.wav'):
                    with open(result_data, 'rb') as f:
                        result_data = f.read()
                
                return {
                    'request_id': row['request_id'],
                    'success': bool(row['success']),
                    'result': result_data,
                    'confidence': row['confidence'],
                    'error': row['error'],
                    'processing_time': row['processing_time'],
                    'engine_used': row['engine_used'],
                    'created_at': row['created_at']
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting speech processing result: {e}")
            return None
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get speech service statistics"""
        total_requests = self.stt_requests_processed + self.tts_requests_processed
        avg_processing_time = (
            self.total_processing_time / total_requests 
            if total_requests > 0 else 0
        )
        
        return {
            'is_running': self.is_running,
            'is_configured': self.is_configured,
            'stt_requests_processed': self.stt_requests_processed,
            'tts_requests_processed': self.tts_requests_processed,
            'total_requests_processed': total_requests,
            'requests_failed': self.requests_failed,
            'active_processing_tasks': len(self.processing_tasks),
            'queue_size': self.request_queue.qsize(),
            'average_processing_time': avg_processing_time,
            'total_processing_time': self.total_processing_time,
            'total_audio_duration': self.total_audio_duration,
            'config': {
                'default_stt_engine': self.config['default_stt_engine'].value,
                'default_tts_engine': self.config['default_tts_engine'].value,
                'default_language': self.config['default_language'],
                'max_concurrent_requests': self.config['max_concurrent_requests']
            },
            'engines': {
                'speech_recognition_available': SPEECH_RECOGNITION_AVAILABLE,
                'gtts_available': GTTS_AVAILABLE,
                'pydub_available': PYDUB_AVAILABLE,
                'transformers_speech_available': TRANSFORMERS_SPEECH_AVAILABLE,
                'loaded_recognizers': list(self.recognizers.keys()),
                'loaded_tts_engines': list(self.tts_engines.keys())
            }
        }


__all__ = ['SpeechService', 'SpeechEngine', 'AudioFormat', 'ProcessingStatus', 'SpeechRequest', 'SpeechResult']
