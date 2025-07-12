import datetime
import os.path
from datetime import datetime, timedelta
import json
import pytz

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import Flow

from config.settings import Settings

settings = Settings()

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
REDIRECT = settings.web_server_host
REDIRECT_URI = f"{settings.web_server_host}:{settings.web_server_port}"

client_config = {
    "web": {
        "client_id": settings.google_client_id,
        "project_id": "reminder-ai-bot", "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": settings.google_client_secret,
        "redirect_uris": [REDIRECT_URI]
    }
}


def get_google_auth_url(chat_id: str, language: str = 'en'):
    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )

    # Combine chat_id and language in state parameter
    state_data = f"{chat_id}|{language}"

    auth_url, _ = flow.authorization_url(
        access_type='offline',
        prompt="consent",
        state=state_data
    )
    print(auth_url)

    return auth_url


def exchange_code_for_tokens(code: str):
    """Exchange authorization code for access and refresh tokens"""
    try:
        flow = Flow.from_client_config(
            client_config=client_config,
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI
        )

        # Exchange the authorization code for tokens
        flow.fetch_token(code=code)

        credentials = flow.credentials

        # Calculate expiration time as timezone-aware UTC datetime
        expires_at = datetime.now(pytz.utc) + timedelta(
            seconds=credentials.expiry.timestamp() - datetime.now(pytz.utc).timestamp()) if credentials.expiry else None

        return {
            'access_token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'expires_at': expires_at,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret
        }

    except Exception as e:
        print(f"Error exchanging code for tokens: {e}")
        return None


def refresh_access_token(refresh_token: str, client_id: str, client_secret: str):
    """Refresh an expired access token"""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    try:
        credentials = Credentials(
            token=None,  # We don't have the current token
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret
        )

        # Refresh the token
        credentials.refresh(Request())

        # Calculate new expiration time as timezone-aware UTC datetime
        expires_at = datetime.now(pytz.utc) + timedelta(seconds=3600)  # Google tokens typically last 1 hour

        return {
            'access_token': credentials.token,
            'expires_at': expires_at
        }

    except Exception as e:
        print(f"Error refreshing access token: {e}")
        return None


def create_calendar_event(access_token: str, event_name: str, event_description: str, start_time: datetime,
                          end_time: datetime = None, timezone_str: str = 'UTC', rrule: str = None,
                          refresh_token: str = None, client_id: str = None, client_secret: str = None):
    """Create an event in Google Calendar (supports both one-time and recurring events)"""
    try:
        # Create credentials with all necessary fields for auto-refresh
        credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token" if refresh_token else None,
            client_id=client_id,
            client_secret=client_secret
        )
        service = build('calendar', 'v3', credentials=credentials)

        # Default end time to 1 hour after start if not provided
        if end_time is None:
            end_time = start_time + timedelta(hours=1)

        # Format datetime for Google Calendar API
        start_datetime = start_time.isoformat()
        end_datetime = end_time.isoformat()

        # Create event object
        event = {
            'summary': event_name,
            'description': event_description,
            'start': {
                'dateTime': start_datetime,
                'timeZone': timezone_str,
            },
            'end': {
                'dateTime': end_datetime,
                'timeZone': timezone_str,
            },
        }

        # Add recurrence rule if this is a recurring event
        if rrule:
            # Google Calendar expects RRULE in the format: ["RRULE:FREQ=WEEKLY;BYDAY=MO"]
            event['recurrence'] = [f"RRULE:{rrule}"]
            print(f"Creating recurring event with RRULE: {rrule}")

        # Insert the event
        event_result = service.events().insert(calendarId='primary', body=event).execute()
        print(f"Event created: {event_result.get('htmlLink')}")

        return {
            'success': True,
            'event_id': event_result.get('id'),
            'event_link': event_result.get('htmlLink'),
            'is_recurring': bool(rrule)
        }

    except HttpError as error:
        print(f"An error occurred creating calendar event: {error}")
        return {
            'success': False,
            'error': str(error)
        }
    except Exception as e:
        print(f"Unexpected error creating calendar event: {e}")
        return {
            'success': False,
            'error': str(e)
        }


def get_oauth_client_config():
    """Get OAuth client configuration from credentials file"""
    try:
        settings = Settings()

        return {
            'client_id': settings.google_client_id,
            'client_secret': settings.google_client_secret
        }
    except Exception as e:
        print(f"Error loading OAuth client config: {e}")
        return None
