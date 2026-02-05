from pydantic import BaseModel
from datetime import datetime
from typing import Optional


# User Schemas
class UserCreate(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    is_active: bool

    class Config:
        from_attributes = True


# Token Schemas
class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None


# Project Schemas
class ProjectCreate(BaseModel):
    name: str


class ProjectResponse(BaseModel):
    id: int
    name: str
    owner_id: int

    class Config:
        from_attributes = True


class ProjectWithRoleResponse(BaseModel):
    id: int
    name: str
    owner_id: int
    role: str  # 'owner' or 'member'

    class Config:
        from_attributes = True


# Member Schemas
class MemberAdd(BaseModel):
    username: str


class MemberResponse(BaseModel):
    id: int
    username: str

    class Config:
        from_attributes = True


class MemberWithRoleResponse(BaseModel):
    id: int
    username: str
    role: str  # 'owner' or 'member'

    class Config:
        from_attributes = True


# Upload Schemas
class UploadResponse(BaseModel):
    message: str
    file_id: str
    original_filename: str
    project_id: int
    size: int
    status: str


# File Status Schemas
class FileStatusResponse(BaseModel):
    file_id: str
    original_filename: str
    status: str
    error_message: Optional[str] = None
    processed_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Transcript Schemas
class TranscriptUpload(BaseModel):
    meeting_name: str
    meeting_date: str  # YYYY-MM-DD format
    turns_per_chunk: int = 8
    overlap: int = 3


class TranscriptResponse(BaseModel):
    message: str
    file_id: str
    meeting_name: str
    meeting_date: str
    chunks_count: int
    speakers: list[str]
    collection_name: str
    status: str


# Audio Upload Schemas
class AudioUpload(BaseModel):
    audio_name: str
    audio_date: str  # YYYY-MM-DD format


class AudioUploadResponse(BaseModel):
    message: str
    file_id: str
    original_filename: str
    project_id: int
    size: int
    status: str
    audio_name: str
    audio_date: str


# Query/RAG Schemas
class QueryRequest(BaseModel):
    question: str
    filter: str = "unified"  # Options: "unified", "document", "transcript"
    top_k: int = 5


class SourceMetadata(BaseModel):
    chunk_id: str
    source_type: str  # "document" or "transcript"
    # Document-specific fields
    document_name: Optional[str] = None
    page_number: Optional[int] = None  # Changed to int to match ChromaDB metadata
    positions: Optional[list] = None
    # Transcript-specific fields
    meeting_name: Optional[str] = None
    meeting_date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    speakers: Optional[list[str]] = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceMetadata]


# Chat Schemas
class ChatSessionCreate(BaseModel):
    name: Optional[str] = None  # Optional session name


class ChatSessionResponse(BaseModel):
    id: int
    user_id: int
    project_id: int
    name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    message_count: Optional[int] = None  # Optional for list views

    class Config:
        from_attributes = True


class ChatMessageRequest(BaseModel):
    question: str
    filter: str = "unified"  # Options: "unified", "document", "transcript"
    top_k: int = 5


class ChatMessageResponse(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    sources: Optional[list[SourceMetadata]] = None
    timestamp: datetime

    class Config:
        from_attributes = True
