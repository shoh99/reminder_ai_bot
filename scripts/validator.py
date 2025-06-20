import re
from datetime import datetime, timedelta


def validate_and_sanitize_input(text: str) -> str:
    """Validate and sanitize user input"""
    if not text or len(text.strip()) == 0:
        raise ValueError("Input cannot be empty")

    # Remove potentially dangerous characters
    sanitized = re.sub(r'[<>"\']', '', text.strip())

    if len(sanitized) > 500:  # Reasonable limit
        raise ValueError("Input too long")

    return sanitized


def validate_datetime(date_str: str, time_str: str) -> datetime:
    """Validate and parse datetime with proper error handling"""
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M:%S')

        # Check if datetime is in reasonable future (not more than 1 year)
        max_future = datetime.now() + timedelta(days=365)
        if dt > max_future:
            raise ValueError("Date too far in the future")

        if dt < datetime.now():
            raise ValueError("Date is in the past")

        return dt
    except ValueError as e:
        raise ValueError(f"Invalid date/time format: {e}")