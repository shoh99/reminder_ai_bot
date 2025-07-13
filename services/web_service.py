import os
import ssl

from aiohttp import web
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import sys

sys.path.append('..')

from config.settings import Settings
from scripts.models import create_database
from scripts import database_crud as db
from services.g_calendar import exchange_code_for_tokens
from utils.language_manager import LanguageManager


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
        state_data = request.query.get('state')
        code = request.query.get('code')
        error = request.query.get('error')

        # Parse state to extract chat_id and language
        if state_data and '|' in state_data:
            chat_id, language = state_data.split('|', 1)
        else:
            # Fallback for old format
            chat_id = state_data
            language = 'en'

        # Initialize language manager
        lm = LanguageManager()

        if error:
            return web.Response(
                text=get_error_html(f"Authentication failed: {error}", language, lm),
                content_type='text/html',
                status=400
            )

        if not chat_id or not code:
            return web.Response(
                text=get_error_html("Missing required parameters", language, lm),
                content_type='text/html',
                status=400
            )

        # Exchange code for tokens
        token_data = exchange_code_for_tokens(code)

        if not token_data:
            return web.Response(
                text=get_error_html("Failed to exchange code for tokens", language, lm),
                content_type='text/html',
                status=500
            )

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
                    text=get_success_html(language, lm),
                    content_type='text/html'
                )
            else:
                return web.Response(
                    text=get_error_html("Failed to store authentication data", language, lm),
                    content_type='text/html',
                    status=500
                )

    except Exception as e:
        print(f"error while handling callback: {e}")
        return web.Response(
            text=get_error_html(f"Internal server error: {str(e)}", 'en', LanguageManager()),
            content_type='text/html',
            status=500
        )


async def handle(request):
    """Default handler with a nice welcome page"""
    return web.Response(
        text=get_welcome_html(),
        content_type='text/html'
    )


async def health_check(request):
    """Health check endpoint"""
    return web.Response(text="OK", status=200)


async def privacy_policy(request):
    """Privacy policy page"""
    return web.Response(
        text=get_privacy_policy_html(),
        content_type='text/html'
    )


async def terms_of_service(request):
    """Terms of service page"""
    return web.Response(
        text=get_terms_of_service_html(),
        content_type='text/html'
    )


def setup_server():
    settings = Settings()
    web_host = settings.web_server_host
    web_port = int(settings.web_server_port)

    # Create an SSL context
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

    # Load your certificate and private key
    ssl_context.load_cert_chain(
        f'/etc/letsencrypt/live/{web_host}/fullchain.pem',
        f'/etc/letsencrypt/live/{web_host}/privkey.pem'
    )

    app = web.Application()
    app.add_routes([
        web.get('/', handle),
        web.get('/health', health_check),
        web.get('/privacy', privacy_policy),
        web.get('/terms', terms_of_service),
        web.get("/oath2callback", handle_google_callback)
    ])

    print(f"🚀 Starting OAuth server on {web_host}")
    print("📋 Available endpoints:")
    print("   GET /              - Welcome page")
    print("   GET /health        - Health check")
    print("   GET /privacy       - Privacy Policy")
    print("   GET /terms         - Terms of Service")
    print("   GET /oath2callback - Google OAuth callback")

    web.run_app(app, port=web_port, ssl_context=ssl_context)


def get_welcome_html():
    """Return a welcome page HTML"""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>PlanAI Bot Service</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }
            
            .container {
                background: white;
                border-radius: 20px;
                padding: 40px;
                text-align: center;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                max-width: 500px;
                width: 100%;
            }
            
            .robot-icon {
                font-size: 60px;
                margin-bottom: 20px;
            }
            
            .title {
                color: #2c3e50;
                font-size: 28px;
                font-weight: 600;
                margin-bottom: 15px;
            }
            
            .message {
                color: #5a6c7d;
                font-size: 16px;
                line-height: 1.6;
                margin-bottom: 25px;
            }
            
            .status {
                background: #d4edda;
                border: 1px solid #c3e6cb;
                color: #155724;
                padding: 15px;
                border-radius: 10px;
                margin: 20px 0;
                font-weight: 600;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="robot-icon">🤖</div>
            <h1 class="title">PlanAI Bot</h1>
            <p class="message">
                This is the OAuth callback service for the PlanAI Bot. 
                This page handles Google Calendar authentication.
            </p>
            <div class="status">
                ✅ Service is running and ready to handle OAuth callbacks
            </div>
            <p class="message">
                If you're seeing this page, the OAuth service is working correctly.
                Authentication callbacks will be processed automatically.
            </p>
            
            <div style="margin-top: 30px; padding-top: 20px; border-top: 2px solid #f0f0f0;">
                <a href="/privacy" style="color: #667eea; text-decoration: none; margin: 0 15px; font-weight: 500;">Privacy Policy</a>
                <a href="/terms" style="color: #667eea; text-decoration: none; margin: 0 15px; font-weight: 500;">Terms of Service</a>
            </div>
        </div>
    </body>
    </html>
    """


def get_success_html(language='en', lm=None):
    """Return a beautiful success page HTML with translations"""
    if not lm:
        lm = LanguageManager()

    # Get translated strings
    title = lm.get_string("web.success_title", language)
    subtitle = lm.get_string("web.success_subtitle", language)
    message = lm.get_string("web.success_message", language)
    what_next = lm.get_string("web.what_next", language)
    features = [
        lm.get_string("web.feature_calendar_sync", language),
        lm.get_string("web.feature_recurring", language),
        lm.get_string("web.feature_manage_both", language),
        lm.get_string("web.feature_real_time", language)
    ]
    return_message = lm.get_string("web.return_to_bot", language)
    close_button = lm.get_string("web.close_window", language)
    auto_close_message = lm.get_string("web.auto_close_confirm", language)

    # Use fallbacks if translations are missing
    title = title if title != "web.success_title" else "🎉 Successfully Connected!"
    subtitle = subtitle if subtitle != "web.success_subtitle" else "Google Calendar Connected!"
    message = message if message != "web.success_message" else "Your Google Calendar has been connected to the PlanAI Bot. All your future reminders will now be automatically synced to your calendar!"
    what_next = what_next if what_next != "web.what_next" else "📅 What happens next?"
    return_message = return_message if return_message != "web.return_to_bot" else "You can now close this window and return to the Telegram bot to continue."
    close_button = close_button if close_button != "web.close_window" else "Close Window"
    auto_close_message = auto_close_message if auto_close_message != "web.auto_close_confirm" else "Auto-close window? Click OK to close or Cancel to keep open."

    # Default features if translations missing
    if features[0] == "web.feature_calendar_sync":
        features = [
            "Future reminders will appear in Google Calendar",
            "Recurring events will be created automatically",
            "You can manage reminders from both the bot and calendar",
            "Changes sync in real-time"
        ]
    return f"""
    <!DOCTYPE html>
    <html lang="{language}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{subtitle}</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }}
            
            .container {{
                background: white;
                border-radius: 20px;
                padding: 40px;
                text-align: center;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                max-width: 500px;
                width: 100%;
                animation: slideUp 0.5s ease-out;
            }}
            
            @keyframes slideUp {{
                from {{
                    opacity: 0;
                    transform: translateY(30px);
                }}
                to {{
                    opacity: 1;
                    transform: translateY(0);
                }}
            }}
            
            .success-icon {{
                width: 80px;
                height: 80px;
                background: #4CAF50;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 20px;
                animation: bounce 1s ease-out;
            }}
            
            @keyframes bounce {{
                0%, 20%, 50%, 80%, 100% {{
                    transform: translateY(0);
                }}
                40% {{
                    transform: translateY(-10px);
                }}
                60% {{
                    transform: translateY(-5px);
                }}
            }}
            
            .checkmark {{
                width: 40px;
                height: 40px;
                color: white;
                font-size: 30px;
                font-weight: bold;
            }}
            
            .title {{
                color: #2c3e50;
                font-size: 28px;
                font-weight: 600;
                margin-bottom: 15px;
            }}
            
            .message {{
                color: #5a6c7d;
                font-size: 16px;
                line-height: 1.6;
                margin-bottom: 25px;
            }}
            
            .calendar-info {{
                background: #f8f9fa;
                border-radius: 10px;
                padding: 20px;
                margin: 20px 0;
            }}
            
            .calendar-title {{
                color: #2c3e50;
                font-size: 18px;
                font-weight: 600;
                margin-bottom: 10px;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 10px;
            }}
            
            .feature-list {{
                list-style: none;
                text-align: left;
                color: #5a6c7d;
            }}
            
            .feature-list li {{
                padding: 5px 0;
                display: flex;
                align-items: center;
                gap: 10px;
            }}
            
            .feature-list li::before {{
                content: "✓";
                color: #4CAF50;
                font-weight: bold;
                width: 20px;
            }}
            
            .close-btn {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                padding: 12px 30px;
                border-radius: 25px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s ease;
                margin-top: 10px;
            }}
            
            .close-btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
            }}
            
            .bot-link {{
                color: #667eea;
                text-decoration: none;
                font-weight: 600;
            }}
            
            .bot-link:hover {{
                text-decoration: underline;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="success-icon">
                <div class="checkmark">✓</div>
            </div>
            
            <h1 class="title">{title}</h1>
            
            <p class="message">
                {message}
            </p>
            
            <div class="calendar-info">
                <div class="calendar-title">
                    {what_next}
                </div>
                <ul class="feature-list">
                    <li>{features[0]}</li>
                    <li>{features[1]}</li>
                    <li>{features[2]}</li>
                    <li>{features[3]}</li>
                </ul>
            </div>
            
            <p class="message">
                {return_message}
            </p>
            
            <button class="close-btn" onclick="window.close()">
                {close_button}
            </button>
            
            <div style="margin-top: 30px; padding-top: 20px; border-top: 2px solid #f0f0f0; font-size: 14px;">
                <a href="/privacy" style="color: #667eea; text-decoration: none; margin: 0 15px;">Privacy Policy</a>
                <a href="/terms" style="color: #667eea; text-decoration: none; margin: 0 15px;">Terms of Service</a>
            </div>
        </div>
        
        <script>
            // Auto-close after 10 seconds (optional)
            setTimeout(() => {{
                if (confirm('{auto_close_message}')) {{
                    window.close();
                }}
            }}, 10000);
        </script>
    </body>
    </html>
    """


def get_error_html(error_message, language='en', lm=None):
    """Return a beautiful error page HTML with translations"""
    if not lm:
        lm = LanguageManager()

    # Get translated strings
    title = lm.get_string("web.error_title", language)
    subtitle = lm.get_string("web.error_subtitle", language)
    message = lm.get_string("web.error_message", language)
    error_details_label = lm.get_string("web.error_details", language)
    close_button = lm.get_string("web.close_window", language)
    try_again_button = lm.get_string("web.try_again", language)

    # Use fallbacks if translations are missing
    title = title if title != "web.error_title" else "😔 Connection Failed"
    subtitle = subtitle if subtitle != "web.error_subtitle" else "Connection Failed"
    message = message if message != "web.error_message" else "We couldn't connect your Google Calendar to the PlanAI Bot. Please try again or contact support if the issue persists."
    error_details_label = error_details_label if error_details_label != "web.error_details" else "Error details:"
    close_button = close_button if close_button != "web.close_window" else "Close Window"
    try_again_button = try_again_button if try_again_button != "web.try_again" else "Try Again"
    return f"""
    <!DOCTYPE html>
    <html lang="{language}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{subtitle}</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }}
            
            .container {{
                background: white;
                border-radius: 20px;
                padding: 40px;
                text-align: center;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                max-width: 500px;
                width: 100%;
                animation: slideUp 0.5s ease-out;
            }}
            
            @keyframes slideUp {{
                from {{
                    opacity: 0;
                    transform: translateY(30px);
                }}
                to {{
                    opacity: 1;
                    transform: translateY(0);
                }}
            }}
            
            .error-icon {{
                width: 80px;
                height: 80px;
                background: #ff4757;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 20px;
                animation: shake 0.5s ease-out;
            }}
            
            @keyframes shake {{
                0%, 100% {{ transform: translateX(0); }}
                25% {{ transform: translateX(-5px); }}
                75% {{ transform: translateX(5px); }}
            }}
            
            .error-mark {{
                width: 40px;
                height: 40px;
                color: white;
                font-size: 30px;
                font-weight: bold;
            }}
            
            .title {{
                color: #2c3e50;
                font-size: 28px;
                font-weight: 600;
                margin-bottom: 15px;
            }}
            
            .message {{
                color: #5a6c7d;
                font-size: 16px;
                line-height: 1.6;
                margin-bottom: 25px;
            }}
            
            .error-details {{
                background: #fff5f5;
                border: 1px solid #fed7d7;
                border-radius: 10px;
                padding: 15px;
                margin: 20px 0;
                color: #742a2a;
                font-size: 14px;
            }}
            
            .actions {{
                display: flex;
                gap: 15px;
                justify-content: center;
                flex-wrap: wrap;
            }}
            
            .btn {{
                padding: 12px 25px;
                border-radius: 25px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s ease;
                text-decoration: none;
                display: inline-block;
                border: none;
            }}
            
            .btn-primary {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }}
            
            .btn-secondary {{
                background: #f8f9fa;
                color: #5a6c7d;
                border: 2px solid #e9ecef;
            }}
            
            .btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(0,0,0,0.2);
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="error-icon">
                <div class="error-mark">✗</div>
            </div>
            
            <h1 class="title">{title}</h1>
            
            <p class="message">
                {message}
            </p>
            
            <div class="error-details">
                <strong>{error_details_label}</strong><br>
                {error_message}
            </div>
            
            <div class="actions">
                <button class="btn btn-primary" onclick="window.close()">
                    {close_button}
                </button>
                <a href="#" class="btn btn-secondary">
                    {try_again_button}
                </a>
            </div>
            
            <div style="margin-top: 30px; padding-top: 20px; border-top: 2px solid #f0f0f0; font-size: 14px;">
                <a href="/privacy" style="color: #667eea; text-decoration: none; margin: 0 15px;">Privacy Policy</a>
                <a href="/terms" style="color: #667eea; text-decoration: none; margin: 0 15px;">Terms of Service</a>
            </div>
        </div>
    </body>
    </html>
    """


def get_privacy_policy_html():
    """Return comprehensive privacy policy page for Google OAuth verification"""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Privacy Policy - PlanAI Bot</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
                line-height: 1.6;
            }
            
            .container {
                background: white;
                border-radius: 20px;
                padding: 40px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                max-width: 800px;
                margin: 0 auto;
                animation: slideUp 0.5s ease-out;
            }
            
            @keyframes slideUp {
                from {
                    opacity: 0;
                    transform: translateY(30px);
                }
                to {
                    opacity: 1;
                    transform: translateY(0);
                }
            }
            
            .header {
                text-align: center;
                margin-bottom: 40px;
                padding-bottom: 20px;
                border-bottom: 2px solid #f0f0f0;
            }
            
            .logo {
                font-size: 48px;
                margin-bottom: 10px;
            }
            
            .title {
                color: #2c3e50;
                font-size: 32px;
                font-weight: 600;
                margin-bottom: 10px;
            }
            
            .subtitle {
                color: #5a6c7d;
                font-size: 16px;
            }
            
            .content {
                color: #2c3e50;
            }
            
            .section {
                margin-bottom: 30px;
            }
            
            .section h2 {
                color: #2c3e50;
                font-size: 24px;
                font-weight: 600;
                margin-bottom: 15px;
                padding-left: 15px;
                border-left: 4px solid #667eea;
            }
            
            .section h3 {
                color: #34495e;
                font-size: 18px;
                font-weight: 600;
                margin: 20px 0 10px 0;
            }
            
            .section p {
                margin-bottom: 15px;
                color: #5a6c7d;
                text-align: justify;
            }
            
            .section ul {
                margin-left: 20px;
                margin-bottom: 15px;
            }
            
            .section li {
                margin-bottom: 8px;
                color: #5a6c7d;
            }
            
            .highlight {
                background: #f8f9fa;
                border: 1px solid #e9ecef;
                border-radius: 8px;
                padding: 15px;
                margin: 15px 0;
            }
            
            .contact-info {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 20px;
                border-radius: 10px;
                margin: 20px 0;
                text-align: center;
            }
            
            .back-link {
                display: inline-block;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 12px 24px;
                border-radius: 25px;
                text-decoration: none;
                font-weight: 600;
                transition: all 0.3s ease;
                margin-top: 20px;
            }
            
            .back-link:hover {
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
            }
            
            .footer {
                text-align: center;
                margin-top: 40px;
                padding-top: 20px;
                border-top: 2px solid #f0f0f0;
                color: #5a6c7d;
                font-size: 14px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">🤖</div>
                <h1 class="title">Privacy Policy</h1>
                <p class="subtitle">PlanAI Bot - Google Calendar Integration Service</p>
                <p class="subtitle">Last updated: July 2025</p>
            </div>
            
            <div class="content">
                <div class="section">
                    <h2>1. Introduction</h2>
                    <p>
                        This Privacy Policy describes how PlanAI Bot collects, uses, and protects your information when you use our Google Calendar integration service. By using our service, you agree to the collection and use of information in accordance with this policy.
                    </p>
                </div>
                
                <div class="section">
                    <h2>2. Information We Collect</h2>
                    
                    <h3>2.1 Google Calendar Data</h3>
                    <p>When you connect your Google Calendar to PlanAI Bot, we collect and process:</p>
                    <ul>
                        <li><strong>Calendar Events:</strong> We read, and modify calendar events in your Google Calendar</li>
                        <li><strong>Calendar Metadata:</strong> Basic calendar information to identify where to create events</li>
                        <li><strong>Access Tokens:</strong> OAuth tokens that allow us to access your calendar on your behalf</li>
                    </ul>
                    
                    <h3>2.2 User Information</h3>
                    <ul>
                        <li><strong>Telegram User ID:</strong> Your unique Telegram identifier to link your account</li>
                        <li><strong>Username:</strong> Your Telegram username for account management</li>
                        <li><strong>Language Preference:</strong> Your selected language for localized experience</li>
                        <li><strong>Phone Number:</strong> Optional, for account verification and security</li>
                    </ul>
                    
                    <h3>2.3 Reminder Data</h3>
                    <ul>
                        <li><strong>Reminder Content:</strong> The text content of your reminders</li>
                        <li><strong>Scheduling Information:</strong> Date, time, and recurrence patterns</li>
                        <li><strong>Tags and Categories:</strong> Optional organizational metadata</li>
                    </ul>
                </div>
                
                <div class="section">
                    <h2>3. How We Use Your Information</h2>
                    
                    <div class="highlight">
                        <strong>Primary Purpose:</strong> To sync your reminders between the Telegram bot and your Google Calendar.
                    </div>
                    
                    <p>Specifically, we use your information to:</p>
                    <ul>
                        <li><strong>Create Calendar Events:</strong> Automatically add your reminders to your Google Calendar</li>
                        <li><strong>Manage Recurring Events:</strong> Handle repeating reminders with proper RRULE formatting</li>
                        <li><strong>Synchronization:</strong> Keep your bot reminders and calendar events in sync</li>
                        <li><strong>User Experience:</strong> Provide localized content in your preferred language</li>
                        <li><strong>Account Management:</strong> Link your Telegram account with Google Calendar access</li>
                        <li><strong>Service Improvement:</strong> Analyze usage patterns to improve functionality (anonymized data only)</li>
                    </ul>
                </div>
                
                <div class="section">
                    <h2>4. Data Storage and Security</h2>
                    
                    <h3>4.1 Encryption</h3>
                    <p>
                        All sensitive data, including Google OAuth tokens, are encrypted using industry-standard encryption methods (Fernet encryption) before being stored in our database.
                    </p>
                    
                    <h3>4.2 Data Location</h3>
                    <p>
                        Your data is stored securely in encrypted databases. We implement appropriate technical and organizational measures to protect your data against unauthorized access, alteration, disclosure, or destruction.
                    </p>
                    
                    <h3>4.3 Access Controls</h3>
                    <p>
                        Access to your data is strictly limited to authorized personnel and automated systems that require it for service functionality. We use secure authentication and authorization mechanisms.
                    </p>
                </div>
                
                <div class="section">
                    <h2>5. Google API Services User Data Policy Compliance</h2>
                    
                    <div class="highlight">
                        <strong>Limited Use:</strong> Our use of information received from Google APIs adheres to the Google API Services User Data Policy, including the Limited Use requirements.
                    </div>
                    
                    <p>We commit to:</p>
                    <ul>
                        <li><strong>Limited Use:</strong> Only using Google user data for providing and improving our reminder synchronization features</li>
                        <li><strong>No Human Readable Private Content:</strong> We do not transfer Google user data to humans except for security purposes, legal compliance, or with explicit user consent</li>
                        <li><strong>No Advertising:</strong> We do not use Google user data for advertising purposes</li>
                        <li><strong>No AI/ML Training:</strong> We do not use Google user data to train machine learning models</li>
                    </ul>
                </div>
                
                <div class="section">
                    <h2>6. Data Sharing</h2>
                    
                    <p><strong>We do not sell, trade, or otherwise transfer your personal information to third parties.</strong></p>
                    
                    <p>We may share information only in the following limited circumstances:</p>
                    <ul>
                        <li><strong>With Your Consent:</strong> When you explicitly authorize us to share specific information</li>
                        <li><strong>Legal Requirements:</strong> When required by law, court order, or government regulations</li>
                        <li><strong>Security:</strong> To protect the rights, property, or safety of our users or others</li>
                        <li><strong>Service Providers:</strong> With trusted service providers who assist in operating our service (under strict confidentiality agreements)</li>
                    </ul>
                </div>
                
                <div class="section">
                    <h2>7. Data Retention</h2>
                    
                    <p>We retain your data only as long as necessary to provide our services:</p>
                    <ul>
                        <li><strong>Active Users:</strong> Data is retained while your account is active and you use our services</li>
                        <li><strong>Inactive Accounts:</strong> Data may be retained for up to 12 months after last activity</li>
                        <li><strong>Deleted Accounts:</strong> Upon account deletion, personal data is removed within 30 days</li>
                        <li><strong>Legal Requirements:</strong> Some data may be retained longer if required by law</li>
                    </ul>
                </div>
                
                <div class="section">
                    <h2>8. Your Rights and Controls</h2>
                    
                    <h3>8.1 Access and Control</h3>
                    <ul>
                        <li><strong>Disconnect:</strong> You can disconnect Google Calendar integration at any time through the bot</li>
                        <li><strong>Data Access:</strong> Request access to your personal data we have stored</li>
                        <li><strong>Data Correction:</strong> Request correction of inaccurate personal data</li>
                        <li><strong>Data Deletion:</strong> Request deletion of your personal data</li>
                        <li><strong>Data Portability:</strong> Request a copy of your data in a portable format</li>
                    </ul>
                    
                    <h3>8.2 Google Calendar Permissions</h3>
                    <p>
                        You can revoke our access to your Google Calendar at any time by visiting your Google Account permissions page at <a href="https://myaccount.google.com/permissions">https://myaccount.google.com/permissions</a>
                    </p>
                </div>
                
                <div class="section">
                    <h2>9. Children's Privacy</h2>
                    <p>
                        Our service is not intended for children under 13 years of age. We do not knowingly collect personal information from children under 13. If you are a parent or guardian and believe your child has provided us with personal information, please contact us to have the data removed.
                    </p>
                </div>
                
                <div class="section">
                    <h2>10. Changes to This Privacy Policy</h2>
                    <p>
                        We may update our Privacy Policy from time to time. We will notify you of any changes by posting the new Privacy Policy on this page and updating the "Last updated" date. You are advised to review this Privacy Policy periodically for any changes.
                    </p>
                </div>
                
                <div class="contact-info">
                    <h2>11. Contact Information</h2>
                    <p><strong>If you have any questions about this Privacy Policy, please contact us:</strong></p>
                    <p>📧 Email: support@planaibot.com</p>
                    <p>💬 Telegram: @PlanAIBotSupport</p>
                    <p>🌐 Website: https://planaibot.com</p>
                </div>
                
                <div class="section">
                    <h2>12. Governing Law</h2>
                    <p>
                        This Privacy Policy is governed by and construed in accordance with the laws of South Korea.
                    </p>
                </div>
            </div>
            
            <div class="footer">
                <a href="/" class="back-link">← Back to Home</a>
                <p>© 2025 PlanAI Bot. All rights reserved.</p>
                <p>This privacy policy is designed to comply with Google OAuth app verification requirements.</p>
            </div>
        </div>
    </body>
    </html>
    """


def get_terms_of_service_html():
    """Return terms of service page"""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Terms of Service - PlanAI Bot</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
                line-height: 1.6;
            }
            
            .container {
                background: white;
                border-radius: 20px;
                padding: 40px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                max-width: 800px;
                margin: 0 auto;
                animation: slideUp 0.5s ease-out;
            }
            
            @keyframes slideUp {
                from {
                    opacity: 0;
                    transform: translateY(30px);
                }
                to {
                    opacity: 1;
                    transform: translateY(0);
                }
            }
            
            .header {
                text-align: center;
                margin-bottom: 40px;
                padding-bottom: 20px;
                border-bottom: 2px solid #f0f0f0;
            }
            
            .logo {
                font-size: 48px;
                margin-bottom: 10px;
            }
            
            .title {
                color: #2c3e50;
                font-size: 32px;
                font-weight: 600;
                margin-bottom: 10px;
            }
            
            .subtitle {
                color: #5a6c7d;
                font-size: 16px;
            }
            
            .content {
                color: #2c3e50;
            }
            
            .section {
                margin-bottom: 30px;
            }
            
            .section h2 {
                color: #2c3e50;
                font-size: 24px;
                font-weight: 600;
                margin-bottom: 15px;
                padding-left: 15px;
                border-left: 4px solid #667eea;
            }
            
            .section p {
                margin-bottom: 15px;
                color: #5a6c7d;
                text-align: justify;
            }
            
            .section ul {
                margin-left: 20px;
                margin-bottom: 15px;
            }
            
            .section li {
                margin-bottom: 8px;
                color: #5a6c7d;
            }
            
            .back-link {
                display: inline-block;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 12px 24px;
                border-radius: 25px;
                text-decoration: none;
                font-weight: 600;
                transition: all 0.3s ease;
                margin-top: 20px;
            }
            
            .back-link:hover {
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
            }
            
            .footer {
                text-align: center;
                margin-top: 40px;
                padding-top: 20px;
                border-top: 2px solid #f0f0f0;
                color: #5a6c7d;
                font-size: 14px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">📋</div>
                <h1 class="title">Terms of Service</h1>
                <p class="subtitle">PlanAI Bot - Google Calendar Integration Service</p>
                <p class="subtitle">Last updated: July 2025</p>
            </div>
            
            <div class="content">
                <div class="section">
                    <h2>1. Acceptance of Terms</h2>
                    <p>
                        By using PlanAI Bot and its Google Calendar integration service, you agree to be bound by these Terms of Service. If you do not agree to these terms, please do not use our service.
                    </p>
                </div>
                
                <div class="section">
                    <h2>2. Description of Service</h2>
                    <p>
                        PlanAI Bot is a Telegram-based reminder service that integrates with Google Calendar to synchronize your reminders and calendar events. The service includes:
                    </p>
                    <ul>
                        <li>Creating and managing reminders through Telegram</li>
                        <li>Automatic synchronization with Google Calendar</li>
                        <li>Support for recurring events and complex scheduling</li>
                        <li>Multilingual user interface</li>
                    </ul>
                </div>
                
                <div class="section">
                    <h2>3. User Responsibilities</h2>
                    <p>You agree to:</p>
                    <ul>
                        <li>Provide accurate information when using our service</li>
                        <li>Use the service only for lawful purposes</li>
                        <li>Not attempt to gain unauthorized access to our systems</li>
                        <li>Respect the intellectual property rights of others</li>
                        <li>Not use the service to send spam or malicious content</li>
                    </ul>
                </div>
                
                <div class="section">
                    <h2>4. Privacy and Data Protection</h2>
                    <p>
                        Your privacy is important to us. Please review our Privacy Policy to understand how we collect, use, and protect your information. By using our service, you consent to our data practices as described in the Privacy Policy.
                    </p>
                </div>
                
                <div class="section">
                    <h2>5. Service Availability</h2>
                    <p>
                        We strive to provide reliable service but cannot guarantee 100% uptime. The service may be temporarily unavailable due to maintenance, updates, or technical issues. We are not liable for any inconvenience caused by service interruptions.
                    </p>
                </div>
                
                <div class="section">
                    <h2>6. Limitation of Liability</h2>
                    <p>
                        To the maximum extent permitted by law, PlanAI Bot shall not be liable for any indirect, incidental, special, consequential, or punitive damages resulting from your use of the service.
                    </p>
                </div>
                
                <div class="section">
                    <h2>7. Termination</h2>
                    <p>
                        You may stop using our service at any time. We may terminate or suspend your access to the service at our discretion, with or without notice, for any reason including violation of these terms.
                    </p>
                </div>
                
                <div class="section">
                    <h2>8. Changes to Terms</h2>
                    <p>
                        We reserve the right to modify these terms at any time. We will notify you of any changes by posting the new terms on this page. Your continued use of the service after changes constitutes acceptance of the new terms.
                    </p>
                </div>
            </div>
            
            <div class="footer">
                <a href="/" class="back-link">← Back to Home</a>
                <p>© 2025 PlanAI Bot. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """


if __name__ == "__main__":
    setup_server()
