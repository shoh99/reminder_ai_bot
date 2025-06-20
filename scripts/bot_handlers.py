import tempfile
import os
import uuid
import logging

from scripts import database_crud as db

from datetime import datetime
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode

from sqlalchemy.orm import sessionmaker, Session
from scripts.dependincies import BotDependencies
from utils.utils import convert_to_json

# Setup logger
logger = logging.getLogger(__name__)

SESSION_FACTORY = None


def share_phone_button():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Share your phone number ☎️", request_contact=True)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def get_main_buttons():
    builder = ReplyKeyboardBuilder()
    builder.button(text="List Reminders")
    builder.button(text="Cancel Reminders")
    builder.button(text="Help")
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)


@asynccontextmanager
async def get_db_session(session_factory: sessionmaker) -> Session:
    session = session_factory()
    try:
        yield session
    except Exception as e:
        logger.error(f"Database session error: {e}")
        session.rollback()
        raise
    finally:
        session.close()


async def send_reminder(bot_token: str, chat_id: int, event_name: str,
                        event_description: str, job_id: str):
    """
    This function is called by the scheduler. It creates a temporary bot instance to send the message.
    """
    logger.info(f"Executing job {job_id} to send reminder to chat {chat_id}")
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        reminder_text = (
            f"🔔 <b>Reminder:</b> {event_name}\n"
            f"<b>Details:</b> {event_description}\n"
        )
        await bot.send_message(chat_id=chat_id, text=reminder_text, reply_markup=get_main_buttons())

        async with get_db_session(SESSION_FACTORY) as session:
            db.update_event_status(session, job_id, "complete")

        logger.info(f"Successfully sent reminder for job {job_id}")

    except Exception as e:
        logger.error(f"Failed to execute reminder job {job_id}: {e}")
    finally:
        await bot.session.close()


class BotHandlers:
    def __init__(self, deps: BotDependencies):
        self.deps = deps

    async def _scheduler_reminder(self, chat_id: int, user_id: uuid.UUID, data: dict, reminder_time: datetime) -> bool:
        """Schedules a job and saves it to the db. Fixed to use direct function reference."""
        try:
            job_id = str(uuid.uuid4())

            self.deps.scheduler.add_job(
                send_reminder,
                'date',
                run_date=reminder_time,
                args=[
                    self.deps.bot.token,
                    chat_id,
                    data.get("event_name", "Untitled Event"),
                    data.get("event_description", "No details provided."),
                    job_id
                ],
                id=job_id
            )

            async with get_db_session(self.deps.session_factory) as session:
                tags = db.get_or_create_tags(session, data.get("tags", []))
                db.create_full_event(
                    session, user_id, data.get("event_name", "Untitled Event"),
                    data.get("event_description", "No details provided."),
                    reminder_time, job_id, data.get("type", "one-time"),
                    data.get("rrule"), tags
                )
            logger.info(f"Scheduled job {job_id} and saved to db")
            return True
        except Exception as e:
            logger.error(f"Schedule failed: {e}")
            return False

    async def _process_and_schedule(self, user_id: uuid.UUID, chat_id: int, data: dict, remind_time: datetime):
        status_message = await self.deps.bot.send_message(chat_id=chat_id, text="⏰ Scheduling your request...")
        try:
            if remind_time < datetime.now():
                await status_message.edit_text(text="Oops! That time is in the past. Please try a future time.")
                return

            if await self._scheduler_reminder(chat_id, user_id, data, remind_time):
                confirmation_message = (
                    f"<b>✅ Reminder Scheduled!</b>\n\nI will remind you to:\n"
                    f"<b>Event:</b> {data['event_name']}\n<b>On:</b> {remind_time.strftime('%A, %B %d at %I:%M %p')}"
                )
                await status_message.edit_text(text=confirmation_message)
            else:
                await status_message.edit_text(text="Sorry, I ran into an error trying to schedule that.")
        except Exception as e:
            logger.error(f"Error at processing and scheduling job: {e}")
            await status_message.edit_text(text="An unexpected error occurred during scheduling.")

    # --- Message and Callback Handlers as class methods ---
    async def start(self, message: Message):
        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, message.chat.id, message.from_user.first_name)

        welcome_text = (
            f"Hello, {message.from_user.first_name}! 🤖 I'm your Remind Me AI assistant.\n\n"
            "Just send me a text or voice message describing what you want to be reminded about and when!"
        )
        if not user or not user.phone_number:
            await message.answer(
                f"Hello {message.from_user.first_name}! Please share your phone number to get started.",
                reply_markup=share_phone_button())
        else:
            await message.answer(welcome_text, reply_markup=get_main_buttons())

    async def list_reminders(self, message: Message):
        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, message.chat.id, message.from_user.first_name)
            reminders = db.get_active_reminders_by_user(session, user.id)
        if not reminders:
            await message.answer("📝 You have no active reminders.", reply_markup=get_main_buttons())
            return
        response_text = f"📋 **Your Active Reminders ({len(reminders)}):**\n\n"
        for event in reminders:
            response_text += f"▪️{event.event_name}\n  - 🕐 {event.schedule.scheduled_time.strftime('%A, %b %d at %I:%M %p')}\n\n"
        await message.answer(response_text, parse_mode="Markdown", reply_markup=get_main_buttons())

    async def cancel_reminders_list(self, message: Message):
        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, message.chat.id, message.from_user.first_name)
            reminders = db.get_active_reminders_by_user(session, user.id)
        if not reminders:
            await message.answer("📝 You have no active reminders to cancel.", reply_markup=get_main_buttons())
            return
        builder = InlineKeyboardBuilder()
        for event in reminders:
            button_text = f"{event.event_name[:30]}.. - {event.schedule.scheduled_time.strftime('%m/%d %H:%M')}"
            builder.add(InlineKeyboardButton(text=button_text, callback_data=f"cancel_{event.schedule.job_id}"))
        builder.adjust(1)
        await message.answer("🗑️ **Select a reminder to cancel:**", reply_markup=builder.as_markup(),
                             parse_mode="Markdown")

    async def cancel_reminder_callback(self, callback: CallbackQuery):
        job_id = callback.data.split("_", 1)[1]
        async with get_db_session(self.deps.session_factory) as session:
            event = db.get_event_by_job_id(session, job_id)
            if not event:
                await callback.message.edit_text("This reminder may have already been cancelled.")
                return
            try:
                self.deps.scheduler.remove_job(job_id)
            except Exception as e:
                logger.warning(f"Job {job_id} not found in scheduler, might be already completed or removed: {e}")
            db.update_event_status(session, job_id=job_id, status="cancelled")
            await callback.message.edit_text(f"✅ **Reminder Cancelled**\n\n📋 {event.event_name}", parse_mode='Markdown')
        await callback.answer()

    async def get_user_contact(self, message: Message):
        async with get_db_session(self.deps.session_factory) as session:
            db.add_user_phone(session, message.chat.id, message.contact.phone_number)
        await message.answer("✅ Your phone number has been saved!", reply_markup=get_main_buttons())
        await self.start(message)

    async def handle_text_message(self, message: Message):
        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, message.chat.id, message.from_user.first_name)
        if not user or not user.phone_number:
            await message.answer("Please share your phone number first so I can assist you.",
                                 reply_markup=share_phone_button())
            return

        status_message = await message.reply("Analyzing your request...")
        response_text = self.deps.ai_manager.analyze_text(message.text)
        json_response = convert_to_json(response_text)

        if json_response and json_response.get("status") == "success":
            try:
                remind_time = datetime.strptime(f"{json_response['date']} {json_response['time']}", '%Y-%m-%d %H:%M:%S')
                await self._process_and_schedule(user.id, message.chat.id, json_response, remind_time)
            except (ValueError, TypeError, KeyError):
                await status_message.edit_text(
                    "I understood the event but struggled with the date or time format. Could you be more specific?")
        else:
            await status_message.edit_text("I couldn't quite understand that. Could you try rephrasing your reminder?")

    async def handle_voice_message(self, message: Message):
        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, message.chat.id, message.from_user.first_name)
        if not user or not user.phone_number:
            await message.answer("Please share your phone number first so I can assist you.",
                                 reply_markup=share_phone_button())
            return

        status_message = await message.reply("Heard you! Analyzing your voice message...")

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, f"{message.voice.file_id}.ogg")
            await self.deps.bot.download(message.voice, destination=file_path)

            response_text = self.deps.ai_manager.analyze_audio(file_path)
            json_response = convert_to_json(response_text)

            if json_response and json_response.get("status") == "success":
                try:
                    transcript = json_response.get('transcript', 'Unavailable')
                    event = json_response.get('event_description', 'Untitled Event')
                    date = json_response.get('date')
                    time = json_response.get('time')

                    remind_time = datetime.strptime(f"{date} {time}", '%Y-%m-%d %H:%M:%S')

                    response_text_confirmation = (
                        f"<b>Got it! Here's what I heard:</b>\n\n"
                        f"🗣 <b>Transcript:</b> “<i>{transcript}</i>”\n\n"
                        f"📝 <b>Event:</b> {event}\n"
                        f"📅 <b>Date:</b> {date}\n"
                        f"⏰ <b>Time:</b> {time}"
                    )
                    await message.answer(response_text_confirmation, reply_markup=get_main_buttons())
                    await self._process_and_schedule(user.id, message.chat.id, json_response, remind_time)
                except (ValueError, TypeError, KeyError):
                    await status_message.edit_text(
                        "I understood the event but struggled with the date or time format. Could you be more specific?")
            else:
                await status_message.edit_text(
                    "I couldn't quite understand that. Could you try rephrasing your reminder?")


def register_handlers(dp: Dispatcher, deps: BotDependencies):
    """
    Registers all handlers with proper dependency injection using a class-based approach.
    """
    handlers = BotHandlers(deps)
    global SESSION_FACTORY
    if SESSION_FACTORY is None:
        SESSION_FACTORY = deps.session_factory

    dp.message.register(handlers.start, Command("start", "help"))
    dp.message.register(handlers.start, F.text == "Help")
    dp.message.register(handlers.list_reminders, Command("list"))
    dp.message.register(handlers.list_reminders, F.text == "List Reminders")
    dp.message.register(handlers.cancel_reminders_list, Command("cancel"))
    dp.message.register(handlers.cancel_reminders_list, F.text == "Cancel Reminders")
    dp.message.register(handlers.get_user_contact, F.contact)
    # The general text handler must be last
    dp.message.register(handlers.handle_text_message, F.text)
    dp.message.register(handlers.handle_voice_message, F.voice)
    dp.callback_query.register(handlers.cancel_reminder_callback, F.data.startswith("cancel_"))
