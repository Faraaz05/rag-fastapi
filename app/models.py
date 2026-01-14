from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Table, Enum, DateTime, JSON
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime
import enum

Base = declarative_base()


# File status enum
class FileStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PARTITIONING = "partitioning"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"

# Many-to-many association table for Project Members
project_members = Table(
    'project_members',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('project_id', Integer, ForeignKey('projects.id'), primary_key=True),
    Column('role', String, default='member')  # 'owner' or 'member'
)


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)

    # Relationship to projects where user is owner
    owned_projects = relationship('Project', back_populates='owner')
    # Relationship to projects where user is a member
    member_projects = relationship('Project', secondary=project_members, back_populates='members')


class Project(Base):
    __tablename__ = 'projects'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    owner_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Relationship to owner
    owner = relationship('User', back_populates='owned_projects')
    # Relationship to members
    members = relationship('User', secondary=project_members, back_populates='member_projects')
    # Relationship to files
    files = relationship('File', back_populates='project', cascade='all, delete-orphan')


class File(Base):
    __tablename__ = 'files'

    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(String, unique=True, index=True, nullable=False)  # UUID
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    original_filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    status = Column(Enum(FileStatus), default=FileStatus.UPLOADED, nullable=False)
    error_message = Column(String, nullable=True)
    processed_path = Column(String, nullable=True)  # Path to processed JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to project
    project = relationship('Project', back_populates='files')


class ChatSession(Base):
    __tablename__ = 'chat_sessions'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    name = Column(String, nullable=True)  # Optional session name
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship('User')
    project = relationship('Project')
    messages = relationship('ChatMessage', back_populates='session', cascade='all, delete-orphan')


class ChatMessage(Base):
    __tablename__ = 'chat_messages'

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('chat_sessions.id'), nullable=False)
    role = Column(String, nullable=False)  # 'user' or 'assistant'
    content = Column(String, nullable=False)
    sources = Column(JSON, nullable=True)  # Store citation metadata for assistant messages
    timestamp = Column(DateTime, default=datetime.utcnow)

    # Relationship to session
    session = relationship('ChatSession', back_populates='messages')
