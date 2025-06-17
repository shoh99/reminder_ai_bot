import os

from datetime import datetime
from typing import Optional
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

    def analyze_text(self, text: str) -> Optional[str]:
        """Analyzes text to extrac reminder details using Gemini"""
        if not self.ai_client: return None

        current_date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prompt = f"""
        You are an intelligent scheduling assistant. Your task is to analyze the user's request and extract detailed scheduling information. The current date is {current_date_str}.

        Interpret the user's text to determine if the event is a one-time or recurring event.
        - If it's recurring, generate an appropriate iCalendar RRULE string (e.g., 'FREQ=DAILY' or 'FREQ=WEEKLY;BYDAY=MO').
        - Analyze the event's content and suggest a few relevant tags in a list.

        Respond STRICTLY with a JSON object in the following format:
        {{
          "event_name": "A short event name",
          "event_description": "A concise description of the event.",
          "date": "YYYY-MM-DD format. For recurring events, this should be the date of the first occurrence.",
          "time": "HH:MM:SS 24-hour format.",
          "type": "Should be 'one_time' or 'recurring'.",
          "rrule": "An iCalendar RRULE string if the type is 'recurring', otherwise null.",
          "tags": ["An", "array", "of", "relevant", "tags", "like", "work", "personal", "health"],
          "status": "'success' if all information is clear, or 'clarification_needed' if date/time is ambiguous."
        }}

        User's text: "{text}"
        """

        try:
            response = self.ai_client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            return response.text
        except Exception as e:
            print(f"Error during AI text analysis: {e}")
            return None

    def analyze_audio(self, voice_file_path: str) -> Optional[str]:
        if not self.ai_client: return None

        current_date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prompt = f"""
        You are a highly intelligent scheduling assistant. The user has provided an audio recording. Your task is to:
        1. Accurately transcribe the spoken content.
        2. Identify and extract the scheduled event from the transcript.
        3. Interpret fuzzy dates (e.g., "tomorrow", "next Monday", "every day") based on the current date: {current_date_str}, and convert them to exact "YYYY-MM-DD" and "HH:MM:SS" values.
        4. Determine if the event is a one-time or recurring event. If recurring, generate an appropriate iCalendar RRULE string.
        5. Analyze the event's content and suggest a few relevant tags in a list.

        Respond STRICTLY with a JSON object in the following format:
        {{
          "transcript": "The full transcript of the user's audio.",
          "event_name": "A short event name",
          "event_description": "A concise description of the event.",
          "date": "YYYY-MM-DD format. For recurring events, this should be the date of the first occurrence.",
          "time": "HH:MM:SS 24-hour format.",
          "type": "Should be 'one_time' or 'recurring'.",
          "rrule": "An iCalendar RRULE string if the type is 'recurring', otherwise null.",
          "tags": ["An", "array", "of", "relevant", "tags", "like", "work", "personal", "health"],
          "status": "'success' if all information is clear, or 'clarification_needed' if date/time is ambiguous."
        }}
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


