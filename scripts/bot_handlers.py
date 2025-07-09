import math
import tempfile
import os
import uuid
import logging
import pytz
from scripts import database_crud as db

from datetime import datetime, timedelta, time, date
from contextlib import asynccontextmanager
from dateutil.rrule import rrulestr, MINUTELY, HOURLY, DAILY, WEEKLY, MONTHLY
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode

from sqlalchemy.orm import sessionmaker, Session

from scripts.database_crud import add_google_event_id_to_events
from scripts.dependincies import BotDependencies
from scripts.models import Users, Event
from utils.filters import TranslatedText
from utils.language_manager import LanguageManager
from utils.utils import convert_to_json, create_human_readable_rule, safe_timezone_convert, adjust_datetime_if_needed

SESSION_FACTORY = None
ITEMS_PER_PAGE = 6

def get_language_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en"),
        InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="set_lang_uz"),
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru")
    )
    builder.adjust(1)
    return builder.as_markup()


def get_timezone_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="🇺🇿 Uzbekistan (Tashkent)", callback_data="tz_Asia/Tashkent"),
        InlineKeyboardButton(text="🇰🇷 South Korea (Seoul)", callback_data="tz_Asia/Seoul")
    )
    builder.adjust(1)
    return builder.as_markup()


def share_phone_button(text: str):
    builder = ReplyKeyboardBuilder()
    builder.button(text=text, request_contact=True)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def get_main_buttons(lm: LanguageManager, lang: str):
    builder = ReplyKeyboardBuilder()
    builder.button(text=lm.get_string("buttons.list_reminders", lang))
    builder.button(text=lm.get_string("buttons.cancel_reminders", lang))
    builder.button(text=lm.get_string("buttons.settings", lang))
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)

def get_settings_inline_buttons(lm: LanguageManager, lang: str):
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text=lm.get_string("buttons.change_language", lang), callback_data="settings_change_language"),
        InlineKeyboardButton(text=lm.get_string("buttons.change_timezone", lang), callback_data="settings_change_timezone"),
        InlineKeyboardButton(text=lm.get_string("buttons.sync_google_calendar", lang), callback_data="settings_sync_google_calendar")
    )
    builder.adjust(1)
    return builder.as_markup()


def get_burger_menu_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="☰ Menu")
    return builder.as_markup()


def get_main_inline_menu(lm: LanguageManager, lang: str):
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text=lm.get_string("buttons.list_reminders", lang), callback_data="menu_list"),
        InlineKeyboardButton(text=lm.get_string("buttons.cancel_reminders", lang), callback_data="menu_cancel"),
        InlineKeyboardButton(text=lm.get_string("buttons.help", lang), callback_data="menu_help"),
        InlineKeyboardButton(text=lm.get_string("buttons.change_language", lang), callback_data="menu_change_language")
    )
    builder.adjust(2, 2)
    return builder.as_markup()


def create_cancellation_keyboard(reminders: list, page:int):
    """creates an inline keyboard for a specific page of reminders to be cancelled."""

    builder = InlineKeyboardBuilder()
    start_index = page * ITEMS_PER_PAGE
    end_index = start_index + ITEMS_PER_PAGE

    paginated_reminders = reminders[start_index:end_index]

    for event in paginated_reminders:
        button_text = f"❌ {event.event_name[:40]}" # Truncate for readability
        builder.add(InlineKeyboardButton(text=button_text, callback_data=f"cancel_{event.schedule.job_id}"))

    control_buttons = []
    total_pages = math.ceil(len(reminders) / ITEMS_PER_PAGE)

    if page > 0:
        control_buttons.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"page_cancel_{page-1}" # go to the previous page
            )
        )

    if end_index < len(reminders):
        control_buttons.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"page_cancel_{page+1}" # go to the next page
            )
        )


    builder.adjust(1)
    if control_buttons:
        builder.row(*control_buttons)

    return builder.as_markup()



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
    lm = LanguageManager()
    try:
        async with get_db_session(SESSION_FACTORY) as session:
            event = db.get_event_by_job_id(session, job_id)
            status = "complete"

            if not event:
                logging.warning(f"Could not find event for job {job_id} after sending reminder.")
                return

            reminder_text = lm.get_string("reminders.reminder_notification", event.user.language, event_name=event_name,
                                          event_description=event_description)

            await bot.send_message(chat_id=chat_id, text=reminder_text,
                                   reply_markup=get_main_buttons(lm, event.user.language))

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
                                  reminder_time_utc: datetime) -> dict:
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
                event_id = db.create_full_event(
                    session, user_id, data.get("event_name", "Untitled Event"),
                    data.get("event_description", "No details provided."),
                    reminder_time_utc, job_id, data.get("type"),
                    data.get("rrule"), tags
                )
                logging.info(f"Scheduled job {job_id} and saved to db")
                return {'status': True, 'event_id': event_id}
        except Exception as e:
            logging.error(f"Schedule failed: {e}")
            return {'status': False, 'event_id': None}

    async def _process_and_schedule(self, user: Users, chat_id: int, data: dict, remind_time_naive: datetime, now_utc: datetime, now_user_tz: datetime):
        """Process and schedule a reminder/event
        Args:
            user: User object from database
            chat_id: Telegram chat ID
            data: Parsed data from AI response
            remind_time_naive: Naive datetime from AI (assumed to be in user's timezone)
            now_utc: Current time in UTC
            now_user_tz: Current time in user's timezone
        """

        status_message = await self.deps.bot.send_message(chat_id=chat_id, text=self.deps.lm.get_string(
            "scheduling.scheduling_in_progress",
            user.language)
                                                          )
        try:
            user_tz = pytz.timezone(user.timezone)

            remind_time_naive = adjust_datetime_if_needed(remind_time_naive, now_user_tz)

            try:
                # localize the naive datetime to user's timezone
                remind_time_local = user_tz.localize(remind_time_naive)
            except pytz.AmbiguousTimeError:
                # handle daylight saving the ambiguity - assume standard time
                remind_time_local = user_tz.localize(remind_time_naive, is_dst=False)
                logging.warning(f"Ambiguous time detected, assumed standard time: {remind_time_local}")
            except pytz.NonExistentTimeError:
                # handle dayligth saving time gap - move forward 1 hour
                remind_time_naive_adjusted= remind_time_naive + timedelta(hours=1)
                remind_time_local = user_tz.localize(remind_time_naive_adjusted)
                logging.warning(f"Non-existing time detected, moved forward 1 hour: {remind_time_local}")

            # convert to utc for internal processing
            remind_time_utc = remind_time_local.astimezone(pytz.utc)
            logging.info(f"Time processing for user {user.user_name}: "
                         f"naive={remind_time_naive}, "
                         f"local={remind_time_local}, "
                         f"utc={remind_time_utc}, "
                         f"now_utc={now_utc}")

            if remind_time_utc <= now_utc:
                time_diff = now_utc - remind_time_utc
                await status_message.edit_text(
                    text=self.deps.lm.get_string("scheduling.past_time_error", user.language))
                logging.warning(f"The time has passed for user {user.user_name}. "
                                f"Requested time: {remind_time_local} (local) ,"
                                f"{remind_time_utc} (UTC), "
                                f"Current time: {now_utc} (UTC) "
                                f"Time difference: {time_diff}")
                return

            response = await self._scheduler_reminder(chat_id, user.id, user_tz, data, remind_time_utc)
            if response['status']:
                display_time_str = remind_time_local.strftime('%Y/%m/%d %H:%M %Z')
                if data.get("rrule"):
                    schedule_text = create_human_readable_rule(data["rrule"], remind_time_local, self.deps.lm,
                                                               user.language)
                else:
                    schedule_text = self.deps.lm.get_string("scheduling.one_time_schedule_prefix", user.language,
                                                            display_time_str=display_time_str)

                confirmation_message = self.deps.lm.get_string(
                    "scheduling.schedule_confirmation",
                    user.language,
                    event_name=data['event_name'],
                    schedule_text=schedule_text
                )

                # Check if user has Google Calendar connected and create event
                await self._create_google_calendar_event_if_connected(chat_id, data, remind_time_local, user_tz, user.language, response['event_id'])

                await status_message.edit_text(text=confirmation_message)
            else:
                await status_message.edit_text(text=self.deps.lm.get_string("scheduling.schedule_error", user.language))
        except Exception as e:
            logging.error(f"Error at processing and scheduling job: {e}")
            await status_message.edit_text(text=self.deps.lm.get_string("scheduling.unexpected_error", user.language))

    async def _create_google_calendar_event_if_connected(self, chat_id: int, data: dict, remind_time_local: datetime, user_tz: pytz.timezone, user_language: str, event_id):
        """Create Google Calendar event if user has Google Calendar connected"""
        try:
            async with get_db_session(self.deps.session_factory) as session:
                # Check if user has Google Calendar connected
                if not db.is_google_calendar_connected(session, chat_id):
                    return
                
                # Get user's Google Calendar tokens
                tokens = db.get_google_tokens(session, chat_id)
                if not tokens:
                    return
                
                access_token = tokens['access_token']
                
                # Check if token needs refresh
                try:
                    # Ensure both datetimes are timezone-aware for comparison
                    current_time = datetime.now(pytz.utc)
                    token_expires = tokens['expires_at']
                    
                    # Handle both datetime and date objects
                    if token_expires:
                        # Check if it's a date object (not datetime)
                        if isinstance(token_expires, date) and not isinstance(token_expires, datetime):
                            # It's a date object, convert to datetime at start of day
                            token_expires = datetime.combine(token_expires, time.min)
                        
                        # Convert token_expires to timezone-aware UTC if it's naive
                        if not hasattr(token_expires, 'tzinfo') or token_expires.tzinfo is None:
                            token_expires = pytz.utc.localize(token_expires)
                        elif token_expires.tzinfo != pytz.utc:
                            token_expires = token_expires.astimezone(pytz.utc)
                    
                    if token_expires and current_time >= token_expires:
                        # Token expired, try to refresh
                        from services.g_calendar import refresh_access_token, get_oauth_client_config
                        
                        oauth_config = get_oauth_client_config()
                        if oauth_config and tokens['refresh_token']:
                            refresh_result = refresh_access_token(
                                tokens['refresh_token'],
                                oauth_config['client_id'],
                                oauth_config['client_secret']
                            )
                            
                            if refresh_result:
                                # Update the access token in database
                                db.update_google_access_token(
                                    session, 
                                    chat_id, 
                                    refresh_result['access_token'], 
                                    refresh_result['expires_at']
                                )
                                access_token = refresh_result['access_token']
                                logging.info(f"Successfully refreshed Google Calendar token for user {chat_id}")
                            else:
                                logging.error(f"Failed to refresh Google Calendar token for user {chat_id}")
                                return
                        else:
                            logging.warning(f"Cannot refresh Google Calendar token for user {chat_id} - missing refresh token or client config")
                            return
                
                except Exception as datetime_error:
                    logging.error(f"Error checking token expiration for user {chat_id}: {datetime_error}")
                    # Continue with existing token if there's a datetime comparison error
                    pass
                
                # Prepare event data
                event_name = data.get('event_name', 'Reminder')
                event_description = data.get('event_description', 'Scheduled reminder from ReminderBot')
                event_type = data.get('type', 'one_time')
                rrule = data.get('rrule') if event_type == 'recurring' else None
                
                # Set end time (15 minutes after start for reminders)
                end_time_local = remind_time_local + timedelta(minutes=15)
                
                # Create the calendar event
                from services.g_calendar import create_calendar_event, get_oauth_client_config
                
                # Get OAuth config for credentials
                oauth_config = get_oauth_client_config()
                
                result = create_calendar_event(
                    access_token=access_token,
                    event_name=event_name,
                    event_description=event_description,
                    start_time=remind_time_local,
                    end_time=end_time_local,
                    timezone_str=str(user_tz),
                    rrule=rrule,
                    refresh_token=tokens.get('refresh_token'),
                    client_id=oauth_config.get('client_id') if oauth_config else None,
                    client_secret=oauth_config.get('client_secret') if oauth_config else None
                )
                
                if result['success']:
                    logging.info(f"Successfully created Google Calendar event for user {chat_id}: {result['event_id']}")
                    # Send confirmation message to user
                    try:
                        if result.get('is_recurring', False):
                            confirmation_text = self.deps.lm.get_string("google_calendar.recurring_event_created", user_language)
                        else:
                            confirmation_text = self.deps.lm.get_string("google_calendar.event_created", user_language)
                        
                        await self.deps.bot.send_message(
                            chat_id=chat_id,
                            text=confirmation_text
                        )

                        async with get_db_session(self.deps.session_factory) as session:
                            add_google_event_id_to_events(session, event_id, result['event_id'])

                    except Exception as e:
                        logging.error(f"Failed to send Google Calendar confirmation message: {e}")
                else:
                    logging.error(f"Failed to create Google Calendar event for user {chat_id}: {result.get('error')}")
                    
        except Exception as e:
            logging.error(f"Error creating Google Calendar event for user {chat_id}: {e}")
            # Don't let Google Calendar errors break the reminder scheduling

    # --- Message and Callback Handlers as class methods ---
    async def start(self, message: Message):
        async with get_db_session(self.deps.session_factory) as session:
            try:
                user = db.get_or_create_user(session, message.chat.id, message.from_user.first_name)
            except Exception as e:
                logging.error(f"Failed to get/create user: {e}")
                await message.answer("Sorry, there was a error.")
                return

            if not user.language:
                await message.answer(
                    "Please select your language:\n\nTilni tanlang:\n\nВыберите ваш язык:",
                    reply_markup=get_language_keyboard()
                )
                return

            user_lang = user.language
            if not user.phone_number:
                response_message = self.deps.lm.get_string("greetings.request_phone", user_lang,
                                                           first_name=message.from_user.first_name)
                await message.answer(response_message, reply_markup=share_phone_button())
            elif user.timezone == "UTC":
                response_message = self.deps.lm.get_string("setup.request_timezone", user_lang)
                await message.answer(response_message, reply_markup=get_timezone_keyboard())
            else:
                response_message = self.deps.lm.get_string("greetings.welcome", user_lang,
                                                           first_name=message.from_user.first_name)

                await message.answer(response_message, reply_markup=get_main_buttons(self.deps.lm, user_lang))

    async def select_timezone(self, callback: CallbackQuery):
        """Handle the user's timezone selection"""
        try:
            await self.deps.bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
        except Exception as e:
            logging.error("Error at message deletion")

        try:
            user_tz = callback.data.split("tz_")[1]
            async with get_db_session(self.deps.session_factory) as session:
                user = db.update_user_timezone(session, callback.message.chat.id, user_tz)
                logging.info(f"User: {user}")
                if user:
                    user_lang = user.language
                    await callback.message.answer(self.deps.lm.get_string("setup.timezone_selected", user_lang),
                                                  reply_markup=get_main_buttons(self.deps.lm, user_lang))
                else:
                    await callback.message.reply("Sorry, something went wrong. Please try again.")
        except Exception as e:
            logging.error(f"Error setting timezone: {e}")
            await callback.message.edit_text(self.deps.lm.get_string("errors.generic_error", user.language))
        finally:
            await callback.answer()

    async def list_reminders(self, message: Message):
        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, message.chat.id, message.from_user.first_name)
            reminders = db.get_active_reminders_by_user(session, user.id)
            user_tz = pytz.timezone(user.timezone)

        if not reminders:
            await message.answer(self.deps.lm.get_string("reminders.no_active_reminders", user.language),
                                 reply_markup=get_main_buttons(self.deps.lm, user.language))
            return

        response_text = self.deps.lm.get_string("reminders.active_reminders_header",
                                                user.language,
                                                reminder_count=len(reminders))

        for event in reminders:
            response_text += f"▪️{event.event_name}\n"
            scheduled_time_local = safe_timezone_convert(
                event.schedule.scheduled_time,
                user_tz,
                pytz.utc
            )
            try:
                if event.schedule.rrule:
                    rule_text = create_human_readable_rule(event.schedule.rrule, scheduled_time_local, self.deps.lm,
                                                           user.language)
                    response_text += self.deps.lm.get_string("reminders.recurring_prefix", user.language,
                                                             rule_text=rule_text)
                else:
                    response_text += f"  - 🗓️ {scheduled_time_local.strftime('%Y/%m/%d %H:%M %Z')}\n\n"
            except Exception as e:
                logging.error(f"List reminder error: {e}, event rrule: {event.schedule.rrule}")
        try:
            await self.deps.bot.delete_message(chat_id=message.chat.id, message_id=message.message_id - 1)
        except Exception as e:
            logging.error(f"Error at deleting message. {e}")

        await message.answer(response_text, parse_mode="Markdown",
                             reply_markup=get_main_buttons(self.deps.lm, user.language))

    async def cancel_reminders_list(self, message: Message):
        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, message.chat.id, message.from_user.first_name)
            reminders = db.get_active_reminders_by_user(session, user.id)

            try:
                await self.deps.bot.delete_message(chat_id=message.chat.id, message_id=message.message_id - 1)
            except Exception as e:
                logging.error(f"Error at deleting message. {e}")

        if not reminders:
            await message.answer(self.deps.lm.get_string("reminders.no_active_reminders", user.language),
                                 reply_markup=get_main_buttons(self.deps.lm, user.language))
            return

        keyword = create_cancellation_keyboard(reminders, page=0)
        await message.answer(self.deps.lm.get_string("cancellation.select_reminder_to_cancel", user.language),
                             reply_markup=keyword,
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

            await callback.answer(self.deps.lm.get_string("cancellation.cancellation_confirmation", event.user.language, event_name=event.event_name, show_alert=False))

            remaining_events = db.get_active_reminders_by_user(session, user_id=event.user_id)
            if remaining_events:
                updated_keyword = create_cancellation_keyboard(remaining_events, page=0)
                await callback.message.edit_reply_markup(reply_markup=updated_keyword)
            else:
                try:
                    await callback.message.delete()
                except Exception as e:
                    logging.error(f"Failed to delete message: {e}")

                await self.deps.bot.send_message(
                    chat_id=callback.message.chat.id,
                    text=self.deps.lm.get_string("reminders.no_active_reminders", event.user.language),
                    reply_markup=get_main_buttons(self.deps.lm, event.user.language)
                )

    async def handle_cancel_pagination(self, callback: CallbackQuery):
        """Handles next and back button clicks for the cancellation list"""
        page = int(callback.data.split("_")[-1])

        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, callback.message.chat.id, callback.from_user.first_name)
            reminders = db.get_active_reminders_by_user(session, user.id)

        user_lang = user.language
        new_keyboard = create_cancellation_keyboard(reminders, page=page)
        total_pages = math.ceil(len(reminders) / ITEMS_PER_PAGE)
        new_text = f"{self.deps.lm.get_string('cancellation.select_reminder_to_cancel', user_lang)}"

        await callback.message.edit_text(text=new_text, reply_markup=new_keyboard, parse_mode='Markdown')
        await callback.answer()

    async def settings(self, message: Message):
        chat_id = message.chat.id
        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, chat_id, message.from_user.first_name)
            await message.answer(
                self.deps.lm.get_string("settings.settings_menu", user.language),
                reply_markup=get_settings_inline_buttons(self.deps.lm, user.language)
            )

    async def settings_change_language_callback(self, callback: CallbackQuery):
        """Handle inline button click for changing language in settings"""
        chat_id = callback.message.chat.id
        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, chat_id, callback.from_user.first_name)
            
        await callback.message.edit_text(
            text=self.deps.lm.get_string("setup.ask_language", user.language),
            reply_markup=get_language_keyboard()
        )
        await callback.answer()

    async def settings_change_timezone_callback(self, callback: CallbackQuery):
        """Handle inline button click for changing timezone in settings"""
        chat_id = callback.message.chat.id
        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, chat_id, callback.from_user.first_name)
            
        await callback.message.edit_text(
            text=self.deps.lm.get_string("setup.request_timezone", user.language),
            reply_markup=get_timezone_keyboard()
        )
        await callback.answer()

    async def settings_sync_google_calendar_callback(self, callback: CallbackQuery):
        """Handle inline button click for Google Calendar sync"""
        chat_id = callback.message.chat.id
        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, chat_id, callback.from_user.first_name)
            
            # Check if user is already connected to Google Calendar
            is_connected = db.is_google_calendar_connected(session, chat_id)
            
            if is_connected:
                # User is already connected - show disconnect option
                disconnect_builder = InlineKeyboardBuilder()
                disconnect_builder.add(
                    InlineKeyboardButton(
                        text=self.deps.lm.get_string("google_calendar.disconnect_button", user.language), 
                        callback_data="disconnect_google_calendar"
                    ),
                    InlineKeyboardButton(
                        text=self.deps.lm.get_string("buttons.back_to_settings", user.language), 
                        callback_data="back_to_settings"
                    )
                )
                disconnect_builder.adjust(1)
                
                await callback.message.edit_text(
                    text=self.deps.lm.get_string("google_calendar.already_connected", user.language),
                    reply_markup=disconnect_builder.as_markup()
                )
            else:
                # User needs to connect - generate auth URL
                from services.g_calendar import get_google_auth_url
                auth_url = get_google_auth_url(str(chat_id))
                
                # Create inline keyboard with authentication link
                auth_builder = InlineKeyboardBuilder()
                auth_builder.add(
                    InlineKeyboardButton(
                        text=self.deps.lm.get_string("buttons.authenticate_google", user.language), 
                        url=auth_url
                    ),
                    InlineKeyboardButton(
                        text=self.deps.lm.get_string("buttons.back_to_settings", user.language), 
                        callback_data="back_to_settings"
                    )
                )
                auth_builder.adjust(1)
                
                await callback.message.edit_text(
                    text=self.deps.lm.get_string("settings.google_calendar_sync", user.language),
                    reply_markup=auth_builder.as_markup()
                )
                
        await callback.answer()

    async def back_to_settings_callback(self, callback: CallbackQuery):
        """Handle back to settings button"""
        chat_id = callback.message.chat.id
        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, chat_id, callback.from_user.first_name)
            
        await callback.message.edit_text(
            text=self.deps.lm.get_string("settings.settings_menu", user.language),
            reply_markup=get_settings_inline_buttons(self.deps.lm, user.language)
        )
        await callback.answer()

    async def disconnect_google_calendar_callback(self, callback: CallbackQuery):
        """Handle disconnecting Google Calendar"""
        chat_id = callback.message.chat.id
        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, chat_id, callback.from_user.first_name)
            
            # Remove Google Calendar tokens
            success = db.remove_google_tokens(session, chat_id)
            
            if success:
                await callback.message.edit_text(
                    text=self.deps.lm.get_string("google_calendar.disconnected", user.language),
                    reply_markup=InlineKeyboardBuilder().add(
                        InlineKeyboardButton(
                            text=self.deps.lm.get_string("buttons.back_to_settings", user.language), 
                            callback_data="back_to_settings"
                        )
                    ).as_markup()
                )
            else:
                await callback.message.edit_text(
                    text="❌ Failed to disconnect Google Calendar. Please try again.",
                    reply_markup=InlineKeyboardBuilder().add(
                        InlineKeyboardButton(
                            text=self.deps.lm.get_string("buttons.back_to_settings", user.language), 
                            callback_data="back_to_settings"
                        )
                    ).as_markup()
                )
                
        await callback.answer()

    async def select_langauge(self, callback: CallbackQuery):
        lang_code = callback.data.split("_")[2]
        chat_id = callback.message.chat.id
        first_name = callback.from_user.first_name
        logging.info(f"User selected language: {lang_code}")
        async with get_db_session(self.deps.session_factory) as session:
            user = db.add_user_lang(session, chat_id, lang_code)

            try:
                await self.deps.bot.delete_message(chat_id=chat_id, message_id=callback.message.message_id)
            except Exception as e:
                logging.error(f"Failed to delete message: {e}")
            if user.phone_number is None:
                await callback.message.answer(
                    self.deps.lm.get_string("greetings.request_phone", lang_code, first_name=first_name),
                    reply_markup=share_phone_button(self.deps.lm.get_string("buttons.share_phone", lang_code))
                )
            else:
                await callback.message.answer(text=self.deps.lm.get_string("setup.timezone_selected", lang_code))

            await callback.answer()

    async def get_user_contact(self, message: Message):
        async with get_db_session(self.deps.session_factory) as session:
            user = db.add_user_phone(session, message.chat.id, message.contact.phone_number)

            if user:
                user_lang = user.language
                response_text = self.deps.lm.get_string("setup.phone_thanks", user_lang)
                await message.answer(response_text,
                                     reply_markup=get_timezone_keyboard())

    async def handle_text_message(self, message: Message):
        now_utc = datetime.now(pytz.utc)

        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, message.chat.id, message.from_user.first_name)
        if not user or not user.phone_number:
            await message.answer(self.deps.lm.get_string("greetings.request_phone_generic", user.language),
                                 reply_markup=share_phone_button(self.deps.lm.get_string("buttons.share_phone",
                                                                                         user.language)))
            return

        if user.timezone == 'UTC':
            await message.answer(self.deps.lm.get_string("setup.request_timezone", user.language),
                                 reply_markup=get_timezone_keyboard())
            return

        user_tz = pytz.timezone(user.timezone)
        now_user_tz = now_utc.astimezone(user_tz)

        status_message = await message.reply(
            self.deps.lm.get_string("analysis.text_request_in_progress", user.language),
            reply_markup=get_main_buttons(self.deps.lm, user.language))

        response_text = self.deps.ai_manager.analyze_text(message.text, user.timezone, user.language)
        json_response = convert_to_json(response_text)

        logging.info(f"AI response for {user.user_name}`s language: {user.language} request: {json_response}")

        if json_response and json_response.get("status") == "success":
            try:
                remind_time = datetime.strptime(f"{json_response['date']} {json_response['time']}", '%Y-%m-%d %H:%M:%S')
                await self._process_and_schedule(user, message.chat.id, json_response, remind_time, now_utc, now_user_tz)
            except (ValueError, TypeError, KeyError):
                new_text = self.deps.lm.get_string("analysis.format_error", user.language)
                if status_message != new_text:
                    await status_message.edit_text(new_text)
                else:
                    await status_message.edit_text(self.deps.lm.get_string("analysis.format_error", user.language))
        else:
            await status_message.answer(self.deps.lm.get_string("analysis.unclear_request", user.language))

    async def handle_voice_message(self, message: Message):
        now_utc = datetime.now(pytz.utc)
        async with get_db_session(self.deps.session_factory) as session:
            user = db.get_or_create_user(session, message.chat.id, message.from_user.first_name)
        if not user or not user.phone_number:
            await message.answer("greetings.request_phone_generic", user.language,
                                 reply_markup=share_phone_button())
            return

        if user.timezone == 'UTC':
            await message.answer(self.deps.lm.get_string("setup.request_timezone", user.language),
                                 reply_markup=get_timezone_keyboard())
            return

        status_message = await message.reply(
            self.deps.lm.get_string("analysis.voice_request_in_progress", user.language))

        user_tz = pytz.timezone(user.timezone)
        now_user_tz = now_utc.astimezone(user_tz)

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, f"{message.voice.file_id}.ogg")
            await self.deps.bot.download(message.voice, destination=file_path)

            response_text = self.deps.ai_manager.analyze_audio(file_path, user.timezone, user.language)
            json_response = convert_to_json(response_text)

            logging.info(f"AI voice response for {user.user_name}'s language: {user.language} request: {json_response}")
            if json_response and json_response.get("status") == "success":
                try:
                    transcript = json_response.get('transcript', 'Unavailable')
                    event = json_response.get('event_description', 'Untitled Event')
                    date = json_response.get('date')
                    time = json_response.get('time')

                    remind_time = datetime.strptime(f"{date} {time}", '%Y-%m-%d %H:%M:%S')
                    response_text_confirmation = self.deps.lm.get_string(
                        "analysis.voice_confirmation",
                        user.language,
                        transcript=transcript,
                        event=event,
                        date=date,
                        time=time
                    )

                    await message.answer(response_text_confirmation,
                                         reply_markup=get_main_buttons(self.deps.lm, user.language))
                    await self._process_and_schedule(user, message.chat.id, json_response, remind_time, now_utc, now_user_tz)
                except (ValueError, TypeError, KeyError) as e:
                    logging.error(f"Error parsing voice datetime: {e} , data: {json_response}")
                    await status_message.edit_text(self.deps.lm.get_string("analysis.format_error", user.language))
            else:
                await status_message.edit_text(self.deps.lm.get_string("analysis.unclear_request", user.language))


def register_handlers(dp: Dispatcher, deps: BotDependencies, lm: LanguageManager):
    """
    Registers all handlers with proper dependency injection using a class-based approach.
    """
    handlers = BotHandlers(deps)
    global SESSION_FACTORY
    if SESSION_FACTORY is None:
        SESSION_FACTORY = deps.session_factory

    dp.message.register(handlers.start, Command("start", "help"))
    dp.message.register(handlers.start, TranslatedText(lm, "buttons.help"))
    dp.message.register(handlers.list_reminders, Command("list"))
    dp.message.register(handlers.list_reminders, TranslatedText(lm, "buttons.list_reminders"))
    dp.message.register(handlers.cancel_reminders_list, Command("cancel"))
    dp.message.register(handlers.cancel_reminders_list, TranslatedText(lm, "buttons.cancel_reminders"))
    dp.message.register(handlers.settings, TranslatedText(lm, "buttons.settings"))
    dp.message.register(handlers.get_user_contact, F.contact)
    dp.message.register(handlers.handle_text_message, F.text)
    dp.message.register(handlers.handle_voice_message, F.voice)

    dp.callback_query.register(handlers.cancel_reminder_callback, F.data.startswith("cancel_"))
    dp.callback_query.register(handlers.handle_cancel_pagination, F.data.startswith("page_cancel"))
    dp.callback_query.register(handlers.select_timezone, F.data.startswith("tz_"))
    dp.callback_query.register(handlers.select_langauge, F.data.startswith("set_lang"))
    dp.callback_query.register(handlers.settings_change_language_callback, F.data == "settings_change_language")
    dp.callback_query.register(handlers.settings_change_timezone_callback, F.data == "settings_change_timezone")
    dp.callback_query.register(handlers.settings_sync_google_calendar_callback, F.data == "settings_sync_google_calendar")
    dp.callback_query.register(handlers.disconnect_google_calendar_callback, F.data == "disconnect_google_calendar")
    dp.callback_query.register(handlers.back_to_settings_callback, F.data == "back_to_settings")
    dp.callback_query.register(handlers.disconnect_google_calendar_callback, F.data == "disconnect_google_calendar")
