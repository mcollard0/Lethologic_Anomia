#!/usr/bin/env python3
"""
Translation Management Script

Script to extract, update, and compile translations for the Migration Service.
Requires Babel to be installed for full functionality.
"""

import os
import sys
import argparse
import subprocess
from pathlib import Path
from typing import List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from babel.messages import frontend as babel_frontend
    from babel.messages.extract import extract_from_dir
    from babel.messages.pofile import read_po, write_po
    from babel.messages.mofile import write_mo
    from babel.messages.catalog import Catalog
    BABEL_AVAILABLE = True
except ImportError:
    BABEL_AVAILABLE = False

from core.custom_logging import get_logger

logger = get_logger(__name__)


class TranslationManager:
    """Translation Management Utility"""
    
    def __init__(self, base_dir: str):
        """
        Initialize translation manager
        
        Args:
            base_dir: Base directory of the project
        """
        self.base_dir = Path(base_dir)
        self.locales_dir = self.base_dir / 'locales'
        self.translations_dir = self.locales_dir / 'translations'
        self.pot_file = self.locales_dir / 'messages.pot'
        self.babel_cfg = self.base_dir / 'babel.cfg'
        
        # Supported locales
        self.supported_locales = ['en', 'de', 'fr', 'es', 'it', 'ja', 'zh']
        
        # Create directories if they don't exist
        self.translations_dir.mkdir(parents=True, exist_ok=True)
    
    def extract_messages(self) -> bool:
        """
        Extract translatable messages from source code
        
        Returns:
            True if extraction successful
        """
        try:
            if not BABEL_AVAILABLE:
                logger.error("Babel not available for message extraction")
                return False
            
            logger.info("Extracting translatable messages...")
            
            # Extract messages using Babel
            catalog = Catalog(project='Migration Service', version='1.0')
            
            # Extract from Python files
            extracted = extract_from_dir(
                str(self.base_dir),
                method_map=[
                    ('**.py', 'python'),
                ],
                options_map={
                    '**.py': {
                        'encoding': 'utf-8'
                    }
                },
                keywords=['_', 'ngettext:1,2', 'translate'],
                comment_tags=['TRANSLATORS:'],
                strip_comments=True
            )
            
            # Add extracted messages to catalog
            for filename, lineno, message, comments, context in extracted:
                if isinstance(message, tuple):
                    # Plural form
                    catalog.add(message[0], plural=message[1], 
                               locations=[(filename, lineno)], auto_comments=comments)
                else:
                    # Singular form
                    catalog.add(message, locations=[(filename, lineno)], auto_comments=comments)
            
            # Write POT file
            with open(self.pot_file, 'wb') as f:\n                write_po(f, catalog, sort_output=True, sort_by_file=True)\n            \n            logger.info(f\"Extracted {len(catalog)} messages to {self.pot_file}\")\n            return True\n            \n        except Exception as e:\n            logger.error(f\"Message extraction failed: {e}\")\n            return False\n    \n    def update_translations(self, locales: Optional[List[str]] = None) -> bool:\n        \"\"\"\n        Update translation files with new messages\n        \n        Args:\n            locales: List of locales to update (all if None)\n            \n        Returns:\n            True if update successful\n        \"\"\"\n        try:\n            if not BABEL_AVAILABLE:\n                logger.error(\"Babel not available for translation updates\")\n                return False\n            \n            if not self.pot_file.exists():\n                logger.error(\"POT file not found. Run extract_messages first.\")\n                return False\n            \n            target_locales = locales or self.supported_locales\n            \n            # Load template catalog\n            with open(self.pot_file, 'rb') as f:\n                template_catalog = read_po(f)\n            \n            for locale in target_locales:\n                logger.info(f\"Updating translations for locale: {locale}\")\n                \n                # Create locale directory\n                locale_dir = self.translations_dir / locale / 'LC_MESSAGES'\n                locale_dir.mkdir(parents=True, exist_ok=True)\n                \n                po_file = locale_dir / 'messages.po'\n                \n                if po_file.exists():\n                    # Update existing catalog\n                    with open(po_file, 'rb') as f:\n                        existing_catalog = read_po(f, locale=locale)\n                    \n                    # Update with new messages from template\n                    existing_catalog.update(template_catalog)\n                    \n                    # Write updated catalog\n                    with open(po_file, 'wb') as f:\n                        write_po(f, existing_catalog, sort_output=True, sort_by_file=True)\n                        \n                else:\n                    # Create new catalog\n                    new_catalog = Catalog(locale=locale)\n                    new_catalog.update(template_catalog)\n                    \n                    # Write new catalog\n                    with open(po_file, 'wb') as f:\n                        write_po(f, new_catalog, sort_output=True, sort_by_file=True)\n                \n                logger.info(f\"Updated translations for {locale}\")\n            \n            return True\n            \n        except Exception as e:\n            logger.error(f\"Translation update failed: {e}\")\n            return False\n    \n    def compile_translations(self, locales: Optional[List[str]] = None) -> bool:\n        \"\"\"\n        Compile PO files to MO files\n        \n        Args:\n            locales: List of locales to compile (all if None)\n            \n        Returns:\n            True if compilation successful\n        \"\"\"\n        try:\n            target_locales = locales or self.supported_locales\n            compiled_count = 0\n            \n            for locale in target_locales:\n                locale_dir = self.translations_dir / locale / 'LC_MESSAGES'\n                po_file = locale_dir / 'messages.po'\n                mo_file = locale_dir / 'messages.mo'\n                \n                if po_file.exists():\n                    if BABEL_AVAILABLE:\n                        # Use Babel\n                        with open(po_file, 'rb') as f:\n                            catalog = read_po(f)\n                        \n                        with open(mo_file, 'wb') as f:\n                            write_mo(f, catalog)\n                            \n                        compiled_count += 1\n                        logger.info(f\"Compiled translations for {locale}\")\n                        \n                    else:\n                        # Try using system msgfmt\n                        try:\n                            subprocess.run(\n                                ['msgfmt', '-o', str(mo_file), str(po_file)],\n                                check=True,\n                                capture_output=True\n                            )\n                            compiled_count += 1\n                            logger.info(f\"Compiled translations for {locale} using msgfmt\")\n                        except (subprocess.CalledProcessError, FileNotFoundError):\n                            logger.warning(f\"Could not compile {locale} - msgfmt not available\")\n                else:\n                    logger.warning(f\"PO file not found for locale: {locale}\")\n            \n            logger.info(f\"Compiled {compiled_count} translation files\")\n            return compiled_count > 0\n            \n        except Exception as e:\n            logger.error(f\"Translation compilation failed: {e}\")\n            return False\n    \n    def create_locale(self, locale: str) -> bool:\n        \"\"\"\n        Create a new locale directory and empty PO file\n        \n        Args:\n            locale: Locale code to create\n            \n        Returns:\n            True if creation successful\n        \"\"\"\n        try:\n            locale_dir = self.translations_dir / locale / 'LC_MESSAGES'\n            locale_dir.mkdir(parents=True, exist_ok=True)\n            \n            po_file = locale_dir / 'messages.po'\n            \n            if not po_file.exists():\n                # Create empty catalog\n                if BABEL_AVAILABLE:\n                    catalog = Catalog(locale=locale)\n                    with open(po_file, 'wb') as f:\n                        write_po(f, catalog)\n                else:\n                    # Create basic PO file header\n                    po_content = f'''# Translation for {locale}\nmsgid \"\"\nmsgstr \"\"\n\"Language: {locale}\\\\n\"\n\"MIME-Version: 1.0\\\\n\"\n\"Content-Type: text/plain; charset=UTF-8\\\\n\"\n\"Content-Transfer-Encoding: 8bit\\\\n\"\n'''\n                    with open(po_file, 'w', encoding='utf-8') as f:\n                        f.write(po_content)\n                \n                logger.info(f\"Created locale directory and PO file for: {locale}\")\n                return True\n            else:\n                logger.info(f\"Locale {locale} already exists\")\n                return True\n                \n        except Exception as e:\n            logger.error(f\"Failed to create locale {locale}: {e}\")\n            return False\n    \n    def validate_translations(self) -> Dict[str, Any]:\n        \"\"\"\n        Validate all translation files\n        \n        Returns:\n            Validation results\n        \"\"\"\n        results = {\n            'valid_locales': [],\n            'invalid_locales': [],\n            'missing_locales': [],\n            'total_messages': 0,\n            'translated_messages': {},\n            'completion_percentage': {}\n        }\n        \n        try:\n            # Check each supported locale\n            for locale in self.supported_locales:\n                locale_dir = self.translations_dir / locale / 'LC_MESSAGES'\n                po_file = locale_dir / 'messages.po'\n                \n                if po_file.exists():\n                    try:\n                        if BABEL_AVAILABLE:\n                            with open(po_file, 'rb') as f:\n                                catalog = read_po(f)\n                            \n                            total = len(list(catalog))\n                            translated = len([msg for msg in catalog if msg.string])\n                            \n                            results['translated_messages'][locale] = translated\n                            results['completion_percentage'][locale] = (\n                                (translated / total * 100) if total > 0 else 0\n                            )\n                            results['total_messages'] = total\n                            \n                        results['valid_locales'].append(locale)\n                        \n                    except Exception as e:\n                        logger.error(f\"Invalid translation file for {locale}: {e}\")\n                        results['invalid_locales'].append(locale)\n                else:\n                    results['missing_locales'].append(locale)\n            \n            logger.info(f\"Translation validation completed: {len(results['valid_locales'])} valid\")\n            return results\n            \n        except Exception as e:\n            logger.error(f\"Translation validation failed: {e}\")\n            return results\n\n\ndef main():\n    \"\"\"Main function for translation management CLI\"\"\"\n    parser = argparse.ArgumentParser(description='Migration Service Translation Manager')\n    \n    subparsers = parser.add_subparsers(dest='command', help='Available commands')\n    \n    # Extract command\n    extract_parser = subparsers.add_parser('extract', help='Extract messages from source code')\n    \n    # Update command\n    update_parser = subparsers.add_parser('update', help='Update translation files')\n    update_parser.add_argument('--locale', action='append', help='Specific locale to update')\n    \n    # Compile command\n    compile_parser = subparsers.add_parser('compile', help='Compile PO files to MO files')\n    compile_parser.add_argument('--locale', action='append', help='Specific locale to compile')\n    \n    # Create command\n    create_parser = subparsers.add_parser('create', help='Create new locale')\n    create_parser.add_argument('locale', help='Locale code to create')\n    \n    # Validate command\n    validate_parser = subparsers.add_parser('validate', help='Validate translation files')\n    \n    # Init command\n    init_parser = subparsers.add_parser('init', help='Initialize translation system')\n    \n    args = parser.parse_args()\n    \n    if not args.command:\n        parser.print_help()\n        return\n    \n    # Determine base directory\n    base_dir = Path(__file__).parent.parent\n    \n    # Initialize translation manager\n    manager = TranslationManager(str(base_dir))\n    \n    if args.command == 'extract':\n        success = manager.extract_messages()\n        print(f\"Message extraction: {'SUCCESS' if success else 'FAILED'}\")\n        \n    elif args.command == 'update':\n        success = manager.update_translations(args.locale)\n        print(f\"Translation update: {'SUCCESS' if success else 'FAILED'}\")\n        \n    elif args.command == 'compile':\n        success = manager.compile_translations(args.locale)\n        print(f\"Translation compilation: {'SUCCESS' if success else 'FAILED'}\")\n        \n    elif args.command == 'create':\n        success = manager.create_locale(args.locale)\n        print(f\"Locale creation: {'SUCCESS' if success else 'FAILED'}\")\n        \n    elif args.command == 'validate':\n        results = manager.validate_translations()\n        print(\"\\nTranslation Validation Results:\")\n        print(f\"Valid locales: {', '.join(results['valid_locales'])}\")\n        print(f\"Invalid locales: {', '.join(results['invalid_locales'])}\")\n        print(f\"Missing locales: {', '.join(results['missing_locales'])}\")\n        print(f\"Total messages: {results['total_messages']}\")\n        print(\"\\nCompletion percentages:\")\n        for locale, percentage in results['completion_percentage'].items():\n            print(f\"  {locale}: {percentage:.1f}%\")\n            \n    elif args.command == 'init':\n        print(\"Initializing translation system...\")\n        \n        # Extract messages\n        print(\"1. Extracting messages...\")\n        if manager.extract_messages():\n            print(\"   ✓ Messages extracted\")\n        else:\n            print(\"   ✗ Message extraction failed\")\n            return\n        \n        # Create locale directories\n        print(\"2. Creating locale directories...\")\n        for locale in manager.supported_locales:\n            if manager.create_locale(locale):\n                print(f\"   ✓ Created locale: {locale}\")\n            else:\n                print(f\"   ✗ Failed to create locale: {locale}\")\n        \n        # Update translations\n        print(\"3. Updating translations...\")\n        if manager.update_translations():\n            print(\"   ✓ Translations updated\")\n        else:\n            print(\"   ✗ Translation update failed\")\n        \n        # Compile translations\n        print(\"4. Compiling translations...\")\n        if manager.compile_translations():\n            print(\"   ✓ Translations compiled\")\n        else:\n            print(\"   ✗ Translation compilation failed\")\n        \n        print(\"\\nTranslation system initialization complete!\")\n        print(\"\\nNext steps:\")\n        print(\"1. Edit PO files in locales/translations/*/LC_MESSAGES/\")\n        print(\"2. Run 'python manage_translations.py compile' to compile changes\")\n        print(\"3. Test translations in your application\")\n\n\nif __name__ == '__main__':\n    main()
