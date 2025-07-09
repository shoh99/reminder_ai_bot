from dataclasses import dataclass
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import sessionmaker

from services.ai_services import AIManager
from utils.language_manager import LanguageManager


@dataclass
class BotDependencies:
    """Holds all shared dependencies for the bot that can be passed to handlers."""
    bot: Bot
    session_factory: sessionmaker
    scheduler: AsyncIOScheduler
    ai_manager: AIManager
    lm: LanguageManager


