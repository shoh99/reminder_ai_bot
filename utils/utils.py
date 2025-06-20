import json
import logging

from typing import Optional

logger = logging.getLogger(__name__)


def convert_to_json(text: str) -> Optional[dict]:
    try:
        if text is None: return None
        json_string = text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except (json.JSONDecodeError, TypeError) as e:
        logger.error(f"Failed to convert text to JSON: {e}\nText was: {text}")
        return None