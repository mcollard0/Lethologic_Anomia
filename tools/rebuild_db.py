#!/usr/bin/env python3
"""
Database Rebuild Tool for Lethologic Anomia
Convenience wrapper around scripts/init_db.py for operations
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.init_db import main

if __name__ == "__main__":
    print("🔧 Lethologic Anomia Database Rebuild Tool")
    print("=" * 50)
    asyncio.run(main())
