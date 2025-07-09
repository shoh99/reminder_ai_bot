# Reminder AI Bot

A sophisticated Telegram bot that uses AI to understand and set reminders from natural language text and voice messages.

## Features

- Natural Language Processing for creating reminders.
- Support for one-time and recurring events (daily, weekly, monthly).
- Timezone awareness for each user.
- Multi-language support.
- Voice message transcription for setting reminders.
- PostgreSQL backend for storing user and reminder data.

## Getting Started

### Prerequisites

- Python 3.9+
- Docker and Docker Compose
- Telegram Bot Token
- Google Cloud credentials for AI services

### Installation

1. **Clone the repository:**
   ```sh
   git clone https://github.com/shoh99/reminder_ai_bot.git
   cd reminder_ai_bot
   ```

2. **Set up environment variables:**
   Create a `.env` file and add your configuration (see `.env.example`).

3. **Build and run with Docker:**
   ```sh
   docker-compose up --build
   ```