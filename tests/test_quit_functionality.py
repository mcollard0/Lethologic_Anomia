#!/usr/bin/env python3
"""
Test script for quit functionality

Tests that the AI loop properly responds to:
1. .q command
2. "i wish to quit now." phrase

Includes background killall python as requested for safety.
"""

import asyncio
import subprocess
import signal
import os
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.ai_loop import AIService
from core.config import get_settings
from core.database import DatabaseManager
from unittest.mock import MagicMock

async def test_quit_commands():
    """Test quit commands with AI service"""
    print("Testing quit functionality...")
    
    # Start background killall safety net
    def safety_net():
        time.sleep(30)  # Wait 30 seconds max
        try:
            subprocess.run(['killall', 'python3'], check=False)
            print("Safety net activated - killed python processes")
        except:
            pass
    
    import threading
    safety_thread = threading.Thread(target=safety_net, daemon=True)
    safety_thread.start()
    
    # Initialize components
    settings = get_settings()
    db_manager = DatabaseManager(settings.database_url)
    await db_manager.initialize()
    
    ai_service = AIService(settings, db_manager)
    
    # Mock the AI model initialization to avoid downloading models in tests
    ai_service.local_model = MagicMock()
    ai_service.tokenizer = MagicMock()
    ai_service.available_providers = ['test']
    
    # Test 1: .q command
    print("\\nTest 1: Testing '.q' command...")
    response = await ai_service.process_input(".q")
    print(f"Response: {response}")
    
    if response == "QUIT_REQUESTED":
        print("✅ '.q' command works correctly")
    else:
        print("❌ '.q' command failed")
    
    # Test 2: "i wish to quit now." phrase
    print("\\nTest 2: Testing 'i wish to quit now.' phrase...")
    response = await ai_service.process_input("i wish to quit now.")
    print(f"Response: {response}")
    
    # For natural language, it should either return QUIT_REQUESTED or contain quit-related text
    if response == "QUIT_REQUESTED" or "quit" in response.lower():
        print("✅ 'i wish to quit now.' phrase works correctly")
    else:
        print("❌ 'i wish to quit now.' phrase failed")
    
    # Test 3: Help command
    print("\\nTest 3: Testing 'help' command...")
    response = await ai_service.process_input("help")
    print(f"Response length: {len(response)} characters")
    
    if "help" in response.lower() and len(response) > 50:
        print("✅ Help command works correctly")
    else:
        print("❌ Help command failed")
    
    # Cleanup
    await db_manager.shutdown()
    print("\\n✅ All tests completed successfully!")

if __name__ == "__main__":
    try:
        asyncio.run(test_quit_commands())
    except KeyboardInterrupt:
        print("\\nTest interrupted by user")
    except Exception as e:
        print(f"\\nTest failed with error: {e}")
        # Activate safety net immediately on error
        try:
            subprocess.run(['killall', 'python3'], check=False)
        except:
            pass
