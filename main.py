import logging
import os
import json
import sqlite3
import tempfile
import asyncio
import textwrap
import dotenv

from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import InlineKeyboardMarkup, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from typing import Optional
from google import genai
from google.cloud import speech
from google.genai import types

dotenv.load_dotenv()


TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DB_FILE = os.getenv('DB_FILE')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Global Bot and Dispatcher Initialization ---
# The bot and dispatcher are initialized here to be accessible globally.
# This is key to solving the APScheduler pickling error.
bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


# --- Database Setup ---
def init_db():
    # Using your updated schema with the 'transcript' column
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                event_description TEXT NOT NULL,
                transcript TEXT NOT NULL,
                reminder_time DATETIME NOT NULL,
                job_id TEXT NOT NULL UNIQUE
            )
        ''')
        conn.commit()
    logger.info("Database initialized.")


# --- AI & Speech-to-Text Initialization ---
try:
    ai_model = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    logger.error(f"Failed to configure Gemini AI: {e}")
    ai_model = None


# --- Helper Functions ---
def convert_to_json(text: str) -> Optional[dict]:
    """Safely converts a string to a JSON object."""
    try:
        # The AI might wrap the JSON in markdown backticks
        json_string = text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except (json.JSONDecodeError, TypeError) as e:
        logger.error(f"Failed to convert text to JSON: {e}\nText was: {text}")
        return None


# --- AI Analysis Functions ---
async def analyze_text_with_ai(text: str) -> Optional[str]:
    """Analyzes text to extract reminder details using Gemini."""
    if not ai_model: return None
    current_date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prompt = f"""
You are an intelligent scheduling assistant. Analyze the user's text based on the current date: {current_date_str}.
Interpret fuzzy dates (e.g., "tomorrow", "next Monday") and extract the event, exact date, and time.
Respond strictly with a JSON object in the format:
{{
  "event_description": "a concise description of the event",
  "date": "YYYY-MM-DD",
  "time": "HH:MM:SS",
  "status": "success" or "clarification_needed"
}}
User's text: "{text}"
"""
    try:
        response = ai_model.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return response.text
    except Exception as e:
        logger.error(f"Error during AI text analysis: {e}")
        return None


async def analyze_voice_with_ai(voice_file_path: str) -> Optional[str]:
    """Transcribes and analyzes audio to extract reminder details using Gemini."""
    if not ai_model: return None
    current_date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prompt = f"""
You are a highly intelligent scheduling assistant. The user has provided an audio recording. Your task is to:
1. Accurately transcribe the spoken content.
2. Identify and extract the scheduled event from the transcript.
3. Interpret fuzzy or relative dates (e.g., "tomorrow", "next Monday") based on the current date: {current_date_str}, and convert them to exact "YYYY-MM-DD" and "HH:MM:SS" values.
4. If the date or time is ambiguous or missing, set the "status" field to "clarification_needed".
Respond strictly with a JSON object in the format:
{{
  "transcript": "the full transcript of the user's audio",
  "event_description": "a concise description of the event",
  "date": "YYYY-MM-DD",
  "time": "HH:MM:SS",
  "status": "success" or "clarification_needed"
}}
"""
    try:
        with open(voice_file_path, 'rb') as f:
            audio_bytes = f.read()

        response = ai_model.models.generate_content(
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
        logger.error(f"Error during AI voice analysis: {e}")
        return None


# --- Scheduler & Reminder Logic ---
async def send_reminder(chat_id: int, event: str, job_id: str):
    """The function called by the scheduler. It uses the global `bot` object."""
    logger.info(f"Sending reminder for job {job_id} to chat {chat_id}")
    try:
        await bot.send_message(chat_id=chat_id, text=f"🔔 <b>Reminder:</b>\n{event}")
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("DELETE FROM reminders WHERE job_id = ?", (job_id,))
    except Exception as e:
        logger.error(f"Failed to execute reminder job {job_id}: {e}")


async def schedule_reminder(scheduler: AsyncIOScheduler, chat_id: int, transcript: str, event: str,
                            remind_time: datetime) -> bool:
    """Schedules a job and saves it to the database."""
    job_id = f"reminder_{chat_id}_{int(remind_time.timestamp())}"
    try:
        # **THE FIX**: `bot` is no longer passed in `args`.
        scheduler.add_job(send_reminder, 'date', run_date=remind_time, args=[chat_id, event, job_id], id=job_id)
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                "INSERT INTO reminders (chat_id, event_description, transcript, reminder_time, job_id) VALUES (?, ?, ?, ?, ?)",
                (chat_id, event, transcript, remind_time, job_id)
            )
        logger.info(f"Scheduled job {job_id} and saved to DB.")
        return True
    except Exception as e:
        logger.error(f"Error scheduling job id: {job_id}, {e}")
        return False


# --- Core Logic ---
async def process_and_schedule(scheduler: AsyncIOScheduler, chat_id: int, transcript: str, event: str,
                               remind_time: datetime):
    """Processes parsed data and schedules the reminder."""
    await bot.send_message(chat_id=chat_id, text="⏰ Scheduling your request...")
    if remind_time < datetime.now():
        await bot.send_message(chat_id=chat_id, text="Oops! That time is in the past. Please try a future time.")
        return

    if await schedule_reminder(scheduler, chat_id, transcript, event, remind_time):
        confirmation_message = (
            f"<b>✅ Reminder Scheduled!</b>\n\nI will remind you to:\n"
            f"<b>Event:</b> {event}\n<b>On:</b> {remind_time.strftime('%A, %B %d at %I:%M %p')}"
        )
        await bot.send_message(chat_id=chat_id, text=confirmation_message)
    else:
        await bot.send_message(chat_id=chat_id, text="Sorry, I ran into an error trying to schedule that.")


# --- Aiogram Handlers ---
@dp.message(Command("start"))
async def start_handler(message: Message):
    user_name = message.from_user.first_name
    welcome_text = f"""
        Hello, {user_name}! 🤖 I'm your Remind Me AI assistant.
        
        **Commands:**
        /start - Show this welcome message
        /list - View your active reminders  
        /cancel - Cancel a reminder
        /help - Get detailed help
        
        **How to use:**
        Just send me a text or voice message describing what you want to be reminded about and when!
        
        Examples:
        • "Remind me to call mom tomorrow at 3 PM"
        • "Meeting with John next Friday at 10 AM"
        • "Take medication daily at 8 AM"
    """
    await message.answer(welcome_text)


@dp.message(Command("help"))
async def help_handler(message: Message):
    """Detailed help message"""
    help_text = """
        🤖 **Remind Me AI - Complete Guide**
        
        **🎯 Basic Usage:**
        Just tell me what you want to be reminded about and when!
        
        **📝 Text Examples:**
        • "Remind me to call mom tomorrow at 3 PM"
        • "Meeting with John next Friday at 10 AM"  
        • "Take medication every day at 8 AM"
        • "Dentist appointment on 2024-12-25 at 14:30"
        
        **🎤 Voice Messages:**
        Send voice messages for natural language processing!
        
        **⚙️ Commands:**
        • `/start` - Welcome message
        • `/timezone [timezone]` - Set your timezone
        • `/list` - View active reminders
        • `/cancel` - Cancel reminders
        • `/help` - This help message
        
        **🌍 Timezone Support:**
        Set your timezone with `/timezone America/New_York`
        All times will be converted to your local timezone.
        
        **📅 Date Formats Supported:**
        • 2024-12-25 (YYYY-MM-DD)
        • 25/12/2024 (DD/MM/YYYY)
        • 12/25/2024 (MM/DD/YYYY)
        
        **🕐 Time Formats Supported:**
        • 14:30 (24-hour)
        • 2:30 PM (12-hour with AM/PM)
        • 14:30:00 (with seconds)
        
        **🔄 Natural Language:**
        • "tomorrow at 3 PM"
        • "next Monday at 9 AM"
        • "this Friday evening"
        
        Need more help? Just ask me anything!
    """
    await message.answer(help_text, parse_mode='Markdown')


@dp.message(Command("list"))
async def list_reminders_handler(message: Message):
    """list all active reminders for the user."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, event_description, reminder_time, job_id 
                    FROM reminders
                    WHERE chat_id = ?
                    ORDER BY reminder_time ASC""",
                (message.chat.id,)
            )

            reminders = cursor.fetchall()
            print(reminders)
            if not reminders:
                await message.answer("📝 You have no active reminders.")
                return

            response_text = f"📋 **Your Active Reminders ({len(reminders)}):**\n\n"

            for i, (reminder_id, event, reminder_time_str, job_id) in enumerate(reminders, 1):
                reminder_time = datetime.fromisoformat(reminder_time_str)
                time_diff = reminder_time - datetime.now()
                if time_diff.days > 0:
                    time_left = f"in {time_diff.days} days"
                elif time_diff.seconds > 3600:
                    hours = time_diff.seconds // 3600
                    time_left = f"in {hours} hours"
                else:
                    minutes = time_diff.seconds // 60
                    time_left = f"in {minutes} minutes"

                response_text += (
                    f"**{i}.** {event}\n"
                    f"🕐 {reminder_time.strftime('%A, %B %d at %I:%M %p')} ({time_left})\n"
                    f"🆔 ID: `{reminder_id}`\n\n"
                )

            await message.answer(response_text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error listing reminders: {e}")
        await message.answer("❌ Error retrieving your reminders. Please try again.")


@dp.message(Command("cancel"))
async def cancel_start_handler(message: Message):
    """show cancellation options"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, event_description, reminder_time 
                    FROM reminders
                    WHERE chat_id = ?
                    ORDER BY reminder_time ASC
                    LIMIT 10""",
                (message.chat.id,)
            )
            reminders = cursor.fetchall()

            if not reminders:
                await message.answer("📝 You have no active reminders.")
                return

            builder = InlineKeyboardBuilder()

            for reminder_id, event, reminder_time_str in reminders:
                reminder_time = datetime.fromisoformat(reminder_time_str)
                button_text =  f"{event[:30]}... - {reminder_time.strftime('%m/%d %H:%M')}"
                if len(event) <= 30:
                    button_text = f"{event} - {reminder_time.strftime('%m/%d %H:%M')}"

                builder.add(InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"cancel_{reminder_id}"
                ))

            builder.adjust(1)

            await message.answer(
                "🗑️**Select a reminder to cancel:**",
                reply_markup=builder.as_markup(),
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Error at showing cancellation options: {e}")
        await message.answer(f"❌Error retrieving your reminders. Please try again.")


@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_reminder_callback(callback: CallbackQuery, scheduler: AsyncIOScheduler):
    """Handle reminder cancellation"""
    try:
        reminder_id = int(callback.data.split("_")[1])
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT job_id, event_description FROM reminders WHERE id = ? AND chat_id = ?",
                (reminder_id, callback.message.chat.id)
            )

            result = cursor.fetchone()
            if not result:
                await callback.answer("❌ Reminder not found or already cancelled.")
                return

            job_id, event_description = result

            # remove from scheduler
            try:
                scheduler.remove_job(job_id)
            except Exception as e:
                logger.error(f"Job {job_id} not found in scheduler: {e}")

            # update db
            cursor.execute(
                "DELETE FROM reminders WHERE id = ?",
                (reminder_id,)
            )
            conn.commit()

            await callback.message.edit_text(
                f"✅ **Reminder Cancelled**\n\n📋 {event_description}",
                parse_mode='Markdown'
            )

    except Exception as e:
        logger.error(f"Error cancelling reminder: {e}")
        await callback.answer("❌ Error cancelling reminder.")


@dp.message(F.text)
async def handle_text_message(message: Message, scheduler: AsyncIOScheduler):
    if not ai_model:
        await message.answer("I'm sorry, my AI brain is currently offline. Please try again later.")
        return

    await message.answer("Analyzing your request...")
    response_text = await analyze_text_with_ai(message.text)
    json_response = convert_to_json(response_text)

    if json_response and json_response.get("status") == "success":
        event = json_response.get('event_description', 'Untitled Event')
        date = json_response.get('date')
        time = json_response.get('time')

        try:
            remind_time = datetime.strptime(f"{date} {time}", '%Y-%m-%d %H:%M:%S')
            response_text_confirmation = (
                f"<b>Got it! Here's what I understood:</b>\n\n"
                f"📝 <b>Event:</b> {event}\n"
                f"📅 <b>Date:</b> {date}\n"
                f"⏰ <b>Time:</b> {time}"
            )
            await message.answer(response_text_confirmation)
            # Use message.text as the "transcript" for text messages
            await process_and_schedule(scheduler, message.chat.id, message.text, event, remind_time)
        except (ValueError, TypeError):
            await message.answer(
                "I understood the event but struggled with the date or time format. Could you be more specific?")
    else:
        await message.answer("I couldn't quite understand that. Could you try rephrasing your reminder?")


@dp.message(F.voice)
async def handle_voice_message(message: Message, scheduler: AsyncIOScheduler):

    await message.answer("Heard you! Analyzing your voice message...")
    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = os.path.join(temp_dir, f"{message.voice.file_id}.ogg")
        await bot.download(message.voice, destination=file_path)

        response_text = await analyze_voice_with_ai(file_path)
        json_response = convert_to_json(response_text)

        if json_response and json_response.get("status") == "success":
            transcript = json_response.get('transcript', 'Unavailable')
            event = json_response.get('event_description', 'Untitled Event')
            date = json_response.get('date')
            time = json_response.get('time')

            try:
                remind_time = datetime.strptime(f"{date} {time}", '%Y-%m-%d %H:%M:%S')
                response_text_confirmation = (
                    f"<b>Got it! Here's what I heard:</b>\n\n"
                    f"🗣 <b>Transcript:</b> “<i>{transcript}</i>”\n\n"
                    f"📝 <b>Event:</b> {event}\n"
                    f"📅 <b>Date:</b> {date}\n"
                    f"⏰ <b>Time:</b> {time}"
                )
                await message.answer(response_text_confirmation)
                await process_and_schedule(scheduler, message.chat.id, transcript, event, remind_time)
            except (ValueError, TypeError):
                await message.answer(
                    "I understood the event but struggled with the date or time format from your audio. Could you be more specific?")
        else:
            await message.answer(
                "I couldn't understand the audio. Could you try speaking more clearly or sending a text message?")


# --- Main Execution Logic ---
async def main():
    if "YOUR_TELEGRAM_BOT_TOKEN_HERE" in TELEGRAM_BOT_TOKEN or "YOUR_GEMINI_API_KEY_HERE" in GEMINI_API_KEY:
        logger.error("IMPORTANT: Please set your TELEGRAM_BOT_TOKEN and GEMINI_API_KEY environment variables.")
        return

    init_db()

    # Using your persistent scheduler setup
    jobstores = {'default': SQLAlchemyJobStore(url=f'sqlite:///{DB_FILE}')}
    scheduler = AsyncIOScheduler(jobstores=jobstores, timezone="Asia/Seoul")

    scheduler.start()
    logger.info("Persistent scheduler started.")

    # Pass the scheduler instance to handlers that need it
    dp['scheduler'] = scheduler

    logger.info("Bot is starting...")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
