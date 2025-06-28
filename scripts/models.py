import uuid
import logging

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Table, Index, UUID
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.sql import func

from config.settings import Settings


Base = declarative_base()

event_tags_association = Table(
    'event_tags',
    Base.metadata,
    Column('event_id', UUID(as_uuid=True), ForeignKey('events.id', ondelete='CASCADE'), primary_key=True),
    Column('tag_id', UUID(as_uuid=True), ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True),
)


class Users(Base):
    """
    Represents the users table
    """
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id = Column(Integer, unique=True, nullable=True, index=True)
    user_name = Column(String)
    timezone = Column(String, nullable=False, default='UTC')
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    phone_number = Column(String)
    language = Column(String)
    events = relationship("Event", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Users(id={self.id}, chat_id={self.chat_id}, user_name='{self.user_name}')>"


class Event(Base):
    """
    Represents the events table with a UUID primary key.
    """
    __tablename__ = 'events'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Foreign keys
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    schedule_id = Column(UUID(as_uuid=True), ForeignKey('schedules.id', ondelete='CASCADE'), unique=True,
                         nullable=False)

    event_name = Column(String, nullable=False)
    description = Column(Text)
    status = Column(String, nullable=False, default='active', index=True)

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    user = relationship("Users", back_populates="events")
    schedule = relationship(
        "Schedule",
        back_populates="event",
        uselist=False,
        cascade="all, delete-orphan",
        single_parent=True
    )
    tags = relationship("Tag", secondary=event_tags_association, back_populates="events")

    def __repr__(self):
        return f"<Event(id={self.id}, name='{self.event_name}', status='{self.status}')>"


class Schedule(Base):
    """
    Represents the schedules table with a UUID primary key
    """

    __tablename__ = "schedules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(String, unique=True, nullable=False)
    type = Column(String, nullable=False, default='one_time', index=True)
    scheduled_time = Column(DateTime, nullable=False)
    rrule = Column(String)
    status = Column(String, nullable=False, default="pending", index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    event = relationship("Event", back_populates="schedule")

    def __rep__(self):
        return f"<Schedule(id={self.id}, job_id='{self.job_id}', type='{self.type}')>"


class Tag(Base):
    """
    Represents the tags table.
    """
    __tablename__ = "tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, unique=True, nullable=False, index=True)
    description = Column(Text)

    events = relationship("Event", secondary=event_tags_association, back_populates="tags")

    def __repr__(self):
        return f"<Tag(id={self.id}, name='{self.name}')>"


def create_database(settings: Settings):
    """
    Initializes the database engine and creates all tables if they don't exist
    :return:
    """
    db_user = settings.db_user
    db_password = settings.db_password
    db_host = settings.db_host
    db_port = settings.db_port
    db_name = settings.db_name

    db_url = f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

    # Create the SQLAlchemy engine
    engine = create_engine(db_url, echo=True)

    logging.info(f"Connecting to PostgreSQL database: {db_url}")
    Base.metadata.create_all(engine)

    logging.info("Database setup complete. All tables are ready in PostgreSQL.")

