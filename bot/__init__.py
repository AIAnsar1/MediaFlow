from bot.processor import update_processor, UpdateProcessor

# MESSAGES and get_message are expected by some components
try:
    from i18n.lang import MESSAGES, get_message
except ImportError:
    # Fallback if i18n.lang is missing
    MESSAGES = {}
    def get_message(key: str, lang: str = "en", **kwargs) -> str:
        return key

from bot.keyboards import (
    get_language_keyboard,
)

__all__ = [
    "update_processor",
    "UpdateProcessor",
    "MESSAGES",
    "get_message",
    "get_language_keyboard",
]
