import logging

from aiogram import F
from aiogram.filters import Filter
from utils.language_manager import LanguageManager


def TranslatedText(lm: LanguageManager, key: str) -> Filter:
    try:
        keys = key.split(".")
        translation_dict = lm.translations
        for k in keys:
            translation_dict = translation_dict[k]

        all_translation = list(translation_dict.values())
        return F.text.in_(all_translation)
    except (KeyError, AttributeError):
        logging.warning(f"Warning: Could not create filter for translation key: {key}. Key not found.")
        return F.text.func(lambda text: False)
