"""
Example: Using Hybrid GPU+CPU Offload for Large Models

This demonstrates how to use the hybrid_offload utility to load models
that don't fit entirely in GPU memory.
"""

import logging;
from util.hybrid_offload import (
    load_model_with_offload,
    load_transformers_model,
    HybridOffloadConfig,
    get_memory_stats
);

# Configure logging
logging.basicConfig( level=logging.INFO );


def example_basic_usage():
    """Basic usage with default settings"""
    print( "\n=== Example 1: Basic Usage ===" );
    
    from transformers import AutoModelForCausalLM;
    
    # Load model with default offload to ai/offload/
    model = AutoModelForCausalLM.from_pretrained(
        "gpt2",
        device_map="auto",
        offload_folder="ai/offload/"
    );
    
    print( "Model loaded with automatic device mapping" );
    print( "Offload directory: ai/offload/" );


def example_custom_offload_location():
    """Custom offload location (e.g., fast NVMe storage)"""
    print( "\n=== Example 2: Custom Offload Location ===" );
    
    # Configure offload to use fast storage
    config = HybridOffloadConfig(
        offload_dir="/mnt/nvme/ai_offload"  # Fast NVMe drive
    );
    
    from transformers import AutoModelForCausalLM;
    model = AutoModelForCausalLM.from_pretrained( "gpt2" );
    
    model = load_model_with_offload( model, config=config );
    
    print( "Model loaded with offload to fast NVMe storage" );


def example_memory_constraints():
    """Specify memory limits per device"""
    print( "\n=== Example 3: Memory Constraints ===" );
    
    # Limit GPU to 8GB, CPU to 16GB
    config = HybridOffloadConfig(
        offload_dir="ai/offload/",
        max_memory={
            0: "8GiB",      # GPU 0: 8GB max
            "cpu": "16GiB"  # CPU: 16GB max
        }
    );
    
    from transformers import AutoModelForCausalLM;
    model = AutoModelForCausalLM.from_pretrained( "gpt2" );
    
    model = load_model_with_offload( model, config=config );
    
    print( "Model loaded with memory constraints" );


def example_large_model():
    """Load a larger model with automatic distribution"""
    print( "\n=== Example 4: Large Model (7B parameters) ===" );
    
    # For larger models, use the convenience function
    model = load_transformers_model(
        "meta-llama/Llama-2-7b-hf",  # 7B parameter model
        offload_dir="ai/offload/",
        max_memory={0: "10GiB", "cpu": "20GiB"}
    );
    
    print( "Large model loaded with hybrid offload" );


def example_check_memory():
    """Check current memory usage"""
    print( "\n=== Example 5: Memory Statistics ===" );
    
    stats = get_memory_stats();
    
    print( "Current Memory Usage:" );
    for device, info in stats.items():
        print( f"\n{device}:" );
        if isinstance( info, dict ):
            for key, value in info.items():
                print( f"  {key}: {value:.2f} GiB" );
        else:
            print( f"  {info}" );


def example_production_usage():
    """Complete example for production use"""
    print( "\n=== Example 6: Production Usage ===" );
    
    import os;
    
    # Get offload path from environment or use default
    offload_path = os.getenv( "AI_OFFLOAD_PATH", "ai/offload/" );
    
    # Configure for production
    config = HybridOffloadConfig(
        offload_dir=offload_path,
        max_memory={
            0: "12GiB",      # Reserve some GPU memory for other processes
            "cpu": "24GiB"
        },
        offload_buffers=True  # Also offload buffers to save memory
    );
    
    # Load model
    from transformers import AutoModelForCausalLM, AutoTokenizer;
    
    model_name = "gpt2";  # Replace with your model
    
    print( f"Loading model: {model_name}" );
    print( f"Offload path: {offload_path}" );
    
    tokenizer = AutoTokenizer.from_pretrained( model_name );
    model = AutoModelForCausalLM.from_pretrained( model_name );
    model = load_model_with_offload( model, config=config );
    
    # Test inference
    text = "Hello, I am a language model";
    inputs = tokenizer( text, return_tensors="pt" );
    
    # Move inputs to same device as model's first layer
    if hasattr( model, "hf_device_map" ):
        first_device = list( model.hf_device_map.values() )[0];
        inputs = {k: v.to( first_device ) for k, v in inputs.items()};
    
    outputs = model.generate( **inputs, max_length=50 );
    result = tokenizer.decode( outputs[0], skip_special_tokens=True );
    
    print( f"\nGenerated text: {result}" );
    
    # Show memory stats
    print( "\nMemory after inference:" );
    stats = get_memory_stats();
    for device, info in stats.items():
        if isinstance( info, dict ) and "allocated" in info:
            print( f"{device}: {info['allocated']:.2f} GiB allocated" );


if __name__ == "__main__":
    print( "Hybrid GPU+CPU Offload Examples" );
    print( "=" * 50 );
    
    # Run examples (comment out ones you don't want to run)
    example_basic_usage();
    # example_custom_offload_location();
    # example_memory_constraints();
    # example_large_model();  # Requires model download
    example_check_memory();
    # example_production_usage();
    
    print( "\n" + "=" * 50 );
    print( "Examples complete!" );
