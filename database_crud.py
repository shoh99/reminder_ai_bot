import uuid
from typing import List

from sqlalchemy.orm import Session
from sqlalchemy import select, update

from models import Users, Tag, Event, Schedule
from datetime import datetime


def get_or_create_user(session: Session, chat_id: int, user_name: str) -> Users:
    # look for an existing user
    stmt = select(Users).where(Users.chat_id == chat_id)
    user = session.scalars(stmt).first()

    if user:
        # update user_name if it has changed
        if user.user_name != user_name:
            user.user_name = user_name
            session.commit()

        return user

    else:
        # create a new user if not found
        new_user = Users(chat_id=chat_id, user_name=user_name)
        session.add(new_user)
        session.commit()
        session.refresh(new_user)
        return new_user


def add_user_phone(session: Session, chat_id: int, phone_number: str):
    stmt = select(Users).where(Users.chat_id == chat_id)
    user = session.scalars(stmt).one()
    user.phone_number = phone_number
    session.commit()


def create_scheduler(session: Session,
                     chat_id: int,
                     job_id: str,
                     type: str,
                     scheduled_time: datetime,
                     rrule: str,
                     status: str,

                     event):
    pass


def get_or_create_tags(session: Session, tag_names: List[str]) -> List[Tag]:
    """finds existing tags or creates new ones
    Returns a list of Tag objects
    """

    tags = []
    for name in tag_names:
        name = name.strip().lower()
        if not name:
            continue

        stmt = select(Tag).where(Tag.name == name)
        tag = session.scalars(stmt).first()

        if not tag:
            tag = Tag(name=name)
            session.add(tag)
            session.flush()
        tags.append(tag)

    session.commit()
    return tags


def create_full_event(session: Session,
                      user_id: uuid.UUID,
                      event_name: str,
                      description: str,
                      scheduled_time: datetime,
                      job_id: str,
                      event_type: str,
                      rrule: str = None,
                      tags: List[Tag] = None) -> Event:
    """Create a new schedule and a new Event, linking them and any associated tagas"""
    new_schedule = Schedule(
        job_id=job_id,
        scheduled_time=scheduled_time,
        type=event_type,
        rrule=rrule
    )
    session.add(new_schedule)
    session.flush()

    new_event = Event(
        user_id=user_id,
        schedule_id=new_schedule.id,
        event_name=event_name,
        description=description
    )

    if tags:
        new_event.tags.extend(tags)

    session.add(new_event)
    session.commit()
    session.refresh(new_event)


def get_active_reminders_by_user(session: Session, user_id: uuid.UUID) -> list[Event]:
    """retrieves all active events for a given user"""
    stmt = (
        select(Event)
        .join(Event.schedule)
        .where(Event.user_id == user_id)
        .where(Event.status == 'active')
        .order_by(Schedule.scheduled_time.asc())
    )

    return session.scalars(stmt).all()


def get_event_by_job_id(session: Session, job_id: uuid.UUID) -> Event:
    """retrieves an event by its associated scheduler job ID"""
    stmt = select(Event).join(Event.schedule).where(Schedule.job_id == job_id)
    return session.scalars(stmt).first()


def delete_event(session: Session, event: Event):
    """Deletes on even and its associated schedule"""
    session.delete(event)
    session.commit()


def update_scheduled_time(session: Session, scheduled_id: uuid.UUID, next_run_time: datetime):
    """Updates the scheduled_time for a recurring events schedule"""
    stmt = select(Schedule).where(Schedule.id == scheduled_id)
    schedule = session.scalars(stmt).one()
    schedule.scheduled_time = next_run_time
    session.commit()


def update_schedule_status(session: Session, job_id: str, status: str):
    """update scheduled job status"""
    stmt = select(Schedule).where(Schedule.job_id == job_id)
    schedule = session.scalars(stmt).one()
    schedule.status = status
    session.commit()


def update_event_status(session: Session, job_id: str, status: str):
    stmt = select(Event) \
        .join(Event.schedule) \
        .where(Schedule.job_id == job_id)

    event = session.scalars(stmt).one()
    event.status = status
    session.commit()
