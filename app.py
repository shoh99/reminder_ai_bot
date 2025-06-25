import asyncio
import logging
import signal
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.ai_services import AIManager
from scripts.bot_handlers import register_handlers
from scripts.dependincies import BotDependencies  # <-- Import from the new file
from utils.logger import setup_logging
from scripts.models import create_database
from config.settings import Settings  # Use the settings instance you created


async def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    settings = Settings()

    shutdown_event = asyncio.Event()

    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    jobstores = {'default': SQLAlchemyJobStore(url=f'sqlite:///{settings.reminder_db_file}')}
    scheduler = AsyncIOScheduler(jobstores=jobstores, timezone=settings.timezone)
    bot = None

    try:
        create_database()
        engine = create_engine(f"sqlite:///{settings.reminder_db_file}")
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        bot = Bot(token=settings.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dp = Dispatcher()
        ai_manager = AIManager(api_key=settings.gemini_api_key)

        # Create the dependencies object
        deps = BotDependencies(
            bot=bot,
            session_factory=SessionLocal,
            scheduler=scheduler,
            ai_manager=ai_manager
        )

        register_handlers(dp, deps)

        scheduler.start()
        logger.info("Bot started successfully")

        # Graceful shutdown logic
        polling_task = asyncio.create_task(dp.start_polling(bot))
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        done, pending = await asyncio.wait([polling_task, shutdown_task], return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()

    except Exception as e:
        logger.error(f"Bot initialization failed: {e}", exc_info=True)
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        if bot:
            await bot.session.close()
        logger.info("Bot shut down gracefully")


if __name__ == "__main__":
    asyncio.run(main())
