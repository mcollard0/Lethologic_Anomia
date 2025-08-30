"""
Internationalization (i18n) Support

Provides multi-language support for Lethologic Anomia using
Babel for message translation and locale management.
"""

from .i18n_manager import I18nManager, get_translator

__all__ = ['I18nManager', 'get_translator']
