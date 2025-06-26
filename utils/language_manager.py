import json
import logging
import os

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_TRANSLATION_FILE_PATH = os.path.join(_CURRENT_DIR, 'translation.json')


class LanguageManager:
    def __init__(self, file_path=_TRANSLATION_FILE_PATH):
        try:
            with open(file_path, 'r') as f:
                self.translations = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(f"Could not load or parse translations file: {e}")
            self.translations = {}

    def get_string(self, key, lang='en', **kwargs):
        """Retrieve translated string using a dot-seperated key."""
        try:
            keys = key.split('.')
            text_obj = self.translations
            for k in keys:
                text_obj = text_obj[k]

            translated_text = text_obj.get(lang, text_obj.get('en'))

            if not translated_text:
                logging.warning(f"Translation key {key} not found")
                return key

            return translated_text.format(**kwargs)
        except KeyError:
            logging.warning(f"Translation key: {key} not found in translations file.")
            return key
        except Exception as e:
            logging.error(f"Error getting translations for key: {key}: {e}")
            return key
