import os

from datetime import datetime
from typing import Optional

import pytz
from google import genai
from google.genai import types



lang_map = {
    "uz": "Uzbek",
    "ru": "Russian",
    "en":"English"
}

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

    def analyze_text(self, text: str, user_timezone: str = 'UTC', user_lang: str='en',) -> Optional[str]:
        """Analyzes text to extrac reminder details using Gemini"""
        if not self.ai_client: return None
        user_lang = lang_map[user_lang]

        user_tz = pytz.timezone(user_timezone)
        current_time_user = datetime.now(user_tz)
        current_date_str = current_time_user.strftime(f"%Y-%m-%d %H:%M:%S %Z")

        timezone_info = f"User's timezone: {user_timezone}"

        prompt = f"""
        You are a multilingual, intelligent scheduling assistant. The user has written a message in either Uzbek, Russian, or English. Your task is to:

        1. Analyze the message to extract scheduling information.
        2. Understand and interpret fuzzy or relative time expressions like:
           - Uzbek: "ertaga", "har kuni", "soat 8"
           - Russian: "завтра", "каждый день", "в 8 часов"
           - English: "tomorrow", "every day", "at 8"
        3. Convert all times and dates to precise formats using the current date: {current_date_str} {timezone_info}.
        4. Clearly distinguish between:
           - One-time events: e.g., "after two minutes", "in an hour", "tomorrow"
           - Recurring events: e.g., "every Monday", "har dushanba", "каждую неделю"
        5. Only generate an RRULE if the user clearly refers to repetition.
        6. Suggest a few relevant tags based on the event (e.g., ["work", "personal", "health"]).

        Finally, translate your response into the user's preferred language: "{user_lang}".
        - Use short, clear translations.
        - Only respond in that language.
        - Do not explain anything, just return the JSON object.

        Respond STRICTLY with a JSON object in the following format:
        {{
          "event_name": "A short event name in the user's language",
          "event_description": "A concise description of the event in the user's language",
          "date": "YYYY-MM-DD format. For recurring events, this should be the first occurrence date.",
          "time": "HH:MM:SS 24-hour format.",
          "type": "'one_time' or 'recurring'",
          "rrule": "A valid iCalendar RRULE string if recurring, otherwise null",
          "tags": ["Array", "of", "relevant", "tags", "translated", "into", "user", "language"],
          "status": "'success' if the event is clear, or 'clarification_needed' if date/time is ambiguous."
        }}

        User's message:
        \"{text}\"

        Only return the JSON response. No explanation or extra commentary.
        """

        try:
            response = self.ai_client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            return response.text
        except Exception as e:
            print(f"Error during AI text analysis: {e}")
            return None

    def analyze_audio(self, voice_file_path: str, user_timezone: str = 'UTC', user_lang: str = 'en') -> Optional[str]:
        user_lang = lang_map[user_lang]
        if not self.ai_client: return None

        user_tz = pytz.timezone(user_timezone)
        current_time_user = datetime.now(user_tz)
        current_date_str = current_time_user.strftime(f"%Y-%m-%d %H:%M:%S %Z")

        timezone_info = f"User's timezone: {user_timezone}"
        prompt = f"""
        You are a highly intelligent, multilingual scheduling assistant. The user has provided an audio recording in either Uzbek, Russian, or English. Your tasks are:

        1. Accurately transcribe the audio into text.
        2. Identify the scheduled event from the transcript.
        3. Detect and interpret fuzzy or relative time expressions such as:
           - Uzbek: "ertaga", "har kuni", "soat 8"
           - Russian: "завтра", "каждый день", "в 8 часов"
           - English: "tomorrow", "every day", "at 8"
        4. Convert all fuzzy time expressions into exact "YYYY-MM-DD" and "HH:MM:SS" formats, using the current date: {current_date_str}, {timezone_info}.
        5. Determine whether the event is:
           - a one-time event: e.g., “after 2 minutes”, “ertaga”, “через час”
           - or a recurring event: e.g., “every Monday”, “har dushanba”, “каждый день”
        6. If the event is recurring, generate a valid iCalendar RRULE (e.g., "FREQ=WEEKLY;BYDAY=MO").
        7. Suggest a few relevant tags in the user's language (e.g., ["work", "health", "personal"]).

        ⚠️ Do NOT treat phrases like “after 2 minutes” or “через 5 минут” as recurring events. These are one-time events.

        Translate the final response fields into the user's preferred language: "{user_lang}".
        - The transcript may remain in the spoken language.
        - All other fields must be translated to "{user_lang}".
        - Do not include explanations or commentary.

        Respond STRICTLY with a JSON object in the following format:
        {{
          "transcript": "Full transcription of the user's audio.",
          "event_name": "A short event name in the user's language",
          "event_description": "A concise description in the user's language",
          "date": "YYYY-MM-DD",
          "time": "HH:MM:SS",
          "type": "'one_time' or 'recurring'",
          "rrule": "A valid iCalendar RRULE string if recurring, otherwise null",
          "tags": ["List", "of", "translated", "tags", "based", "on", "event"],
          "status": "'success' if event is understood, otherwise 'clarification_needed'"
        }}

        Only return this JSON object. Do not include extra explanation.
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


