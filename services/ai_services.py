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
        You are an intelligent scheduling assistant. Your task is to analyze the user's natural language request and extract detailed scheduling information. The current date and time is: {current_date_str}.

        Your goals:
        1. Determine whether the event is a one-time or recurring event.
        2. If it's recurring, generate a valid iCalendar RRULE string (e.g., 'FREQ=DAILY' or 'FREQ=MINUTELY;INTERVAL=2').
        3. Extract the start date and time for the event. 
           - IMPORTANT: Do NOT use the current time as the event time unless the user clearly says "now".
           - If the user gives a time that's already passed today, assume they mean the **next valid future time** (e.g., tomorrow or the next valid occurrence).
           - Round the start time to the next logical future occurrence (e.g., 2 minutes from now if they said "every 2 minutes").
        4. Suggest a few relevant tags based on the event context (e.g., "health", "personal", "work").

        Respond STRICTLY with a JSON object in the following format:
        {{
          "event_name": "A short event name",
          "event_description": "A concise description of the event.",
          "date": "YYYY-MM-DD format. For recurring events, this should be the date of the first future occurrence.",
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

        1. Accurately transcribe the spoken content from the audio.
        2. Identify and extract the scheduled event, including its name, date, and time.
        3. Interpret fuzzy or relative timing (e.g., "tomorrow", "every day", "next Monday", "in 2 minutes") using the current date and time: {current_date_str}.
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


