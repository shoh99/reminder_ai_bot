#!/usr/bin/env python3
"""
Database migration script to add Google Calendar fields to the users table
"""
import sys
import os
from sqlalchemy import create_engine, text
import logging

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config.settings import Settings

settings = Settings()
db_user = settings.db_user
db_password = settings.db_password
db_host = settings.db_host
db_port = settings.db_port
db_name = settings.db_name

db_url = f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
engine = create_engine(db_url)

print(f"✅ Connected to database: {db_name}")


def add_tables_to_user_table():
    """Add Google Calendar fields to the users table"""
    print("🔄 Running database migration for Google Calendar integration")
    print("=" * 60)

    try:
        # Check if the columns already exist
        with engine.connect() as conn:
            # Check for google_access_token column
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'users' 
                AND column_name IN ('google_access_token', 'google_refresh_token', 'google_calendar_id', 'google_token_expires_at')
            """))
            existing_columns = [row[0] for row in result.fetchall()]

            if len(existing_columns) == 4:
                print("✅ All Google Calendar columns already exist. No migration needed.")
                return True

            print(f"📊 Found {len(existing_columns)} existing Google Calendar columns: {existing_columns}")

            # Add missing columns
            columns_to_add = [
                ("google_access_token", "TEXT"),
                ("google_refresh_token", "TEXT"),
                ("google_calendar_id", "VARCHAR(255)"),
                ("google_token_expires_at", "TIMESTAMP")
            ]

            for column_name, column_type in columns_to_add:
                if column_name not in existing_columns:
                    print(f"➕ Adding column: {column_name} ({column_type})")
                    conn.execute(text(f"""
                        ALTER TABLE users 
                        ADD COLUMN {column_name} {column_type}
                    """))
                    conn.commit()
                    print(f"✅ Added column: {column_name}")
                else:
                    print(f"⏭️  Column {column_name} already exists, skipping")

        print(f"\n🎉 Database migration completed successfully!")
        print(f"All Google Calendar integration columns are now available.")
        return True

    except Exception as e:
        print(f"\n❌ Migration failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


def add_column_to_table(table_name, column_name, column_type):
    try:
        with engine.connect() as conn:
            print(f"➕ Adding column: {column_name} ({column_type}) to {table_name} table")
            conn.execute(text(f"""
                                    ALTER TABLE {table_name} 
                                    ADD COLUMN {column_name} {column_type}
                                """))
            conn.commit()
            print(f"✅ Added column: {column_name}")

    except Exception as e:
        print(f"Failed to add new column: {e}")


if __name__ == "__main__":
    add_column_to_table("events", "google_event_id", "VARCHAR(255)")
