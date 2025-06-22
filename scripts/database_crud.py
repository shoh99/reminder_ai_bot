# database_crud.py - Complete fix based on your actual models

import uuid
import logging
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session, joinedload

from scripts.models import Users, Event, Schedule, Tag

logger = logging.getLogger(__name__)


def get_or_create_user(session: Session, chat_id: int, user_name: str) -> Users:
    """Get existing user or create new one"""
    try:
        user = session.query(Users).filter(Users.chat_id == chat_id).first()
        if not user:
            user = Users(chat_id=chat_id, user_name=user_name)
            session.add(user)
            session.commit()
            logger.info(f"Created new user: {user_name} with chat_id: {chat_id}")
        return user
    except Exception as e:
        logger.error(f"Error getting/creating user {chat_id}: {e}")
        session.rollback()
        raise


def add_user_phone(session: Session, chat_id: int, phone_number: str) -> bool:
    """Add phone number to existing user"""
    try:
        user = session.query(Users).filter(Users.chat_id == chat_id).first()
        if user:
            user.phone_number = phone_number
            session.commit()
            logger.info(f"Added phone number for user {chat_id}")
            return True
        return False
    except Exception as e:
        logger.error(f"Error adding phone for user {chat_id}: {e}")
        session.rollback()
        return False


def get_active_reminders_by_user(session: Session, user_id: uuid.UUID) -> List[Event]:
    """
    FIXED: Get active reminders for a user with proper model names and relationships
    """
    try:
        # Use the correct singular model names: Event and Schedule
        reminders = session.query(Event).options(
            joinedload(Event.schedule)  # Load the schedule relationship
        ).filter(
            Event.user_id == user_id,
            Event.status == 'active'
        ).join(
            Schedule,  # Use singular Schedule model
            Event.schedule_id == Schedule.id
        ).order_by(
            Schedule.scheduled_time.asc()  # Use singular Schedule model
        ).all()

        logger.info(f"Found {len(reminders)} active reminders for user {user_id}")
        return reminders

    except Exception as e:
        logger.error(f"Failed to get active reminders for user {user_id}: {e}")
        session.rollback()
        return []


def get_event_by_job_id(session: Session, job_id: str) -> Optional[Event]:
    """Get event by job_id"""
    try:
        event = session.query(Event).options(
            joinedload(Event.schedule)
        ).join(
            Schedule,
            Event.schedule_id == Schedule.id
        ).filter(
            Schedule.job_id == job_id
        ).first()

        return event
    except Exception as e:
        logger.error(f"Error getting event by job_id {job_id}: {e}")
        session.rollback()
        return None

def get_schedule_by_job_id(session:Session, job_id: str) -> Schedule:
    try:
        schedule = session.query(Schedule).filter(Schedule.job_id == job_id).first()
        return schedule
    except Exception as e:
        logger.error(f"Error getting schedule by job_id {job_id}: {e}")
        session.rollback()
        return None


def update_event_status(session: Session, job_id: str, status: str) -> bool:
    """Update event status by job_id"""
    try:
        # Update the schedule status
        schedule = session.query(Schedule).filter(Schedule.job_id == job_id).first()
        if schedule:
            schedule.status = status

            # Also update the related event status
            event = session.query(Event).filter(Event.schedule_id == schedule.id).first()
            if event:
                if status == "complete":
                    event.status = "completed"
                elif status == "cancelled":
                    event.status = "cancelled"

            session.commit()
            logger.info(f"Updated status for job {job_id} to {status}")
            return True

        logger.warning(f"No schedule found for job_id {job_id}")
        return False

    except Exception as e:
        logger.error(f"Error updating status for job {job_id}: {e}")
        session.rollback()
        return False

def update_schedule_run_date(session: Session, job_id: str, next_run_date: datetime) -> bool:
    """update schedule next run time"""
    try:
        schedule = session.query(Schedule).filter(Schedule.job_id == job_id).first()
        if schedule:
            schedule.scheduled_time = next_run_date
            session.commit()
            logger.info(f"Update scheduled next run time for job: {job_id} to {next_run_date}")
            return True

        logger.warning(f"No schedule found for job_id {job_id}")
        return False
    except Exception as e:
        logger.error(f"Error updating next run time for job {job_id}: {e}")
        session.rollback()
        return False


def get_or_create_tags(session: Session, tag_names: List[str]) -> List[Tag]:
    """Get existing tags or create new ones"""
    tags = []
    try:
        for tag_name in tag_names:
            if not tag_name.strip():
                continue

            tag = session.query(Tag).filter(Tag.name == tag_name.strip()).first()
            if not tag:
                tag = Tag(name=tag_name.strip())
                session.add(tag)
            tags.append(tag)

        session.commit()
        return tags

    except Exception as e:
        logger.error(f"Error getting/creating tags: {e}")
        session.rollback()
        return []


def create_full_event(session: Session, user_id: uuid.UUID, event_name: str,
                      description: str, scheduled_time: datetime, job_id: str,
                      event_type: str = "one-time", rrule: Optional[str] = None,
                      tags: Optional[List[Tag]] = None) -> Optional[Event]:
    """Create a complete event with schedule"""
    try:
        # Create the schedule first
        schedule = Schedule(
            job_id=job_id,
            type=event_type,
            scheduled_time=scheduled_time,
            rrule=rrule,
            status="pending"
        )
        session.add(schedule)
        session.flush()  # Get the schedule ID

        # Create the event
        event = Event(
            user_id=user_id,
            schedule_id=schedule.id,
            event_name=event_name,
            description=description,
            status="active"
        )

        # Add tags if provided
        if tags:
            event.tags = tags

        session.add(event)
        session.commit()

        logger.info(f"Created event {event_name} with job_id {job_id}")
        return event

    except Exception as e:
        logger.error(f"Error creating event {event_name}: {e}")
        session.rollback()
        return None


def delete_event(session: Session, event_id: uuid.UUID) -> bool:
    """Delete an event and its schedule"""
    try:
        event = session.query(Event).filter(Event.id == event_id).first()
        if event:
            session.delete(event)  # Cascade will delete the schedule
            session.commit()
            logger.info(f"Deleted event {event_id}")
            return True
        return False

    except Exception as e:
        logger.error(f"Error deleting event {event_id}: {e}")
        session.rollback()
        return False