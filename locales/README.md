# Internationalization (i18n) Support

This directory contains the internationalization infrastructure for the Migration Service, providing multi-language support for user interfaces and messages.

## Overview

The i18n system supports:
- Multi-language message translation
- Locale-specific date/time/number formatting
- Plural form handling for different languages
- Medical terminology translations
- Dynamic language switching
- Translation fallbacks

## Supported Languages

Currently supported locales:
- **English (en)** - Default/fallback language
- **German (de)** - Deutsch
- **French (fr)** - Français
- **Spanish (es)** - Español
- **Italian (it)** - Italiano
- **Japanese (ja)** - 日本語
- **Chinese (zh)** - 中文

## Installation

Install the required dependencies:

```bash
pip install -r locales/requirements-i18n.txt
```

## Directory Structure

```
locales/
├── __init__.py                    # Package initialization
├── i18n_manager.py               # Main i18n management class
├── manage_translations.py        # Translation management CLI
├── requirements-i18n.txt         # Required dependencies
├── README.md                     # This file
└── translations/                 # Translation files
    ├── en/LC_MESSAGES/
    │   ├── messages.po           # English source messages
    │   └── messages.mo           # Compiled English messages
    ├── de/LC_MESSAGES/
    │   ├── messages.po           # German translations
    │   └── messages.mo           # Compiled German messages
    └── fr/LC_MESSAGES/
        ├── messages.po           # French translations
        └── messages.mo           # Compiled French messages
```

## Usage

### In Python Code

```python
from locales import get_translator, _, ngettext

# Get translator instance
translator = get_translator()

# Set locale
translator.set_locale('de')

# Simple translation
message = _("Welcome to Migration Service")

# Translation with parameters
message = _("Processing {count} images", count=5)

# Plural forms
message = ngettext(
    "{count} image", 
    "{count} images", 
    count
)

# Medical terminology
medical_terms = translator.get_medical_terms()
print(medical_terms['patient'])  # "Patient" in current locale

# Service names
service_names = translator.get_service_names()
print(service_names['dicom_service'])  # "DICOM Service" in current locale

# Format dates/numbers
formatted_date = translator.format_date(datetime.now())
formatted_number = translator.format_number(1234.56)
```

### Translation Management

#### Initialize Translation System
```bash
python locales/manage_translations.py init
```

#### Extract New Messages
```bash
python locales/manage_translations.py extract
```

#### Update Translation Files
```bash
# Update all locales
python locales/manage_translations.py update

# Update specific locale
python locales/manage_translations.py update --locale de
```

#### Compile Translations
```bash
# Compile all locales
python locales/manage_translations.py compile

# Compile specific locale
python locales/manage_translations.py compile --locale de
```

#### Create New Locale
```bash
python locales/manage_translations.py create es
```

#### Validate Translations
```bash
python locales/manage_translations.py validate
```

## Medical Terminology

The system includes specialized support for medical terminology:

### DICOM Modalities
- CT (Computed Tomography)
- MRI (Magnetic Resonance Imaging)
- XR (X-Ray)
- US (Ultrasound)
- MG (Mammography)
- NM (Nuclear Medicine)

### Common Medical Terms
- Patient/Patienten/Patient
- Study/Studie/Étude
- Series/Serie/Série
- Image/Bild/Image
- Diagnosis/Diagnose/Diagnostic

### Status Messages
- Running/Läuft/En cours
- Completed/Abgeschlossen/Terminé
- Failed/Fehlgeschlagen/Échec
- Processing/Verarbeitung/Traitement

## Adding New Languages

1. **Create locale directory**:
   ```bash
   python locales/manage_translations.py create <locale_code>
   ```

2. **Extract messages**:
   ```bash
   python locales/manage_translations.py extract
   ```

3. **Update translation files**:
   ```bash
   python locales/manage_translations.py update --locale <locale_code>
   ```

4. **Edit PO file**:
   Edit `locales/translations/<locale_code>/LC_MESSAGES/messages.po`

5. **Compile translations**:
   ```bash
   python locales/manage_translations.py compile --locale <locale_code>
   ```

## Translation File Format

PO files use the standard gettext format:

```po
# Comment
msgid "Original message"
msgstr "Translated message"

# Plural forms
msgid "{count} image"
msgid_plural "{count} images"
msgstr[0] "{count} Bild"
msgstr[1] "{count} Bilder"
```

## Integration with Services

The i18n system integrates with all Migration Service components:

- **Web Interface**: Automatic locale detection and UI translation
- **SSH Server**: Translated command responses
- **HL7/FHIR Services**: Localized medical terminology
- **AI Processing**: Translated analysis results
- **DICOM Services**: Modality and status translations

## Performance

- Translations are cached in memory for fast access
- MO files are used for optimal runtime performance
- Lazy loading of locale-specific resources
- Thread-safe operation for concurrent access

## Troubleshooting

### Common Issues

1. **Babel not installed**:
   ```bash
   pip install babel
   ```

2. **MO files not found**:
   ```bash
   python locales/manage_translations.py compile
   ```

3. **Missing translations**:
   Check PO files and add missing translations, then recompile.

4. **Locale not supported**:
   Add locale to `supported_locales` in `i18n_manager.py` and create PO file.

### Logs

Translation activities are logged to the main application log with detailed information about:
- Locale switching
- Translation loading/compilation
- Missing translations
- Formatting errors

## Contributing Translations

To contribute translations:

1. Create or update PO files for your locale
2. Test translations using the validation script
3. Submit translations with proper attribution
4. Follow medical terminology standards for healthcare terms

For questions about translations or adding new languages, refer to the main project documentation.
