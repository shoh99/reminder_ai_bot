import json
import logging
from datetime import datetime

from typing import Optional

import pytz
from dateutil.rrule import rrulestr, HOURLY, DAILY, WEEKLY, MONTHLY, MINUTELY

logger = logging.getLogger(__name__)


def convert_to_json(text: str) -> Optional[dict]:
    try:
        if text is None: return None
        json_string = text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except (json.JSONDecodeError, TypeError) as e:
        logger.error(f"Failed to convert text to JSON: {e}\nText was: {text}")
        return None


def create_human_readable_rule(rrule_str: str, start_time_local: datetime, lm, lang: str) -> str:
    """Creates a user-friendly and translated description of a recurring rule."""

    try:
        rule = rrulestr(rrule_str, dtstart=start_time_local)

        # --- Get translated building blocks from the JSON file ---
        every_word = lm.get_string("human_readable_rule.every", lang)

        day_map_keys = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        day_map = {i: lm.get_string(f"human_readable_rule.days.{day_key}", lang) for i, day_key in
                   enumerate(day_map_keys)}

        freq_keys_map = {MINUTELY: 'minute', HOURLY: "hour", DAILY: "day", WEEKLY: "week", MONTHLY: "month"}

        # --- Build the rule string based on frequency ---
        rule_text = ""

        if rule._freq == WEEKLY and rule._byweekday:
            # Handle specific days of the week (e.g., "Every Monday, Friday")
            days_of_week = ', '.join([day_map[d] for d in rule._byweekday])
            # Note: For Russian, this part is simplified. 'Каждую' works for plural days.
            if lang == 'ru' and len(rule._byweekday) > 1:
                rule_text = lm.get_string("human_readable_rule.weekly_days_pattern", lang,
                                          days_of_week=days_of_week).replace("Каждую", "Каждый")
            else:
                rule_text = lm.get_string("human_readable_rule.weekly_days_pattern", lang, days_of_week=days_of_week)

        else:
            # Handle other frequencies (e.g., "Every 2 days", "Every month")
            interval = rule._interval
            plural = lm.get_string("human_readable_rule.plural_s", lang) if interval > 1 else ''

            freq_key = freq_keys_map.get(rule._freq, 'time')
            freq_text = lm.get_string(f"human_readable_rule.frequency.{freq_key}", lang)

            # Basic pluralization for English
            if lang == 'en':
                freq_text += plural

            # Construct the main text
            interval_str = str(interval) if interval > 1 else ''
            rule_text = f"{every_word} {interval_str} {freq_text}".strip()

        # --- Add the time suffix ---
        time_str = start_time_local.strftime('%H:%M')
        rule_text += lm.get_string("human_readable_rule.at_time_pattern", lang, time=time_str)

        return rule_text.capitalize()

    except Exception as e:
        print(f"Error while creating human readable rule: {e}")
        # Use the existing fallback translation key
        return lm.get_string(
            "reminders.recurring_schedule_start",
            lang,
            start_date=start_time_local.strftime('%A, %B %d')
        )


def safe_timezone_convert(dt: datetime, target_tz: pytz.BaseTzInfo, source_ts: pytz.BaseTzInfo = pytz.utc) -> datetime:
    try:
        if dt.tzinfo is None:
            dt_aware = source_ts.localize(dt)
        else:
            dt_aware = dt.astimezone(source_ts) if dt.tzinfo != source_ts else dt

        return dt_aware.astimezone(target_tz)

    except Exception as e:
        logging.error(f"Timezone conversion error: {e}")
        if dt.tzinfo is None:
            return pytz.utc.localize(dt)
        return dt.astimezone(pytz.utc)
