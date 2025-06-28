import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

env_path = Path(__file__).parent.parent / '.env'


class Settings(BaseSettings):
    """
    Manages application settings using Pydantic.
    Loads settings from environment variables and a .env file.
    """
    model_config = SettingsConfigDict(env_file=env_path, env_file_encoding='utf-8', extra='ignore')

    # Required settings loaded from environment variables
    telegram_bot_token: str = Field(..., description="API token for the Telegram Bot")
    gemini_api_key: str = Field(..., description="API key for Google Gemini")
    db_user: str = Field(..., description="Postgres database name")
    db_password: str = Field(..., description="Postgres database password")
    db_host: str = Field(..., description="Database host address.")
    db_port: str = Field(..., description="Database port")
    db_name: str = Field(..., description="Database name")

    # Settings with default values
    reminder_db_file: str = '../remindme_ai.sqlite'
    timezone: str = "UTC"
    log_level: str = "INFO"

    # The modern way to do validation in Pydantic v2
    @field_validator('telegram_bot_token', 'gemini_api_key')
    @classmethod
    def validate_required_keys(cls, v: str, info: object) -> str:
        """Validate that the required API keys are not empty or None."""
        if not v:
            # The 'info.field_name' gives you the name of the field being validated
            raise ValueError(f'{info.field_name} is a required environment variable and cannot be empty.')
        return v
