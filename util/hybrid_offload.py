"""
Hybrid GPU+CPU Model Offload Utility

Provides transparent model loading with automatic device mapping across GPU and CPU,
with configurable disk offload for models that exceed available memory.

Uses HuggingFace Accelerate library for intelligent layer distribution.
"""

import os;
import logging;
from pathlib import Path;
from typing import Optional, Union, Dict, Any;

try:
    from accelerate import init_empty_weights, load_checkpoint_and_dispatch, infer_auto_device_map;
    from accelerate.utils import get_balanced_memory;
    import torch;
    ACCELERATE_AVAILABLE = True;
except ImportError:
    ACCELERATE_AVAILABLE = False;


logger = logging.getLogger( __name__ );


class HybridOffloadConfig:
    """Configuration for hybrid GPU+CPU model offload"""
    
    def __init__(
        self,
        offload_dir: Optional[str] = None,
        max_memory: Optional[Dict[Union[int, str], Union[int, str]]] = None,
        offload_buffers: bool = False,
        device_map: Union[str, Dict] = "auto",
    ):
        """
        Initialize offload configuration.
        
        Args:
            offload_dir: Directory for disk offload. Defaults to "ai/offload/".
                        Can be configured to use fast NVMe storage.
            max_memory: Maximum memory per device. Example: {0: "10GiB", "cpu": "30GiB"}
            offload_buffers: Whether to offload buffers to disk
            device_map: Device mapping strategy - "auto", "balanced", or custom dict
        """
        # Set default offload directory
        if offload_dir is None:
            offload_dir = "ai/offload/";
        
        self.offload_dir = Path( offload_dir );
        self.max_memory = max_memory;
        self.offload_buffers = offload_buffers;
        self.device_map = device_map;
        
        # Create offload directory if it doesn't exist
        self._ensure_offload_dir();
    
    def _ensure_offload_dir( self ):
        """Create offload directory structure"""
        try:
            self.offload_dir.mkdir( parents=True, exist_ok=True );
            logger.info( f"Offload directory ready: {self.offload_dir.absolute()}" );
        except Exception as e:
            logger.error( f"Failed to create offload directory: {e}" );
            raise;
    
    def get_device_map_kwargs( self ) -> Dict[str, Any]:
        """Get kwargs for load_checkpoint_and_dispatch"""
        kwargs = {
            "device_map": self.device_map,
            "offload_folder": str( self.offload_dir ),
        };
        
        if self.max_memory is not None:
            kwargs["max_memory"] = self.max_memory;
        
        if self.offload_buffers:
            kwargs["offload_buffers"] = True;
        
        return kwargs;


def load_model_with_offload(
    model,
    checkpoint_path: Optional[str] = None,
    config: Optional[HybridOffloadConfig] = None,
    **kwargs
):
    """
    Load a model with hybrid GPU+CPU offload support.
    
    Args:
        model: Model instance or model class
        checkpoint_path: Path to model checkpoint/weights (optional)
        config: HybridOffloadConfig instance (uses defaults if None)
        **kwargs: Additional arguments passed to load_checkpoint_and_dispatch
    
    Returns:
        Model with device mapping applied
    
    Example:
        ```python
        from transformers import AutoModelForCausalLM;
        
        # Basic usage with defaults (offload to ai/offload/)
        model = load_model_with_offload(
            AutoModelForCausalLM.from_pretrained( "gpt2" )
        );
        
        # Custom offload location (e.g., fast NVMe)
        config = HybridOffloadConfig( offload_dir="/mnt/nvme/offload" );
        model = load_model_with_offload(
            AutoModelForCausalLM.from_pretrained( "meta-llama/Llama-2-7b-hf" ),
            config=config
        );
        
        # With memory constraints
        config = HybridOffloadConfig(
            offload_dir="ai/offload/",
            max_memory={0: "8GiB", "cpu": "16GiB"}
        );
        model = load_model_with_offload( model, config=config );
        ```
    """
    if not ACCELERATE_AVAILABLE:
        logger.warning( "Accelerate library not installed. Install with: pip install accelerate" );
        return model;
    
    if config is None:
        config = HybridOffloadConfig();
    
    # Get device map kwargs
    dispatch_kwargs = config.get_device_map_kwargs();
    dispatch_kwargs.update( kwargs );
    
    try:
        # If checkpoint path provided, load from checkpoint
        if checkpoint_path:
            logger.info( f"Loading model from checkpoint: {checkpoint_path}" );
            model = load_checkpoint_and_dispatch(
                model,
                checkpoint_path,
                **dispatch_kwargs
            );
        else:
            # Just apply device mapping to existing model
            logger.info( "Applying device mapping to model" );
            model = load_checkpoint_and_dispatch(
                model,
                checkpoint=None,
                **dispatch_kwargs
            );
        
        _log_device_map( model );
        return model;
        
    except Exception as e:
        logger.error( f"Failed to load model with offload: {e}" );
        logger.info( "Falling back to standard model loading" );
        return model;


def get_memory_stats() -> Dict[str, Any]:
    """
    Get current memory statistics for GPU and CPU.
    
    Returns:
        Dict with memory info for each device
    """
    stats = {};
    
    if torch.cuda.is_available():
        for i in range( torch.cuda.device_count() ):
            stats[f"cuda:{i}"] = {
                "allocated": torch.cuda.memory_allocated( i ) / 1024**3,
                "reserved": torch.cuda.memory_reserved( i ) / 1024**3,
                "total": torch.cuda.get_device_properties( i ).total_memory / 1024**3,
            };
    
    # CPU memory (requires psutil)
    try:
        import psutil;
        mem = psutil.virtual_memory();
        stats["cpu"] = {
            "used": mem.used / 1024**3,
            "available": mem.available / 1024**3,
            "total": mem.total / 1024**3,
        };
    except ImportError:
        stats["cpu"] = "psutil not installed";
    
    return stats;


def _log_device_map( model ):
    """Log the device mapping of model layers"""
    if hasattr( model, "hf_device_map" ):
        logger.info( "Model device map:" );
        for name, device in model.hf_device_map.items():
            logger.info( f"  {name}: {device}" );
    else:
        logger.info( "Model loaded (device map not available)" );


# Convenience function for common use case
def load_transformers_model(
    model_name: str,
    offload_dir: str = "ai/offload/",
    max_memory: Optional[Dict] = None,
    **model_kwargs
):
    """
    Load a HuggingFace Transformers model with hybrid offload.
    
    Args:
        model_name: HuggingFace model identifier
        offload_dir: Directory for disk offload
        max_memory: Memory constraints per device
        **model_kwargs: Additional arguments for AutoModel.from_pretrained
    
    Returns:
        Loaded model with device mapping
    
    Example:
        ```python
        # Load large model with automatic GPU+CPU distribution
        model = load_transformers_model(
            "meta-llama/Llama-2-13b-hf",
            offload_dir="/mnt/nvme/offload",
            max_memory={0: "10GiB", "cpu": "20GiB"}
        );
        ```
    """
    if not ACCELERATE_AVAILABLE:
        raise ImportError( "Accelerate library required. Install with: pip install accelerate" );
    
    from transformers import AutoModelForCausalLM;
    
    config = HybridOffloadConfig(
        offload_dir=offload_dir,
        max_memory=max_memory
    );
    
    logger.info( f"Loading model: {model_name}" );
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        device_map=config.device_map,
        offload_folder=str( config.offload_dir ),
        max_memory=config.max_memory,
        **model_kwargs
    );
    
    _log_device_map( model );
    return model;
