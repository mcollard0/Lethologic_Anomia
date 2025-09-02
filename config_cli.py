#!/usr/bin/env python3
"""
Configuration CLI Utility

Command-line interface for managing service configurations stored in the database.
Allows viewing, setting, and exporting service configurations.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Add the project root to path
sys.path.insert(0, str(Path(__file__).parent))

from core.database import DatabaseManager
from core.config_manager import DatabaseConfigManager
from core.custom_logging import get_logger

logger = get_logger(__name__)


class ConfigCLI:
    """Configuration CLI manager"""
    
    def __init__(self, db_path: str = "migration_service.db"):
        """Initialize CLI with database path"""
        self.db_manager = DatabaseManager(db_path)
        self.config_manager = DatabaseConfigManager(self.db_manager)
    
    async def initialize(self):
        """Initialize the CLI"""
        await self.db_manager.initialize()
        await self.config_manager.initialize()
    
    async def list_services(self):
        """List all configured services"""
        print("Available services:")
        services = await self.config_manager.list_services()
        for service in services:
            print(f"  - {service}")
    
    async def show_service_config(self, service_name: str):
        """Show configuration for a specific service"""
        config = await self.config_manager.get_service_config(service_name)
        if config:
            print(f"Configuration for service '{service_name}':")
            for key, value in config.items():
                print(f"  {key}: {value}")
        else:
            print(f"No configuration found for service '{service_name}'")
    
    async def show_all_configs(self):
        """Show all service configurations"""
        all_configs = await self.config_manager.get_all_service_configs()
        for service_name, config in all_configs.items():
            print(f"\n[{service_name}]")
            for key, value in config.items():
                print(f"  {key} = {value}")
    
    async def set_config(self, service_name: str, config_name: str, value: str):
        """Set a configuration value"""
        # Try to parse value as JSON, otherwise treat as string
        try:
            parsed_value = json.loads(value)
        except json.JSONDecodeError:
            # Check for boolean strings
            if value.lower() in ('true', 'false'):
                parsed_value = value.lower() == 'true'
            # Check for numeric strings
            elif value.isdigit():
                parsed_value = int(value)
            else:
                parsed_value = value
        
        success = await self.config_manager.set_config_value(service_name, config_name, parsed_value)
        if success:
            print(f"Set {service_name}.{config_name} = {parsed_value}")
        else:
            print(f"Failed to set {service_name}.{config_name}")
    
    async def export_config(self, output_file: Optional[str] = None):
        """Export configuration to JSON file"""
        config_data = await self.config_manager.export_config()
        
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(config_data, f, indent=2)
            print(f"Configuration exported to {output_file}")
        else:
            print(json.dumps(config_data, indent=2))
    
    async def import_config(self, input_file: str):
        """Import configuration from JSON file"""
        try:
            with open(input_file, 'r') as f:
                config_data = json.load(f)
            
            success = await self.config_manager.import_config(config_data)
            if success:
                print(f"Configuration imported from {input_file}")
            else:
                print(f"Failed to import configuration from {input_file}")
                
        except FileNotFoundError:
            print(f"File not found: {input_file}")
        except json.JSONDecodeError as e:
            print(f"Invalid JSON in {input_file}: {e}")


async def main():
    """Main CLI entry point"""
    cli = ConfigCLI()
    await cli.initialize()
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python config_cli.py list                                  # List all services")
        print("  python config_cli.py show <service>                       # Show service config")
        print("  python config_cli.py show-all                             # Show all configs")
        print("  python config_cli.py set <service> <name> <value>         # Set config value")
        print("  python config_cli.py export [file.json]                   # Export to file or stdout")
        print("  python config_cli.py import <file.json>                   # Import from file")
        print("")
        print("Examples:")
        print("  python config_cli.py show dicom_scp")
        print("  python config_cli.py set dicom_scp port 50104")
        print("  python config_cli.py export my_config.json")
        return
    
    command = sys.argv[1]
    
    try:
        if command == "list":
            await cli.list_services()
        
        elif command == "show":
            if len(sys.argv) < 3:
                print("Error: Please specify service name")
                return
            await cli.show_service_config(sys.argv[2])
        
        elif command == "show-all":
            await cli.show_all_configs()
        
        elif command == "set":
            if len(sys.argv) < 5:
                print("Error: Please specify service, config name, and value")
                return
            await cli.set_config(sys.argv[2], sys.argv[3], sys.argv[4])
        
        elif command == "export":
            output_file = sys.argv[2] if len(sys.argv) > 2 else None
            await cli.export_config(output_file)
        
        elif command == "import":
            if len(sys.argv) < 3:
                print("Error: Please specify input file")
                return
            await cli.import_config(sys.argv[2])
        
        else:
            print(f"Unknown command: {command}")
    
    except Exception as e:
        print(f"Error: {e}")
    
    finally:
        await cli.db_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
