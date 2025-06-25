import tempfile
import os
import uuid
import logging
import pytz
from scripts import database_crud as db

from datetime import datetime
from contextlib import asynccontextmanager
from dateutil.rrule import rrulestr, MINUTELY, HOURLY, DAILY, WEEKLY, MONTHLY
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode

from sqlalchemy.orm import sessionmaker, Session
from scripts.dependincies import BotDependencies
from scripts.models import Users
from utils.utils import convert_to_json, create_human_readable_rule, safe_timezone_convert

SESSION_FACTORY = None


def get_timezone_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="🇺🇿 Uzbekistan (Tashkent)", callback_data="tz_Asia/Tashkent"),
        InlineKeyboardButton(text="🇰🇷 South Korea (Seoul)", callback_data="tz_Asia/Seoul")
    )
    builder.adjust(1)
    return builder.as_markup()


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
        logging.error(f"Database session error: {e}")
        session.rollback()
        raise
    finally:
        session.close()


async def send_reminder(bot_token: str, chat_id: int, event_name: str,
                        event_description: str, job_id: str):
    """
    This function is called by the scheduler. It creates a temporary bot instance to send the message.
    """
    logging.info(f"Executing job {job_id} to send reminder to chat {chat_id}")
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        reminder_text = (
            f"🔔 <b>Reminder:</b> {event_name}\n"
            f"<b>Details:</b> {event_description}\n"
        )
        await bot.send_message(chat_id=chat_id, text=reminder_text, reply_markup=get_main_buttons())

        async with get_db_session(SESSION_FACTORY) as session:
            event = db.get_event_by_job_id(session, job_id)
            status = "complete"

            if not event:
                logging.warning(f"Could not find event for job {job_id} after sending reminder.")
                return

            if event.schedule and event.schedule.rrule:
                try:
                    utc = pytz.utc
                    user_tz = pytz.timezone(event.user.timezone)
                    # get current time in utc
                    now_utc = datetime.now(utc)

                    # get original scheduled time in user's timezone
                    if event.schedule.scheduled_time.tzinfo is None:
                        scheduled_time_utc = utc.localize(event.schedule.scheduled_time)
                    else:
                        scheduled_time_utc = event.schedule.scheduled_time.astimezone(utc)

                    # convert to user timezone for rrule calculation
                    scheduled_time_local = scheduled_time_utc.astimezone(user_tz)
                    # parse rrule with local time as dtstart
                    rule = rrulestr(event.schedule.rrule, dtstart=scheduled_time_local)

                    # find next occurrence after current time in user timezone
                    now_local = now_utc.astimezone(user_tz)
                    next_run_local = rule.after(now_local)

                    # next_run = rule.after(now_aware)

                    if next_run_local:
                        next_run_utc = next_run_local.astimezone(utc)
                        status = "ongoing"
                        db.update_schedule_run_date(session, job_id, next_run_utc)
                        logging.info(
                            f"Next run for job {job_id} scheduled at {next_run_utc} UTC ({next_run_utc} {user_tz.zone})")
                    else:
                        status = "complete"
                        logging.info(f"Recurring event {job_id} has finished its cycle.")
                except Exception as e:
                    logging.error(f"Error calculating next run time for job {job_id}: {e}")

            db.update_event_status(session, job_id, status)

        logging.info(f"Successfully sent reminder for job {job_id}")

    except Exception as e:
        logging.error(f"Failed to execute reminder job {job_id}: {e}")
    finally:
        await bot.session.close()


class BotHandlers:
    def __init__(self, deps: BotDependencies):
        self.deps = deps

    async def _scheduler_reminder(self, chat_id: int, user_id: uuid.UUID, user_timezone: pytz, data: dict,
                                  reminder_time_utc: datetime) -> bool:
        """Schedules a job and saves it to the db. Fixed to use direct function reference."""
        try:
            job_id = str(uuid.uuid4())
            rrule_str = data.get("rrule")

            # ensure reminder_time_utc is timezone-aware
            if reminder_time_utc.tzinfo is None:
                reminder_time_utc = pytz.utc.localize(reminder_time_utc)
            elif reminder_time_utc.tzinfo != pytz.utc:
                reminder_time_utc = reminder_time_utc.astimezone(pytz.utc)

            job_kwargs = {
                'id': job_id,
                'args': [
                    self.deps.bot.token,
                    chat_id,
                    data.get("event_name", "Untitled Event"),
                    data.get("event_description", "No details provided."),
                    job_id
                ]
            }
            if rrule_str:
                logging.info(f"Parsing rrule '{rrule_str}' to create a recurring job.")

                # convert to user timezone for rrule parsing
                reminder_time_local = reminder_time_utc.astimezone(user_timezone)
                rule = rrulestr(rrule_str, dtstart=reminder_time_local)

                # Logic to decide between 'interval' and 'cron' triggers
                # If an interval is specified, use the 'interval' trigger.
                if rule._interval > 1:
                    job_kwargs['trigger'] = 'interval'
                    interval_kwargs = {'start_date': reminder_time_utc}  # APScheduler expects UTC
                    if rule._freq == MINUTELY:
                        interval_kwargs['minutes'] = rule._interval
                    elif rule._freq == HOURLY:
                        interval_kwargs['hours'] = rule._interval
                    elif rule._freq == DAILY:
                        interval_kwargs['days'] = rule._interval
                    elif rule._freq == WEEKLY:
                        interval_kwargs['weeks'] = rule._interval
                    job_kwargs.update(interval_kwargs)
                else:
                    # If no interval, use the more specific 'cron' trigger with timezone specification.
                    job_kwargs['trigger'] = 'cron'
                    cron_args = {
                        'hour': reminder_time_local.hour,  # user local time for cron
                        'minute': reminder_time_local.minute,
                        'start_date': reminder_time_utc,  # but start date in utc
                        'timezone': user_timezone  # specify timezone for cron
                    }

                    if rule._freq == WEEKLY:
                        day_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
                        cron_args['day_of_week'] = ','.join([day_map[d] for d in rule._byweekday])
                    elif rule._freq == MONTHLY:
                        cron_args['day'] = ','.join(map(str, rule._bymonthday))
                    # For DAILY, just hour/minute is needed, which is already set.
                    job_kwargs.update(cron_args)
            else:
                # Fallback for one-time jobs
                job_kwargs['trigger'] = 'date'
                job_kwargs['run_date'] = reminder_time_utc  # APScheduler expects UTC

            self.deps.scheduler.add_job(
                send_reminder,
                **job_kwargs
            )

            async with get_db_session(self.deps.session_factory) as session:
                tags = db.get_or_create_tags(session, data.get("tags", []))
                db.create_full_event(
                    session, user_id, data.get("event_name", "Untitled Event"),
                    data.get("event_description", "No details provided."),
                    reminder_time_utc, job_id, data.get("type"),
                    data.get("rrule"), tags
                )
            logging.info(f"Scheduled job {job_id} and saved to db")
            return True
        except Exception as e:
            logging.error(f"Schedule failed: {e}")
            return False

    async def _process_and_schedule(self, user: Users, chat_id: int, data: dict, remind_time_naive: datetime):
        status_message = await self.deps.bot.send_message(chat_id=chat_id, text="⏰ Scheduling your request...")
        try:
            user_tz = pytz.timezone(user.timezone)
            # localize the naive datetime to user's timezone
            remind_time_local = user_tz.localize(remind_time_naive)
            # convert to utc for internal processing
            remind_time_utc = remind_time_local.astimezone(pytz.utc)
            # compare timezone-aware datetimes
            now_utc = datetime.now(pytz.utc)
            if remind_time_utc <= now_utc:
                await status_message.edit_text(text="Oops! That time is in the past. Please try a future time.")
                return

            if await self._scheduler_reminder(chat_id, user.id, user_tz, data, remind_time_utc):
                display_time_str = remind_time_local.strftime('%A, %B, %d at %I:%M %p %Z')
                if data.get("rrule"):
                    schedule_text = create_human_readable_rule(data["rrule"], remind_time_local)
                else:
                    schedule_text = f"On: {display_time_str}"

                confirmation_message = (
                    f"<b>✅ Reminder Scheduled!</b>\n\nI will remind you to:\n"
                    f"<b>Event:</b> {data['event_name']}\n<b>{schedule_text}</b>"
                )
                await status_message.edit_text(text=confirmation_message)
            else:
                await status_message.edit_text(text="Sorry, I ran into an error trying to schedule that.")
        except Exception as e:
            logging.error(f"Error at processing and scheduling job: {e}")
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
            elif user.timezone == "UTC":
                await message.answer("Please select your timezone to continue:", reply_markup=get_timezone_keyboard())
            else:
                await message.answer(welcome_text, reply_markup=get_main_buttons())

    async def select_timezone(self, callback: CallbackQuery):
        """Handle the user's timezone selection"""
        try:
            await self.deps.bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
        except Exception as e:
            logging.error("Error at message deletion")

        try:
            user_tz = callback.data.split("tz_")[1]
            async with get_db_session(self.deps.session_factory) as session:
                if db.update_user_timezone(session, callback.message.chat.id, user_tz):
                    await callback.message.answer(f"You can now send me a reminder request.",
                                                  reply_markup=get_main_buttons())
                else:
                    await callback.message.reply("Sorry, something went wrong. Please try again.")
        except Exception as e:
            logging.error(f"Error setting timezone: {e}")
            await callback.message.edit_text("Sorry, something went wrong. Please try again.")
        finally:
            await callback.answer()

    async def list_reminders(self, message: Message):
        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, message.chat.id, message.from_user.first_name)
            reminders = db.get_active_reminders_by_user(session, user.id)
            user_tz = pytz.timezone(user.timezone)

        if not reminders:
            await message.answer("📝 You have no active reminders.", reply_markup=get_main_buttons())
            return
        response_text = f"📋 **Your Active Reminders ({len(reminders)}):**\n\n"

        for event in reminders:
            response_text += f"▪️{event.event_name}\n"
            scheduled_time_local = safe_timezone_convert(
                event.schedule.scheduled_time,
                user_tz,
                pytz.utc
            )
            try:
                if event.schedule.rrule:
                    rule_text = create_human_readable_rule(event.schedule.rrule, scheduled_time_local)
                    response_text += f"  - 🕐 Recurring: {rule_text}\n\n"
                else:
                    response_text += f"  - 🕐 {scheduled_time_local.strftime('%A, %b %d at %I:%M %p %Z')}\n\n"
            except Exception as e:
                logging.error(f"List reminder error: {e}, event rrule: {event.schedule.rrule}")
        try:
            await self.deps.bot.delete_message(chat_id=message.chat.id, message_id=message.message_id - 1)
        except Exception as e:
            logging.error(f"Error at deleting message. {e}")

        await message.answer(response_text, parse_mode="Markdown", reply_markup=get_main_buttons())

    async def cancel_reminders_list(self, message: Message):
        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, message.chat.id, message.from_user.first_name)
            reminders = db.get_active_reminders_by_user(session, user.id)

            try:
                await self.deps.bot.delete_message(chat_id=message.chat.id, message_id=message.message_id - 1)
            except Exception as e:
                logging.error(f"Error at deleting message. {e}")

        if not reminders:
            await message.answer("📝 You have no active reminders to cancel.", reply_markup=get_main_buttons())
            return
        builder = InlineKeyboardBuilder()
        user_tz = pytz.timezone(user.timezone)

        for event in reminders:
            scheduled_time_local = event.schedule.scheduled_time.replace(tzinfo=pytz.utc).astimezone(user_tz)
            if event.schedule.rrule:
                schedule_desc = create_human_readable_rule(event.schedule.rrule, scheduled_time_local)
            else:
                schedule_desc = scheduled_time_local.strftime('%b %d at %I:%M %p')

            button_text = f"{event.event_name[:30]}.. - {schedule_desc[:30]}"
            builder.add(InlineKeyboardButton(text=button_text, callback_data=f"cancel_{event.schedule.job_id}"))
        builder.adjust(1)

        await message.answer("Here are the reminders", reply_markup=get_main_buttons())
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
                logging.warning(f"Job {job_id} not found in scheduler, might be already completed or removed: {e}")
            db.update_event_status(session, job_id=job_id, status="cancelled")
            try:
                await self.deps.bot.delete_message(chat_id=callback.message.chat.id,
                                                   message_id=callback.message.message_id)
            except Exception as e:
                pass
            await callback.message.answer(f"✅ **Reminder Cancelled**\n\n📋 {event.event_name}", parse_mode='Markdown',
                                          reply_markup=get_main_buttons())
        await callback.answer()

    async def get_user_contact(self, message: Message):
        async with get_db_session(self.deps.session_factory) as session:
            db.add_user_phone(session, message.chat.id, message.contact.phone_number)
        await message.answer("✅ Thanks! Now, please select your timezone to ensure reminders are accurate.",
                             reply_markup=get_timezone_keyboard())
        # await self.start(message)

    async def handle_text_message(self, message: Message):
        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, message.chat.id, message.from_user.first_name)
        if not user or not user.phone_number:
            await message.answer("Please share your phone number first so I can assist you.",
                                 reply_markup=share_phone_button())
            return

        if user.timezone == 'UTC':
            await message.answer("Please select your timezone first to set a reminder. ",
                                 reply_markup=get_timezone_keyboard())
            return

        status_message = await message.reply("Analyzing your request...", reply_markup=get_main_buttons())
        response_text = self.deps.ai_manager.analyze_text(message.text, user.timezone)
        json_response = convert_to_json(response_text)

        logging.info(f"AI response for {user.user_name}`s request: {json_response}")

        if json_response and json_response.get("status") == "success":
            try:
                remind_time = datetime.strptime(f"{json_response['date']} {json_response['time']}", '%Y-%m-%d %H:%M:%S')
                await self._process_and_schedule(user, message.chat.id, json_response, remind_time)
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

            response_text = self.deps.ai_manager.analyze_audio(file_path, user.timezone)
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
                    await self._process_and_schedule(user, message.chat.id, json_response, remind_time)
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
    dp.message.register(handlers.handle_text_message, F.text)
    dp.message.register(handlers.handle_voice_message, F.voice)
    dp.callback_query.register(handlers.cancel_reminder_callback, F.data.startswith("cancel_"))
    dp.callback_query.register(handlers.select_timezone, F.data.startswith("tz_"))
