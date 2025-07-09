import os
from aiohttp import web
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import sys
sys.path.append('..')
from config.settings import Settings
from scripts.models import create_database
from scripts import database_crud as db
from services.g_calendar import exchange_code_for_tokens


def get_session_factory():
    settings = Settings()

    db_user = settings.db_user
    db_password = settings.db_password
    db_host = settings.db_host
    db_port = settings.db_port
    db_name = settings.db_name

    db_url = f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    create_database(settings)
    engine = create_engine(db_url)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


async def handle_google_callback(request):
    """It handles the redirect from google"""
    try:
        chat_id = request.query.get('state')
        code = request.query.get('code')
        error = request.query.get('error')

        if error:
            return web.Response(text=f"Authentication failed: {error}", status=400)

        if not chat_id or not code:
            return web.Response(text="Missing required parameters", status=400)

        # Exchange code for tokens
        token_data = exchange_code_for_tokens(code)

        if not token_data:
            return web.Response(text="Failed to exchange code for tokens", status=500)

        # Store tokens in database
        session_factory = get_session_factory()
        with session_factory() as session:
            success = db.store_google_tokens(
                session=session,
                chat_id=int(chat_id),
                access_token=token_data['access_token'],
                refresh_token=token_data['refresh_token'],
                expires_at=token_data['expires_at'],
                calendar_id='primary'
            )

            if success:
                return web.Response(
                    text="✅ Google Calendar connected successfully! You can close this window and return to the bot.",
                    content_type='text/html'
                )
            else:
                return web.Response(text="Failed to store authentication data", status=500)

    except Exception as e:
        print(f"error while handling callback: {e}")
        return web.Response(text=f"Internal server error: {str(e)}", status=500)


async def handle(request):
    name = request.match_info.get('name', "Anonymous")
    text = "Hello, " + name
    return web.Response(text=text)


def setup_server():
    app = web.Application()
    app.add_routes([
        web.get('/', handle),
        web.get("/oath2callback", handle_google_callback)
    ])

    web.run_app(app)


if __name__ == "__main__":
    setup_server()
