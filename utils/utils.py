import json
import logging
from datetime import datetime

from typing import Optional

from dateutil.rrule import rrulestr, HOURLY, DAILY, WEEKLY, MONTHLY

logger = logging.getLogger(__name__)


def convert_to_json(text: str) -> Optional[dict]:
    try:
        if text is None: return None
        json_string = text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except (json.JSONDecodeError, TypeError) as e:
        logger.error(f"Failed to convert text to JSON: {e}\nText was: {text}")
        return None


def create_human_readable_rule(rrule_str: str, start_time_local: datetime) -> str:
    """creates a user-friendly description of a recurring rules"""

    try:
        rule = rrulestr(rrule_str, dtstart=start_time_local)
        freq_map = {
            HOURLY: "hour", DAILY: "day", WEEKLY: "week", MONTHLY: "month"
        }

        interval = rule._interval
        plural = 's' if interval > 1 else ''
        freq_text = freq_map.get(rule._freq, 'time') + plural
        rule_text = f"Every {interval if interval > 1 else ''} {freq_text}".replace(" ", " ").capitalize()

        if rule._freq == WEEKLY and rule._byweekday:
            day_map = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday', 4: 'Friday', 5: 'Saturday', 6:'Sunday'}
            days = ', '.join([day_map[d] for d in rule._byweekday])
            rule_text = f"Every {days}"

        rule_text += f" at {start_time_local.strftime('%I:%M %p')}"
        return rule_text

    except Exception as e:
        print(f"Erroring while creating human readable rule: {e}")
        return f"Recurring schedule starting on {start_time_local.strftime('%A, %B %d')}"
