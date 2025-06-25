import os

from datetime import datetime
from typing import Optional

import pytz
from google import genai
from google.genai import types


class AIManager:
    def __init__(self, api_key: str):
        """Initializes the AI model client"""
        try:
            self.ai_client = genai.Client(api_key=api_key)
        except Exception as e:
            print(f"Failed to initialize Gemini Client")
            self.ai_client = None

    def is_ready(self) -> bool:
        return self.ai_client is not None

    def analyze_text(self, text: str, user_timezone: str = 'UTC') -> Optional[str]:
        """Analyzes text to extrac reminder details using Gemini"""
        if not self.ai_client: return None

        user_tz = pytz.timezone(user_timezone)
        current_time_user = datetime.now(user_tz)
        current_date_str = current_time_user.strftime(f"%Y-%m-%d %H:%M:%S %Z")

        timezone_info = f"User's timezone: {user_timezone}"

        prompt = f"""
        You are an intelligent scheduling assistant. The user has provided a message in either Uzbek or English. Your job is to:
        
        1. Analyze the message to identify the scheduled event.
        2. Understand fuzzy or relative expressions such as "after 2 minutes", "in an hour", "tomorrow", or "ertaga" based on the current date: {current_date_str} and timezone: {timezone_info}, and convert them into exact date ("YYYY-MM-DD") and time ("HH:MM:SS") values.
        3. Distinguish clearly between:
        - One-time events: e.g., "after two minutes", "tomorrow at 9", "in 3 days"
        - Recurring events: e.g., "every day", "har kuni", "every Monday", "har dushanba"
        4. If it's a recurring event, generate a valid iCalendar RRULE string (e.g., 'FREQ=DAILY' or 'FREQ=WEEKLY;BYDAY=MO').
        5. Suggest a few relevant tags based on the event (e.g., ["work", "health", "personal"]).
        
        ⚠️ Very important:
        - Do **NOT** treat "after X minutes/hours/days" or "in X time" as recurring.
        - Only generate an RRULE if the user clearly meant **repetition** (e.g., “every”, “har”, or “each”).
        
        Respond STRICTLY with a JSON object in the following format:
        {{
        "event_name": "A short event name",
        "event_description": "A concise description of the event.",
        "date": "YYYY-MM-DD format. For recurring events, this should be the first occurrence date.",
        "time": "HH:MM:SS 24-hour format.",
        "type": "'one_time' or 'recurring'",
        "rrule": "A valid iCalendar RRULE string if recurring, otherwise null",
        "tags": ["Array", "of", "relevant", "tags", "like", "work", "health", "personal"],
        "status": "'success' if the event is clear, or 'clarification_needed' if date/time is ambiguous."
        }}
        
        User's text: "{text}"
        """

        try:
            response = self.ai_client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            return response.text
        except Exception as e:
            print(f"Error during AI text analysis: {e}")
            return None

    def analyze_audio(self, voice_file_path: str, user_timezone: str = 'UTC') -> Optional[str]:
        if not self.ai_client: return None

        user_tz = pytz.timezone(user_timezone)
        current_time_user = datetime.now(user_tz)
        current_date_str = current_time_user.strftime(f"%Y-%m-%d %H:%M:%S %Z")

        timezone_info = f"User's timezone: {user_timezone}"
        prompt = f"""
        You are a highly intelligent scheduling assistant. 
        Current date and time in user's timezone: {current_date_str}
        {timezone_info}
        
         The user has provided an audio recording in either Uzbek or English. Your job is to:

        1. Accurately transcribe the spoken content from the audio.
        2. Identify and extract the scheduled event, including its name, date, and time.
        3. Interpret fuzzy or relative timing (e.g., "tomorrow", "every day", "next Monday", "in 2 minutes").
           - IMPORTANT: Do not schedule events in the past.
           - If the specified time has already passed today, schedule it for the next valid future occurrence (e.g., tomorrow or the next cycle).
           - For high-frequency recurring events (e.g., "every 2 minutes"), ensure the first occurrence is slightly ahead of the current time.
        4. Determine whether the event is a one-time or recurring event.
           - If recurring, generate a valid iCalendar RRULE string (e.g., "FREQ=DAILY" or "FREQ=MINUTELY;INTERVAL=2").
        5. Analyze the event's context and suggest a few relevant tags in a list (e.g., "health", "personal", "work").

        Respond STRICTLY with a JSON object in the following format:
        {{
          "transcript": "The full transcript of the user's audio.",
          "event_name": "A short event name",
          "event_description": "A concise description of the event.",
          "date": "YYYY-MM-DD format. For recurring events, this should be the date of the first future occurrence.",
          "time": "HH:MM:SS 24-hour format.",
          "type": "Should be 'one_time' or 'recurring'.",
          "rrule": "An iCalendar RRULE string if the type is 'recurring', otherwise null.",
          "tags": ["An", "array", "of", "relevant", "tags", "like", "work", "personal", "health"],
          "status": "'success' if all information is clear, or 'clarification_needed' if date/time is ambiguous."
        }}

        Process the audio and return only the JSON object as specified.
        """
        try:
            with open(voice_file_path, 'rb') as f:
                audio_bytes = f.read()

            response = self.ai_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[
                    prompt,
                    types.Part.from_bytes(
                        data=audio_bytes,
                        mime_type="audio/mp3"
                    )
                ]
            )

            return response.text
        except Exception as e:
            print(f"Error during AI voice analysis: {e}")
            return None


