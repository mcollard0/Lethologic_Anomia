"""
AI Processor Service

Provides machine learning and natural language processing capabilities
using HuggingFace Transformers and local AI models for medical data analysis.
"""

import asyncio
import json
import os
import torch
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import numpy as np

# ML/AI Libraries
try:
    from transformers import (
        AutoTokenizer, AutoModel, AutoModelForSequenceClassification,
        pipeline, BertTokenizer, BertModel
    )
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

from ...core.logging import get_logger
from ...core.database import DatabaseManager
from ...core.config import Settings

logger = get_logger(__name__)


class ModelType(Enum):
    """AI Model Types"""
    TEXT_CLASSIFICATION = "text_classification"
    NAMED_ENTITY_RECOGNITION = "ner"
    SENTIMENT_ANALYSIS = "sentiment_analysis"
    TEXT_SUMMARIZATION = "text_summarization"
    QUESTION_ANSWERING = "question_answering"
    TEXT_EMBEDDING = "text_embedding"
    MEDICAL_NER = "medical_ner"
    CLINICAL_CLASSIFICATION = "clinical_classification"


class ProcessingStatus(Enum):
    """AI Processing Status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AIModel:
    """AI Model Configuration"""
    model_id: str
    model_type: ModelType
    model_path: str
    tokenizer_path: Optional[str] = None
    device: str = "cpu"
    loaded: bool = False
    last_used: Optional[datetime] = None


@dataclass
class ProcessingRequest:
    """AI Processing Request"""
    request_id: str
    model_type: ModelType
    input_data: Union[str, Dict[str, Any]]
    parameters: Dict[str, Any]
    created_at: datetime
    status: ProcessingStatus = ProcessingStatus.PENDING


@dataclass
class ProcessingResult:
    """AI Processing Result"""
    request_id: str
    success: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processing_time: Optional[float] = None
    model_used: Optional[str] = None


class AIProcessor:
    """
    AI Processor Service
    
    Provides comprehensive AI and ML capabilities:
    - HuggingFace model integration
    - Text classification and analysis
    - Named entity recognition
    - Medical text processing
    - Clinical data classification
    - Batch processing and queuing
    - Model management and caching
    """
    
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        """
        Initialize AI processor
        
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
            'models_directory': './models/',
            'cache_directory': './cache/',
            'max_concurrent_requests': 10,
            'model_cache_size': 5,
            'default_device': 'cuda' if torch.cuda.is_available() else 'cpu',
            'enable_gpu': torch.cuda.is_available(),
            'request_timeout_seconds': 300,
            'batch_size': 32
        }
        
        # AI models
        self.loaded_models: Dict[str, Any] = {}
        self.model_configs: Dict[str, AIModel] = {}
        self.setup_default_models()
        
        # Processing queue
        self.request_queue: asyncio.Queue = asyncio.Queue()
        self.processing_tasks: Dict[str, asyncio.Task] = {}
        self.worker_tasks: List[asyncio.Task] = []
        
        # Statistics
        self.requests_processed = 0
        self.requests_failed = 0
        self.models_loaded = 0
        self.total_processing_time = 0.0
        self.cache_hits = 0
        self.cache_misses = 0
        
        logger.info(f"AI Processor Service initialized (GPU: {self.config['enable_gpu']})")
    
    def configure(self, config: Dict[str, Any]) -> bool:
        """
        Configure the AI processor
        
        Args:
            config: Configuration dictionary
            
        Returns:
            True if configuration successful
        """
        try:
            self.config.update(config)
            
            # Create directories
            os.makedirs(self.config['models_directory'], exist_ok=True)
            os.makedirs(self.config['cache_directory'], exist_ok=True)
            
            self.is_configured = True
            logger.info(f"AI processor configured (Device: {self.config['default_device']})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to configure AI processor: {e}")
            return False
    
    def setup_default_models(self):
        """Setup default AI models"""
        self.model_configs = {
            'clinical_bert': AIModel(
                model_id='clinical_bert',
                model_type=ModelType.TEXT_EMBEDDING,
                model_path='emilyalsentzer/Bio_ClinicalBERT',
                device=self.config['default_device']
            ),
            'medical_ner': AIModel(
                model_id='medical_ner',
                model_type=ModelType.MEDICAL_NER,
                model_path='d4data/biomedical-ner-all',
                device=self.config['default_device']
            ),
            'sentiment_analysis': AIModel(
                model_id='sentiment_analysis',
                model_type=ModelType.SENTIMENT_ANALYSIS,
                model_path='cardiffnlp/twitter-roberta-base-sentiment-latest',
                device=self.config['default_device']
            ),
            'text_summarization': AIModel(
                model_id='text_summarization',
                model_type=ModelType.TEXT_SUMMARIZATION,
                model_path='facebook/bart-large-cnn',
                device=self.config['default_device']
            ),
            'question_answering': AIModel(
                model_id='question_answering',
                model_type=ModelType.QUESTION_ANSWERING,
                model_path='distilbert-base-cased-distilled-squad',
                device=self.config['default_device']
            )
        }
    
    async def start(self) -> bool:
        """
        Start the AI processor service
        
        Returns:
            True if started successfully
        """
        if not self.is_configured:
            # Use default configuration
            if not self.configure({}):
                logger.error("Failed to configure AI processor with defaults")
                return False
        
        if self.is_running:
            logger.warning("AI processor already running")
            return True
        
        try:
            # Check dependencies
            if not TRANSFORMERS_AVAILABLE:
                logger.warning("HuggingFace Transformers not available")
            
            # Load default models
            await self._load_essential_models()
            
            # Start worker tasks
            worker_count = min(self.config['max_concurrent_requests'], 5)
            for i in range(worker_count):
                task = asyncio.create_task(
                    self._processing_worker(f"ai-worker-{i}")
                )
                self.worker_tasks.append(task)
            
            # Start model management task
            management_task = asyncio.create_task(self._model_management_task())
            self.worker_tasks.append(management_task)
            
            self.is_running = True
            logger.info(f"AI processor started with {worker_count} workers")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start AI processor: {e}")
            return False
    
    async def stop(self) -> bool:
        """
        Stop the AI processor service
        
        Returns:
            True if stopped successfully
        """
        if not self.is_running:
            return True
        
        try:
            logger.info("Stopping AI processor...")
            
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
            
            # Clear loaded models to free memory
            self.loaded_models.clear()
            
            # Clear queues and tasks
            self.worker_tasks.clear()
            self.processing_tasks.clear()
            
            logger.info("AI processor stopped")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping AI processor: {e}")
            return False
    
    async def process_text(self, text: str, model_type: ModelType, 
                          parameters: Optional[Dict[str, Any]] = None) -> str:
        """
        Process text with AI model
        
        Args:
            text: Text to process
            model_type: Type of model to use
            parameters: Optional processing parameters
            
        Returns:
            Processing request ID
        """
        try:
            # Generate request ID
            request_id = f"ai_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.processing_tasks)}"
            
            # Create processing request
            request = ProcessingRequest(
                request_id=request_id,
                model_type=model_type,
                input_data=text,
                parameters=parameters or {},
                created_at=datetime.now()
            )
            
            # Add to queue
            await self.request_queue.put(request)
            
            logger.info(f"Queued text processing request: {request_id}")
            return request_id
            
        except Exception as e:
            logger.error(f"Error queuing text processing: {e}")
            raise
    
    async def process_clinical_text(self, text: str, extract_entities: bool = True,
                                  analyze_sentiment: bool = True) -> str:
        """
        Process clinical text with medical NLP
        
        Args:
            text: Clinical text to analyze
            extract_entities: Whether to extract medical entities
            analyze_sentiment: Whether to analyze sentiment
            
        Returns:
            Processing request ID
        """
        try:
            parameters = {
                'extract_entities': extract_entities,
                'analyze_sentiment': analyze_sentiment,
                'clinical_mode': True
            }
            
            return await self.process_text(text, ModelType.MEDICAL_NER, parameters)
            
        except Exception as e:
            logger.error(f"Error processing clinical text: {e}")
            raise
    
    async def get_text_embeddings(self, texts: List[str]) -> str:
        """
        Get text embeddings for similarity analysis
        
        Args:
            texts: List of texts to embed
            
        Returns:
            Processing request ID
        """
        try:
            parameters = {
                'batch_mode': True,
                'normalize': True
            }
            
            return await self.process_text(texts, ModelType.TEXT_EMBEDDING, parameters)
            
        except Exception as e:
            logger.error(f"Error getting text embeddings: {e}")
            raise
    
    async def _processing_worker(self, worker_name: str):
        """
        AI processing worker
        
        Args:
            worker_name: Name of the worker
        """
        logger.info(f"AI processing worker {worker_name} started")
        
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
                    self._process_ai_request(request)
                )
                self.processing_tasks[request.request_id] = task
                
                # Wait for completion
                try:
                    await task
                except Exception as e:
                    logger.error(f"AI processing failed for {request.request_id}: {e}")
                    self.requests_failed += 1
                
                # Mark queue task done
                self.request_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"AI worker {worker_name} error: {e}")
                await asyncio.sleep(1)
        
        logger.info(f"AI processing worker {worker_name} stopped")
    
    async def _process_ai_request(self, request: ProcessingRequest):
        """
        Process AI request
        
        Args:
            request: Processing request to handle
        """
        start_time = datetime.now()
        
        try:
            # Update request status
            request.status = ProcessingStatus.PROCESSING
            await self._store_processing_status(request)
            
            # Get appropriate model
            model = await self._get_model_for_type(request.model_type)
            if not model:
                raise ValueError(f"No model available for type: {request.model_type}")
            
            # Process based on model type
            if request.model_type == ModelType.TEXT_CLASSIFICATION:
                result = await self._classify_text(model, request.input_data, request.parameters)
            elif request.model_type == ModelType.MEDICAL_NER:
                result = await self._extract_medical_entities(model, request.input_data, request.parameters)
            elif request.model_type == ModelType.SENTIMENT_ANALYSIS:
                result = await self._analyze_sentiment(model, request.input_data, request.parameters)
            elif request.model_type == ModelType.TEXT_SUMMARIZATION:
                result = await self._summarize_text(model, request.input_data, request.parameters)
            elif request.model_type == ModelType.QUESTION_ANSWERING:
                result = await self._answer_question(model, request.input_data, request.parameters)
            elif request.model_type == ModelType.TEXT_EMBEDDING:
                result = await self._get_embeddings(model, request.input_data, request.parameters)
            else:
                raise ValueError(f"Unsupported model type: {request.model_type}")
            
            # Calculate processing time
            processing_time = (datetime.now() - start_time).total_seconds()
            self.total_processing_time += processing_time
            
            # Create successful result
            final_result = ProcessingResult(
                request_id=request.request_id,
                success=True,
                result=result,
                processing_time=processing_time,
                model_used=model.get('model_id', 'unknown')
            )
            
            # Update status
            request.status = ProcessingStatus.COMPLETED
            await self._store_processing_result(final_result)
            await self._store_processing_status(request)
            
            self.requests_processed += 1
            logger.info(f"Successfully processed AI request: {request.request_id}")
            
        except Exception as e:
            # Calculate processing time for failed request
            processing_time = (datetime.now() - start_time).total_seconds()
            
            # Create failure result
            final_result = ProcessingResult(
                request_id=request.request_id,
                success=False,
                error=str(e),
                processing_time=processing_time
            )
            
            # Update status
            request.status = ProcessingStatus.FAILED
            await self._store_processing_result(final_result)
            await self._store_processing_status(request)
            
            self.requests_failed += 1
            logger.error(f"AI processing failed for {request.request_id}: {e}")
    
    async def _get_model_for_type(self, model_type: ModelType) -> Optional[Dict[str, Any]]:
        """Get model for processing type"""
        try:
            # Find model config for type
            model_config = None
            for config in self.model_configs.values():
                if config.model_type == model_type:
                    model_config = config
                    break
            
            if not model_config:
                logger.error(f"No model configuration found for type: {model_type}")
                return None
            
            # Check if model is already loaded
            if model_config.model_id in self.loaded_models:
                self.cache_hits += 1
                model_config.last_used = datetime.now()
                return self.loaded_models[model_config.model_id]
            
            # Load model
            self.cache_misses += 1
            model = await self._load_model(model_config)
            return model
            
        except Exception as e:
            logger.error(f"Error getting model for type {model_type}: {e}")
            return None
    
    async def _load_model(self, config: AIModel) -> Optional[Dict[str, Any]]:
        """Load AI model"""
        try:
            if not TRANSFORMERS_AVAILABLE:
                logger.error("HuggingFace Transformers not available")
                return None
            
            logger.info(f"Loading AI model: {config.model_id}")
            
            model_data = {
                'model_id': config.model_id,
                'model_type': config.model_type,
                'device': config.device
            }
            
            # Load based on model type
            if config.model_type == ModelType.TEXT_EMBEDDING:
                if SENTENCE_TRANSFORMERS_AVAILABLE:
                    model = SentenceTransformer(config.model_path)
                    model_data['model'] = model
                else:
                    # Fallback to regular BERT
                    tokenizer = AutoTokenizer.from_pretrained(config.model_path)
                    model = AutoModel.from_pretrained(config.model_path)
                    model_data['tokenizer'] = tokenizer
                    model_data['model'] = model
                    
            elif config.model_type in [ModelType.TEXT_CLASSIFICATION, ModelType.SENTIMENT_ANALYSIS]:
                model_data['pipeline'] = pipeline(
                    "text-classification",
                    model=config.model_path,
                    device=0 if config.device == 'cuda' and torch.cuda.is_available() else -1
                )
                
            elif config.model_type == ModelType.MEDICAL_NER:
                model_data['pipeline'] = pipeline(
                    "ner",
                    model=config.model_path,
                    aggregation_strategy="simple",
                    device=0 if config.device == 'cuda' and torch.cuda.is_available() else -1
                )
                
            elif config.model_type == ModelType.TEXT_SUMMARIZATION:
                model_data['pipeline'] = pipeline(
                    "summarization",
                    model=config.model_path,
                    device=0 if config.device == 'cuda' and torch.cuda.is_available() else -1
                )
                
            elif config.model_type == ModelType.QUESTION_ANSWERING:
                model_data['pipeline'] = pipeline(
                    "question-answering",
                    model=config.model_path,
                    device=0 if config.device == 'cuda' and torch.cuda.is_available() else -1
                )
            
            # Store in cache
            self.loaded_models[config.model_id] = model_data
            config.loaded = True
            config.last_used = datetime.now()
            self.models_loaded += 1
            
            logger.info(f"Successfully loaded AI model: {config.model_id}")
            return model_data
            
        except Exception as e:
            logger.error(f"Failed to load AI model {config.model_id}: {e}")
            return None
    
    async def _classify_text(self, model: Dict[str, Any], text: str, 
                           parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Classify text using model"""
        try:
            pipeline_model = model.get('pipeline')
            if not pipeline_model:
                raise ValueError("No classification pipeline available")
            
            results = pipeline_model(text)
            
            return {
                'classification': results,
                'input_text': text[:200] + '...' if len(text) > 200 else text
            }
            
        except Exception as e:
            logger.error(f"Text classification error: {e}")
            raise
    
    async def _extract_medical_entities(self, model: Dict[str, Any], text: str,
                                      parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Extract medical entities from text"""
        try:
            pipeline_model = model.get('pipeline')
            if not pipeline_model:
                raise ValueError("No NER pipeline available")
            
            entities = pipeline_model(text)
            
            # Group entities by type
            entity_groups = {}
            for entity in entities:
                entity_type = entity['entity_group']
                if entity_type not in entity_groups:
                    entity_groups[entity_type] = []
                entity_groups[entity_type].append({
                    'text': entity['word'],
                    'confidence': entity['score'],
                    'start': entity.get('start'),
                    'end': entity.get('end')
                })
            
            return {
                'entities': entities,
                'entity_groups': entity_groups,
                'total_entities': len(entities),
                'input_text': text[:200] + '...' if len(text) > 200 else text
            }
            
        except Exception as e:
            logger.error(f"Medical NER error: {e}")
            raise
    
    async def _analyze_sentiment(self, model: Dict[str, Any], text: str,
                               parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze text sentiment"""
        try:
            pipeline_model = model.get('pipeline')
            if not pipeline_model:
                raise ValueError("No sentiment pipeline available")
            
            results = pipeline_model(text)
            
            return {
                'sentiment': results,
                'input_text': text[:200] + '...' if len(text) > 200 else text
            }
            
        except Exception as e:
            logger.error(f"Sentiment analysis error: {e}")
            raise
    
    async def _summarize_text(self, model: Dict[str, Any], text: str,
                            parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Summarize text"""
        try:
            pipeline_model = model.get('pipeline')
            if not pipeline_model:
                raise ValueError("No summarization pipeline available")
            
            # Parameters for summarization
            max_length = parameters.get('max_length', 150)
            min_length = parameters.get('min_length', 30)
            
            results = pipeline_model(
                text,
                max_length=max_length,
                min_length=min_length,
                do_sample=False
            )
            
            return {
                'summary': results[0]['summary_text'] if results else "",
                'input_length': len(text),
                'summary_length': len(results[0]['summary_text']) if results else 0
            }
            
        except Exception as e:
            logger.error(f"Text summarization error: {e}")
            raise
    
    async def _answer_question(self, model: Dict[str, Any], input_data: Dict[str, Any],
                             parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Answer question using model"""
        try:
            pipeline_model = model.get('pipeline')
            if not pipeline_model:
                raise ValueError("No QA pipeline available")
            
            question = input_data.get('question')
            context = input_data.get('context')
            
            if not question or not context:
                raise ValueError("Question and context are required")
            
            result = pipeline_model(question=question, context=context)
            
            return {
                'answer': result['answer'],
                'confidence': result['score'],
                'start': result['start'],
                'end': result['end'],
                'question': question,
                'context_length': len(context)
            }
            
        except Exception as e:
            logger.error(f"Question answering error: {e}")
            raise
    
    async def _get_embeddings(self, model: Dict[str, Any], input_data: Union[str, List[str]],
                            parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Get text embeddings"""
        try:
            if 'model' in model and hasattr(model['model'], 'encode'):
                # Sentence transformers
                embeddings = model['model'].encode(input_data)
            else:
                # Regular transformers
                tokenizer = model.get('tokenizer')
                bert_model = model.get('model')
                
                if not tokenizer or not bert_model:
                    raise ValueError("No embedding model available")
                
                if isinstance(input_data, str):
                    input_data = [input_data]
                
                # Tokenize and get embeddings
                encoded = tokenizer(
                    input_data,
                    padding=True,
                    truncation=True,
                    return_tensors='pt'
                )
                
                with torch.no_grad():
                    outputs = bert_model(**encoded)
                    embeddings = outputs.last_hidden_state.mean(dim=1).numpy()
            
            # Convert to list for JSON serialization
            if isinstance(embeddings, np.ndarray):
                embeddings = embeddings.tolist()
            
            return {
                'embeddings': embeddings,
                'embedding_dimension': len(embeddings[0]) if embeddings and len(embeddings) > 0 else 0,
                'input_count': len(input_data) if isinstance(input_data, list) else 1
            }
            
        except Exception as e:
            logger.error(f"Text embedding error: {e}")
            raise
    
    async def _load_essential_models(self):
        """Load essential models on startup"""
        try:
            # Load a basic model for testing
            if TRANSFORMERS_AVAILABLE:
                essential_models = ['sentiment_analysis']
                
                for model_id in essential_models:
                    if model_id in self.model_configs:
                        await self._load_model(self.model_configs[model_id])
                        
        except Exception as e:
            logger.warning(f"Failed to load essential models: {e}")
    
    async def _model_management_task(self):
        """Manage model cache and memory"""
        while self.is_running:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                
                # Clean up unused models if cache is full
                if len(self.loaded_models) > self.config['model_cache_size']:
                    await self._cleanup_unused_models()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Model management error: {e}")
                await asyncio.sleep(60)
    
    async def _cleanup_unused_models(self):
        """Cleanup unused models from cache"""
        try:
            # Sort models by last used time
            model_usage = []
            for model_id, config in self.model_configs.items():
                if config.loaded and config.last_used:
                    model_usage.append((model_id, config.last_used))
            
            # Sort by last used (oldest first)
            model_usage.sort(key=lambda x: x[1])
            
            # Remove oldest models if over cache limit
            models_to_remove = len(model_usage) - self.config['model_cache_size']
            if models_to_remove > 0:
                for i in range(models_to_remove):
                    model_id = model_usage[i][0]
                    if model_id in self.loaded_models:
                        del self.loaded_models[model_id]
                        self.model_configs[model_id].loaded = False
                        logger.info(f"Unloaded unused AI model: {model_id}")
                        
        except Exception as e:
            logger.error(f"Model cleanup error: {e}")
    
    async def _store_processing_status(self, request: ProcessingRequest):
        """Store processing status in database"""
        try:
            await self.db_manager.execute_query(
                """
                INSERT OR REPLACE INTO ai_processing_status 
                (request_id, model_type, status, created_at, input_data)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    request.request_id,
                    request.model_type.value,
                    request.status.value,
                    request.created_at.isoformat(),
                    json.dumps(request.input_data) if isinstance(request.input_data, (dict, list)) else str(request.input_data)
                ]
            )
        except Exception as e:
            logger.error(f"Failed to store processing status: {e}")
    
    async def _store_processing_result(self, result: ProcessingResult):
        """Store processing result in database"""
        try:
            await self.db_manager.execute_query(
                """
                INSERT OR REPLACE INTO ai_processing_results 
                (request_id, success, result_data, error, processing_time, model_used, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    result.request_id,
                    result.success,
                    json.dumps(result.result) if result.result else None,
                    result.error,
                    result.processing_time,
                    result.model_used,
                    datetime.now().isoformat()
                ]
            )
        except Exception as e:
            logger.error(f"Failed to store processing result: {e}")
    
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
                "SELECT * FROM ai_processing_results WHERE request_id = ?",
                [request_id]
            )
            
            if result:
                row = result[0]
                return {
                    'request_id': row['request_id'],
                    'success': bool(row['success']),
                    'result': json.loads(row['result_data']) if row['result_data'] else None,
                    'error': row['error'],
                    'processing_time': row['processing_time'],
                    'model_used': row['model_used'],
                    'created_at': row['created_at']
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting processing result: {e}")
            return None
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get AI processor statistics"""
        avg_processing_time = (
            self.total_processing_time / self.requests_processed 
            if self.requests_processed > 0 else 0
        )
        
        return {
            'is_running': self.is_running,
            'is_configured': self.is_configured,
            'requests_processed': self.requests_processed,
            'requests_failed': self.requests_failed,
            'models_loaded': self.models_loaded,
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'active_processing_tasks': len(self.processing_tasks),
            'queue_size': self.request_queue.qsize(),
            'loaded_models_count': len(self.loaded_models),
            'average_processing_time': avg_processing_time,
            'total_processing_time': self.total_processing_time,
            'config': {
                'enable_gpu': self.config['enable_gpu'],
                'default_device': self.config['default_device'],
                'model_cache_size': self.config['model_cache_size'],
                'max_concurrent_requests': self.config['max_concurrent_requests']
            },
            'transformers_available': TRANSFORMERS_AVAILABLE,
            'sentence_transformers_available': SENTENCE_TRANSFORMERS_AVAILABLE,
            'cuda_available': torch.cuda.is_available()
        }


__all__ = ['AIProcessor', 'ModelType', 'ProcessingStatus', 'AIModel', 'ProcessingRequest', 'ProcessingResult']
