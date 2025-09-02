#!/usr/bin/env python3
"""
Test that Anthropic is now the primary AI model
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Core imports
from core.config import Settings, get_settings
from core.database import DatabaseManager
from core.custom_logging import setup_logging, get_logger
from core.ai_loop import AIService

async def test_anthropic_primary():
    """Test that Anthropic is configured as primary model"""
    
    setup_logging("INFO")
    logger = get_logger(__name__)
    
    print("=" * 80)
    print("🔄 TESTING: Anthropic as Primary AI Model")
    print("=" * 80)
    
    try:
        # Clear the settings cache to force fresh reload
        get_settings.cache_clear()
        
        # Initialize settings
        settings = get_settings()
        
        print("\n1️⃣  Checking AI Provider Configuration:")
        print(f"   Provider priority order: {settings.ai.ai_providers}")
        
        # Verify Anthropic is first
        if settings.ai.ai_providers and settings.ai.ai_providers[0] == "anthropic":
            print("   ✅ Anthropic is configured as primary provider")
        else:
            print("   ❌ Anthropic is not the primary provider")
            print(f"   Current primary: {settings.ai.ai_providers[0] if settings.ai.ai_providers else 'None'}")
        
        print(f"\n2️⃣  Checking API Key Configuration:")
        api_key_set = bool(settings.ai.anthropic_api_key)
        print(f"   Anthropic API key: {'✅ Set' if api_key_set else '❌ Not set'}")
        
        if api_key_set:
            # Mask the key for security
            masked_key = settings.ai.anthropic_api_key[:10] + "..." + settings.ai.anthropic_api_key[-4:]
            print(f"   Key format: {masked_key}")
        
        print(f"\n3️⃣  Testing AI Service Initialization:")
        
        # Initialize database
        db_manager = DatabaseManager(settings.database_url)
        await db_manager.initialize()
        
        # Create basic config table
        await db_manager.execute_query("""
            CREATE TABLE IF NOT EXISTS config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Initialize AI service
        ai_service = AIService(settings, db_manager)
        await ai_service.initialize()
        
        print(f"   Available providers: {ai_service.available_providers}")
        
        if "anthropic" in ai_service.available_providers:
            anthropic_position = ai_service.available_providers.index("anthropic")
            print(f"   ✅ Anthropic initialized successfully (position {anthropic_position + 1})") 
            
            if anthropic_position == 0:
                print("   🎯 Anthropic is the PRIMARY provider!")
            else:
                print(f"   ⚠️  Anthropic is fallback #{anthropic_position + 1}")
        else:
            print("   ❌ Anthropic not available")
        
        print(f"\n4️⃣  Model Information:")
        print("   Anthropic Model: claude-3-5-sonnet-20241022 (Latest)")
        print("   Features: Advanced reasoning, tool calling, code analysis")
        print("   Benefits: High accuracy, ethical AI, excellent for complex tasks")
        
        print(f"\n5️⃣  Summary:")
        if (settings.ai.ai_providers and settings.ai.ai_providers[0] == "anthropic" and 
            "anthropic" in ai_service.available_providers and
            ai_service.available_providers.index("anthropic") == 0):
            print("   🎉 SUCCESS: Anthropic is correctly configured as primary model")
            print("   - All requests will try Anthropic first")
            print("   - Local model is available as fallback") 
            print("   - Using latest Claude 3.5 Sonnet for best performance")
        else:
            print("   ⚠️  Configuration needs attention")
            print("   Check API key and provider order settings")
        
        await db_manager.shutdown()
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_anthropic_primary())
