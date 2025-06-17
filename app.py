import os
import asyncio
import dotenv

from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ai_services import AIManager
from bot_handlers import register_handlers
from models import create_database

dotenv.load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
REMINDER_DB_FILE = 'remindme_ai.sqlite'
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')


async def main():
    jobstores = {'default': SQLAlchemyJobStore(url=f'sqlite:///{REMINDER_DB_FILE}')}
    scheduler = AsyncIOScheduler(jobstores=jobstores, timezone="Asia/Seoul")

    scheduler.start()

    try:
        create_database()
        engine = create_engine(f"sqlite:///{REMINDER_DB_FILE}")
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dp = Dispatcher()

        ai_manager = AIManager(api_key=GEMINI_API_KEY)
        register_handlers(dp, ai_manager, SessionLocal, bot, scheduler)

        print("Bot is starting...")
        await dp.start_polling(bot)

    except Exception as e:
        print(f"Bot initialization failed. {e}")

    finally:
        scheduler.shutdown()
        await bot.session.close()
        print("Bot shut down gracefully")


if __name__ == "__main__":
    asyncio.run(main())
