import logging
import os

from datetime import datetime
from typing import Optional

import pytz
from google import genai
from google.genai import types

lang_map = {
    "uz": "Uzbek",
    "ru": "Russian",
    "en": "English"
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

    def analyze_text(self, text: str, user_timezone: str = 'UTC', user_lang: str = 'en', ) -> Optional[str]:
        """Analyzes text to extrac reminder details using Gemini"""
        if not self.ai_client: return None

        user_tz = pytz.timezone(user_timezone)
        current_time_user = datetime.now(user_tz)
        current_date_str = current_time_user.strftime(f"%Y-%m-%d %H:%M:%S %Z")

        timezone_info = f"User's timezone: {user_timezone}"
        user_lang = lang_map.get(user_lang, 'en')
        logging.info(f"User langauge: {user_lang}")

        prompt = f"""
        You are a multilingual, intelligent scheduling assistant. The user has written a message in either Uzbek, Russian, or English. Your task is to:
        User's language: {user_lang}
        1. Analyze the message to extract scheduling information.
        2. Understand and interpret fuzzy or relative time expressions like:
           - Uzbek: "ertaga", "har kuni", "soat 8"
           - Russian: "завтра", "каждый день", "в 8 часов"
           - English: "tomorrow", "every day", "at 8"
        3. IMPORTANT: Determine if this is a REMINDER request or an EVENT scheduling:
               - If user says "remind me X minutes/hours before [event]", calculate the REMINDER time, not the event time
               - If user says "I have a meeting at 7", schedule the EVENT time
               - Current time: {current_date_str} {timezone_info}
            4. Convert all fuzzy time expressions into exact "YYYY-MM-DD" and "HH:MM:SS" formats:
               - Uzbek: "ertaga" (tomorrow), "har kuni" (every day), "soat 8" (at 8)
               - Russian: "завтра" (tomorrow), "каждый день" (every day), "в 8 часов" (at 8)
               - English: "tomorrow", "every day", "at 8"
            5. Time interpretation rules:
               - If user says "at 7" without AM/PM and it's currently past 7 PM, assume 7 AM tomorrow
               - If user says "at 7" without AM/PM and it's currently before 7 AM, assume 7 AM today
               - If user says "at 7" without AM/PM and it's between 7 AM-7 PM, assume 7 PM today
               - If the calculated time is in the past, move it to the next logical occurrence
            6. For default times (when no specific time mentioned):
               - Morning events: 08:00:00
               - Afternoon/evening context: 17:00:00 (5 PM)
               - Meeting context: 10:00:00 (10 AM)
            7. Determine event type:
               - One-time: "after 2 minutes", "tomorrow", "next Monday"
               - Recurring: "every Monday", "daily", "каждый день"
            8. If recurring, generate valid iCalendar RRULE (e.g., "FREQ=WEEKLY;BYDAY=MO").
            9. Suggest relevant tags in user's language.
            
         ⚠️ CRITICAL: 
            - For "remind me 30 minutes before X at Y time" → return the reminder time (Y minus 30 minutes)
            - For "I have X at Y time" → return the event time (Y)
            - Do NOT treat phrases like "after 2 minutes" as recurring events
            
        Respond STRICTLY with a JSON object in the following format:
        {{
          "event_name": "A short event name in the {user_lang} language",
          "event_description": "A concise description of the event in the {user_lang} language",
          "date": "YYYY-MM-DD format. For recurring events, this should be the first occurrence date.",
          "time": "HH:MM:SS 24-hour format.",
          "type": "'one_time' or 'recurring'",
          "rrule": "A valid iCalendar RRULE string if recurring, otherwise null",
          "tags": ["Array", "of", "relevant", "tags", "translated", "into", "{user_lang}"],
          "status": "'success' if the event is clear, or 'clarification_needed' if date/time or event is ambiguous."
        }}

        User's message:
        \"{text}\"

        Only return the JSON response. No explanation or extra commentary.
        """

        try:
            response = self.ai_client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            return response.text
        except Exception as e:
            logging.error(f"Error during AI text analysis: {e}")
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
            User's language: {user_lang}
            1. Accurately transcribe the audio into text.
            2. Identify the scheduled event from the transcript.
            3. IMPORTANT: Determine if this is a REMINDER request or an EVENT scheduling:
               - If user says "remind me X minutes/hours before [event]", calculate the REMINDER time, not the event time
               - If user says "I have a meeting at 7", schedule the EVENT time
               - Current time: {current_date_str} {timezone_info}
            4. Convert all fuzzy time expressions into exact "YYYY-MM-DD" and "HH:MM:SS" formats:
               - Uzbek: "ertaga" (tomorrow), "har kuni" (every day), "soat 8" (at 8)
               - Russian: "завтра" (tomorrow), "каждый день" (every day), "в 8 часов" (at 8)
               - English: "tomorrow", "every day", "at 8"
            5. Time interpretation rules:
               - If user says "at 7" without AM/PM and it's currently past 7 PM, assume 7 AM tomorrow
               - If user says "at 7" without AM/PM and it's currently before 7 AM, assume 7 AM today
               - If user says "at 7" without AM/PM and it's between 7 AM-7 PM, assume 7 PM today
               - If the calculated time is in the past, move it to the next logical occurrence
            6. For default times (when no specific time mentioned):
               - Morning events: 08:00:00
               - Afternoon/evening context: 17:00:00 (5 PM)
               - Meeting context: 10:00:00 (10 AM)
            7. Determine event type:
               - One-time: "after 2 minutes", "tomorrow", "next Monday"
               - Recurring: "every Monday", "daily", "каждый день"
            8. If recurring, generate valid iCalendar RRULE (e.g., "FREQ=WEEKLY;BYDAY=MO").
            9. Suggest relevant tags in user's language.

            ⚠️ CRITICAL: 
            - For "remind me 30 minutes before X at Y time" → return the reminder time (Y minus 30 minutes)
            - For "I have X at Y time" → return the event time (Y)
            - Do NOT treat phrases like "after 2 minutes" as recurring events

            Translate response fields to "{user_lang}" (transcript can remain in original language).

            Respond STRICTLY with JSON:
            {{
              "transcript": "Full audio transcription",
              "event_name": "Short event name in user's language",
              "event_description": "Concise description in user's language",
              "date": "YYYY-MM-DD",
              "time": "HH:MM:SS",
              "type": "'one_time' or 'recurring'",
              "rrule": "iCalendar RRULE if recurring, otherwise null",
              "tags": ["translated", "tags", "list"],
              "status": "'success' if the event is clear, or 'clarification_needed' if date/time or event is ambiguous."
            }}

            Only return this JSON. No explanations.
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
            logging.error(f"Error during AI voice analysis: {e}")
            return None


def choose_prompt(lang, current_date_str, timezone_info, text):
    logging.info(f"Response Language: {lang}")
    if lang == "UZ":
        return prompt_in_uzbek(current_date_str, timezone_info, text)
    elif lang == "RU":
        return prompt_in_russian(current_date_str, timezone_info, text)
    else:
        return prompt_in_english(current_date_str, timezone_info, text)


def prompt_in_english(current_date_str, timezone_info, text):
    return f"""
    You are an intelligent scheduling assistant. The user has written a message in English. Your task is to:

    1. Analyze the message to extract scheduling information.
    2. Understand and interpret fuzzy or relative time expressions like: "tomorrow", "every day", "in an hour", "at 8 PM".
    3. Convert all times and dates to a precise format using the current date: {current_date_str} {timezone_info}.
    4. Clearly distinguish between:
       - One-time events: e.g., "after two minutes", "in an hour", "tomorrow".
       - Recurring events: e.g., "every Monday", "weekly", "every month".
       - If the user does NOT mention a specific time, assume the default time is 08:00:00 (8 AM local time).
       - Do NOT default to 00:00:00 unless the user explicitly says "midnight".
    5. Only generate an RRULE if the user clearly refers to repetition.
    6. Suggest a few relevant tags based on the event (e.g., ["work", "personal", "health"]).

    Finally, ensure all text in your response is in English.
    - Do not explain anything, just return the JSON object.

    Respond STRICTLY with a JSON object in the following format:
    {{
      "event_name": "A short event name in English",
      "event_description": "A concise description of the event in English",
      "date": "YYYY-MM-DD format. For recurring events, this is the first occurrence.",
      "time": "HH:MM:SS 24-hour format.",
      "type": "'one_time' or 'recurring'",
      "rrule": "A valid iCalendar RRULE string if recurring, otherwise null",
      "tags": ["Array", "of", "relevant", "tags", "in", "English"],
      "status": "'success' if the event is clear, or 'clarification_needed' if date/time is ambiguous."
    }}

    User's message:
    \"{text}\"

    Only return the JSON response. No explanation or extra commentary.
    """


def prompt_in_uzbek(current_date_str, timezone_info, text):
    return f"""
    Siz aqlli rejalashtiruvchi yordamchisiz. Foydalanuvchi o'zbek tilida xabar yozdi. Sizning vazifangiz:

    1. Rejalashtirish ma'lumotlarini ajratib olish uchun xabarni tahlil qilish.
    2. Noaniq yoki nisbiy vaqt iboralarini tushunish va izohlash, masalan: "ertaga", "har kuni", "bir soatdan keyin", "kechki 8 da".
    3. Joriy sanadan foydalanib, barcha vaqt va sana iboralarini aniq formatga o'tkazish: {current_date_str} {timezone_info}.
    4. Quyidagilarni aniq ajratish:
       - Bir martalik hodisalar: masalan, "ikki daqiqadan so'ng", "bir soatdan keyin", "ertaga".
       - Takrorlanadigan hodisalar: masalan, "har dushanba", "har hafta", "har oy".
       - Agar foydalanuvchi aniq vaqtni ko'rsatmasa, standart vaqt sifatida 08:00:00 (mahalliy vaqt bilan ertalab 8) ni qabul qiling.
       - Agar foydalanuvchi aniq "yarim tun" demasa, standart vaqt sifatida 00:00:00 ni ishlatmang.
    5. Faqat foydalanuvchi takrorlanishga aniq ishora qilgan taqdirdagina RRULE yaratish.
    6. Hodisaga asoslanib, bir nechta tegishli teglarni taklif qilish (masalan, ["ish", "shaxsiy", "salomatlik"]).

    Yakuniy javobdagi barcha matn o'zbek tilida ekanligiga ishonch hosil qiling.
    - Hech narsani tushuntirmang, shunchaki JSON obyektini qaytaring.

    QAT'IY JSON obyekti formatida javob bering:
    {{
      "event_name": "Hodisaning o'zbek tilidagi qisqa nomi",
      "event_description": "Hodisaning o'zbek tilidagi qisqacha tavsifi",
      "date": "YYYY-MM-DD formati. Takrorlanadigan hodisalar uchun bu birinchi sanasi.",
      "time": "HH:MM:SS 24 soatlik format.",
      "type": "'one_time' yoki 'recurring' ('bir martalik' yoki 'takrorlanuvchi')",
      "rrule": "Agar takrorlanuvchi bo'lsa, yaroqli iCalendar RRULE qatori, aks holda null",
      "tags": ["O'zbek", "tilidagi", "tegishli", "teglar", "massivi"],
      "status": "'success' (muvaffaqiyatli), agar hodisa tushunarli bo'lsa, yoki 'clarification_needed' (aniqlashtirish kerak), agar sana/vaqt noaniq bo'lsa."
    }}

    Foydalanuvchi xabari:
    \"{text}\"

    Faqat JSON javobini qaytaring. Qo'shimcha tushuntirishlarsiz.
    """


def prompt_in_russian(current_date_str, timezone_info, text):
    return f"""
    Вы — интеллектуальный помощник по планированию. Пользователь написал сообщение на русском языке. Ваша задача:

    1. Проанализировать сообщение для извлечения информации о событии.
    2. Понять и интерпретировать нечеткие или относительные временные выражения, такие как: "завтра", "каждый день", "через час", "в 8 вечера".
    3. Преобразовать все временные и датные выражения в точный формат, используя текущую дату: {current_date_str} {timezone_info}.
    4. Четко различать:
       - Разовые события: например, "через две минуты", "через час", "завтра".
       - Повторяющиеся события: например, "каждый понедельник", "еженедельно", "каждый месяц".
       - Если пользователь НЕ указывает конкретное время, по умолчанию использовать 08:00:00 (8 утра по местному времени).
       - НЕ использовать 00:00:00 по умолчанию, если пользователь явно не указал "в полночь".
    5. Генерировать RRULE только в том случае, если пользователь явно указывает на повторение.
    6. Предложить несколько релевантных тегов на основе события (например, ["работа", "личное", "здоровье"]).

    Наконец, убедитесь, что весь текст в вашем ответе на русском языке.
    - Ничего не объясняйте, просто верните JSON-объект.

    Отвечайте СТРОГО в формате JSON-объекта:
    {{
      "event_name": "Краткое название события на русском языке",
      "event_description": "Краткое описание события на русском языке",
      "date": "Формат YYYY-MM-DD. Для повторяющихся событий это дата первого вхождения.",
      "time": "Формат HH:MM:SS (24-часовой).",
      "type": "'one_time' или 'recurring' ('разовое' или 'повторяющееся')",
      "rrule": "Действительная строка iCalendar RRULE для повторяющихся событий, иначе null",
      "tags": ["Массив", "релевантрых", "тегов", "на", "русском", "языке"],
      "status": "'success' (успех), если событие понятно, или 'clarification_needed' (нужно уточнение), если дата/время неоднозначны."
    }}

    Сообщение пользователя:
    \"{text}\"

    Возвращайте только JSON-ответ. Без объяснений и лишних комментариев.
    """
