import tempfile
import os
import json
import uuid
from datetime import datetime
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import InlineKeyboardMarkup, InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import sessionmaker
from ai_services import AIManager

import database_crud as db

_bot_instance: Bot = None
_SessionLocal: sessionmaker = None
_scheduler_instance: AsyncIOScheduler = None


def convert_to_json(text: str) -> Optional[dict]:
    """Safely converts a string to a JSON object."""
    try:
        if text is None:
            return None

        json_string = text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"Failed to convert text to JSON: {e}\nText was: {text}")
        return None


def share_phone_button():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Share your phone number ☎️", request_contact=True)
    return builder.as_markup(resize_keyboard=True)


def get_main_buttons():
    builder = ReplyKeyboardBuilder()
    builder.button(text="List Reminders")
    builder.button(text="Cancel Reminders")
    builder.button(text="Help")
    builder.adjust(1, 3)
    return builder.as_markup(resize_keyboard=True)


async def send_reminder(chat_id: int, event_name: str, event_description: str, job_id: str):
    print(f"Sending reminder for job {job_id} to chat {chat_id}")

    try:
        reminder = (
            f"🔔 <b>Reminder:</b> {event_name}\n"
            f"<b>Details:</b> {event_description}\n"
        )
        await _bot_instance.send_message(chat_id=chat_id, text=reminder)
        with _SessionLocal() as session:
            db.update_event_status(session, job_id, "complete")

    except Exception as e:
        print(f"Failed to execute reminder job {job_id}: {e}")


def register_handlers(dp: Dispatcher, ai_manager: AIManager, SessionLocal: sessionmaker, bot: Bot,
                      scheduler: AsyncIOScheduler):
    global _bot_instance, _SessionLocal, _scheduler_instance
    _bot_instance = bot
    _SessionLocal = SessionLocal
    _scheduler_instance = scheduler

    async def scheduler_reminder(chat_id: int, user_id: uuid.UUID, data: dict, reminder_time: datetime) -> bool:
        """schedules a job and saves it to the db"""
        try:
            job_id = str(uuid.uuid4())
            event_name = data["event_name"]
            event_description = data["event_description"]
            type = data["type"]
            rrule = data["rrule"]
            tags_str_list = data["tags"]

            scheduler.add_job(send_reminder, 'date', run_date=reminder_time,
                              args=[chat_id, event_name, event_description, job_id], id=job_id)

            with SessionLocal() as session:

                tags = db.get_or_create_tags(session, tags_str_list)
                db.create_full_event(session, user_id, event_name, event_description, reminder_time, job_id, type,
                                     rrule, tags)
                print(f"Scheduled job {job_id} and saved to db")
                return True

        except Exception as e:
            print(f"Scheduled failed: {e}")
            return False

    async def process_and_schedule(user_id: uuid.UUID, chat_id: int, data: dict, remind_time: datetime):
        await bot.send_message(chat_id=chat_id, text="⏰ Scheduling your request...")
        try:
            if remind_time < datetime.now():
                await bot.send_message(chat_id=chat_id,
                                       text="Oops! That time is in the past. Please try a future time.")
                return

            if await scheduler_reminder(chat_id, user_id, data, remind_time):
                confirmation_message = (
                    f"<b>✅ Reminder Scheduled!</b>\n\nI will remind you to:\n"
                    f"<b>Event:</b> {data['event_name']}\n<b>On:</b> {remind_time.strftime('%A, %B %d at %I:%M %p')}"
                )
                await bot.send_message(chat_id=chat_id, text=confirmation_message)
            else:
                await bot.send_message(chat_id=chat_id, text="Sorry, I ran into an error trying to schedule that.")

        except Exception as e:
            print(f"Error at processing and scheduling job: {e}")
            return

    @dp.message(Command("start", "help"))
    async def start_handler(message: Message):
        with SessionLocal() as session:
            logged_user = db.get_or_create_user(session, message.chat.id, message.from_user.first_name)

        welcome_text = (
            f"Hello, {message.from_user.first_name}! 🤖 I'm your Remind Me AI assistant.\n\n"
            "Just send me a text or voice message describing what you want to be reminded about and when!\n\n"
            "**Commands:**\n"
            "/start - Show this message\n"
            "/list - View your active reminders\n"
            "/cancel - Cancel a reminder"
        )
        if not logged_user.phone_number:
            await message.answer(f"Hello {message.from_user.first_name}! Please share your contacts first.",
                                 reply_markup=share_phone_button())
        else:
            await message.answer(welcome_text, parse_mode='Markdown', reply_markup=get_main_buttons())

    @dp.message(F.contact)
    async def get_user_contact(message: Message):
        chat_id = message.chat.id
        phone = message.contact.phone_number

        with SessionLocal() as session:
            db.add_user_phone(session, chat_id, phone)

        await message.answer("✅Saved phone number", reply_markup=get_main_buttons())

    @dp.message(F.text)
    async def handle_text_message(message: Message):
        with SessionLocal() as session:
            user = db.get_or_create_user(session, message.chat.id, message.from_user.first_name)
            if not user.phone_number:
                await message.answer("Please share your contacts first.", reply_markup=share_phone_button())
                return

        await message.answer("Analyzing your request...")
        response_text = ai_manager.analyze_text(message.text)
        json_response = convert_to_json(response_text)
        print(json_response)
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
                await process_and_schedule(user_id=user.id, chat_id=message.chat.id, data=json_response,
                                           remind_time=remind_time)
            except (ValueError, TypeError):
                await message.answer(
                    "I understood the event but struggled with the date or time format. Could you be more specific?")
        else:
            await message.answer("I couldn't quite understand that. Could you try rephrasing your reminder?")

    @dp.message(F.voice)
    async def handle_voice_message(message: Message):
        with SessionLocal() as session:
            user = db.get_or_create_user(session, message.chat.id, message.from_user.first_name)
            if not user.phone_number:
                await message.answer("Please share your contacts first.", reply_markup=share_phone_button())
                return

        await message.answer("Heard you! Analyzing your voice message...")
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, f"{message.voice.file_id}.ogg")
            await bot.download(message.voice, destination=file_path)

            response_text = ai_manager.analyze_audio(file_path)
            json_response = convert_to_json(response_text)
            print(json_response)

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
                    await process_and_schedule(user.id, message.chat.id, json_response, remind_time)
                except (ValueError, TypeError):
                    await message.answer(
                        "I understood the event but struggled with the date or time format from your audio. Could you be more specific?")
            else:
                await message.answer(
                    "I couldn't understand the audio. Could you try speaking more clearly or sending a text message?")

        # @dp.message(Command("list"))
    # async def list_reminders_handler(message: Message):
    #     with SessionLocal() as session:
    #         user = db.get_or_create_user(session, message.chat.id, message.from_user.first_name)
    #         reminders = db.get_active_reminders_by_user(session, user.id)
    #
    #         if not reminders:
    #             await message.answer("📝 You have no active reminders.")
    #             return
    #
    #         response_text = f"📋 **Your Active Reminders ({len(reminders)}):**\n\n"
    #         for event in reminders:
    #             response_text += f"▪️{event.event_name}\n"
    #             response_text += f"  - 🕐 {event.schedule.scheduled_time.strftime('%A, %b %d at %I:%M %p')}\n\n"
    #
    #         await message.answer(response_text, parse_mode="Markdown")
