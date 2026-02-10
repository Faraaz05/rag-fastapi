from datetime import timedelta, datetime
from typing import Annotated
from pathlib import Path
import subprocess
import os

from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, Form
from fastapi import File as FileUpload
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.auth import (
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)

from app.core.config import settings
from app.models import Base, User, Project, project_members, File, FileStatus, ChatMessage, ChatSession
from app.schemas import (
    UserCreate,
    UserResponse,
    Token,
    ProjectCreate,
    ProjectResponse,
    ProjectWithRoleResponse,
    MemberAdd,
    MemberResponse,
    MemberWithRoleResponse,
    UploadResponse,
    FileStatusResponse,
    TranscriptUpload,
    TranscriptResponse,
    AudioUpload,
    AudioUploadResponse,
    QueryRequest,
    QueryResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
    AudioStreamURLResponse,
)
from app.services.storage import storage_service
from app.services.queue import queue_service
from app.services.transcript import process_transcript_file
from app.services.audio import create_audio_queue_message
from app.services.rag import quick_query, get_standalone_question, streaming_chat, query_with_filter

# Database setup
connect_args = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Auth & Project API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Current user dependency with database
def get_current_active_user(
    token: Annotated[str, Depends(get_current_user)],
    db: Session = Depends(get_db)
) -> User:
    """Get current user from token and validate in database."""
    username = token  # get_current_user returns username
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    return user


# Dependency to verify user is project owner
def is_project_owner(project_id: int, current_user: Annotated[User, Depends(get_current_active_user)], db: Session = Depends(get_db)) -> Project:
    """Verify that the current user is the owner of the project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    if project.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project owner can perform this action"
        )
    return project


# ==================== AUTH ROUTES ====================

@app.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user: UserCreate, db: Session = Depends(get_db)):
    """Register a new user."""
    # Check if username already exists
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    # Create new user
    hashed_password = get_password_hash(user.password)
    new_user = User(username=user.username, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.post("/auth/token", response_model=Token)
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(get_db)
):
    """Login to receive a JWT token (OAuth2 compatible)."""
    # Verify user exists
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/auth/me", response_model=UserResponse)
def get_current_user_info(
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Get current authenticated user information."""
    return current_user


# ==================== PROJECT ROUTES ====================

@app.get("/projects", response_model=list[ProjectWithRoleResponse])
def list_user_projects(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db)
):
    """List all projects for the current user with their role (owner or member)."""
    # Get all project memberships for the user
    memberships = db.execute(
        project_members.select().where(
            project_members.c.user_id == current_user.id
        )
    ).all()
    
    # Build response with project details and roles
    result = []
    for membership in memberships:
        project = db.query(Project).filter(Project.id == membership.project_id).first()
        if project:
            result.append(ProjectWithRoleResponse(
                id=project.id,
                name=project.name,
                owner_id=project.owner_id,
                role=membership.role
            ))
    
    return result


@app.post("/projects/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    project: ProjectCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db)
):
    """Create a new project. The current user becomes the owner."""
    new_project = Project(name=project.name, owner_id=current_user.id)
    db.add(new_project)
    db.commit()
    db.refresh(new_project)
    
    # Add owner to project members with 'owner' role
    stmt = project_members.insert().values(
        user_id=current_user.id,
        project_id=new_project.id,
        role='owner'
    )
    db.execute(stmt)
    db.commit()
    
    return new_project


@app.post("/projects/{project_id}/members", response_model=MemberResponse)
def add_member_to_project(
    project_id: int,
    member: MemberAdd,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db)
):
    """
    Add a member to a project.
    Only the project owner can add members.
    """
    # Check if project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Check if current user is the owner
    if project.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the project owner can add members"
        )
    
    # Check if user to add exists
    user_to_add = db.query(User).filter(User.username == member.username).first()
    if not user_to_add:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Check if user is already a member
    existing_member = db.execute(
        project_members.select().where(
            (project_members.c.user_id == user_to_add.id) &
            (project_members.c.project_id == project_id)
        )
    ).first()
    
    if existing_member:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member of this project"
        )
    
    # Add user as member
    stmt = project_members.insert().values(
        user_id=user_to_add.id,
        project_id=project_id,
        role='member'
    )
    db.execute(stmt)
    db.commit()
    
    return user_to_add


@app.get("/projects/{project_id}/members", response_model=list[MemberWithRoleResponse])
def list_project_members(
    project_id: int,
    project: Project = Depends(is_project_owner),
    db: Session = Depends(get_db)
):
    """
    List all members of a project with their roles.
    Only the project owner can view members.
    """
    # Get all members for this project
    memberships = db.execute(
        project_members.select().where(
            project_members.c.project_id == project_id
        )
    ).all()
    
    # Build response with user details and roles
    result = []
    for membership in memberships:
        user = db.query(User).filter(User.id == membership.user_id).first()
        if user:
            result.append(MemberWithRoleResponse(
                id=user.id,
                username=user.username,
                role=membership.role
            ))
    
    return result


@app.delete("/projects/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member_from_project(
    project_id: int,
    user_id: int,
    project: Project = Depends(is_project_owner),
    db: Session = Depends(get_db)
):
    """
    Remove a member from a project.
    Only the project owner can remove members.
    Cannot remove the owner themselves.
    """
    # Check if user to remove exists
    user_to_remove = db.query(User).filter(User.id == user_id).first()
    if not user_to_remove:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Prevent removing the owner
    if user_id == project.owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove the project owner"
        )
    
    # Check if user is a member
    membership = db.execute(
        project_members.select().where(
            (project_members.c.user_id == user_id) &
            (project_members.c.project_id == project_id)
        )
    ).first()
    
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of this project"
        )
    
    # Remove member
    db.execute(
        project_members.delete().where(
            (project_members.c.user_id == user_id) &
            (project_members.c.project_id == project_id)
        )
    )
    db.commit()
    
    return None


@app.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    project: Project = Depends(is_project_owner),
    db: Session = Depends(get_db)
):
    """
    Delete a project and all associated data.
    Only the project owner can delete the project.
    Removes ChromaDB collection, storage files, and database records.
    """
    try:
        # Step 1: Delete ChromaDB collection
        import chromadb
        
        chroma_client = chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT
        )
        
        collection_name = f"project_{project_id}"
        
        try:
            chroma_client.delete_collection(name=collection_name)
            print(f"🗑️  Deleted ChromaDB collection: {collection_name}")
        except Exception as e:
            print(f"⚠️  ChromaDB collection deletion warning: {e}")
            # Continue even if collection doesn't exist or deletion fails
        
        # Step 2: Delete all physical files from storage
        storage_service.delete_directory(project_id)
        
        # Step 3: Delete project from database (cascades to files and removes project_members)
        db.delete(project)
        db.commit()
        
        print(f"✅ Successfully deleted project {project_id}")
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting project: {str(e)}"
        )


@app.post("/projects/{project_id}/upload", response_model=list[UploadResponse], status_code=status.HTTP_202_ACCEPTED)
async def upload_file(
    project_id: int,
    files: list[UploadFile] = FileUpload(...),
    project: Project = Depends(is_project_owner),
    db: Session = Depends(get_db)
):
    """
    Upload multiple files to a project. Only project owner can upload.
    Accepts PDF and DOCX files. DOCX files will be converted to PDF automatically.
    The files are saved locally and messages are sent to the ingestion queue.
    """
    allowed_extensions = {".pdf", ".docx"}
    responses = []
    
    for file in files:
        # Validate file type
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type not supported for {file.filename}. Allowed types: PDF, DOCX"
            )
        
        # Save file to local storage
        file_info = await storage_service.save_file(project_id, file)
        
        # Create file record in database
        db_file = File(
            file_id=file_info["file_id"],
            project_id=project_id,
            original_filename=file_info["original_filename"],
            file_path=file_info["file_path"],
            size=file_info["size"],
            status=FileStatus.QUEUED  # Set to QUEUED when pushing to Redis
        )
        db.add(db_file)
        db.commit()
        db.refresh(db_file)
        
        # Prepare job message for the worker
        job = {
            "project_id": str(project_id),
            "file_id": file_info["file_id"],
            "s3_key": file_info["file_path"],  # This is the S3 key or local path
            "original_filename": file_info["original_filename"],
            "bucket_name": settings.S3_BUCKET_NAME,
        }

        # Push job to the ingestion queue
        try:
            success = queue_service.push_message(job)
            if not success:
                raise Exception("Failed to push message to queue")
            message = "File uploaded successfully and queued for processing"
        except Exception as e:
            # Update status to FAILED if queue push fails
            db_file.status = FileStatus.FAILED
            db_file.error_message = f"Failed to queue for processing: {str(e)}"
            db.commit()
            message = f"File uploaded but failed to queue for processing: {db_file.error_message}"
        
        responses.append(UploadResponse(
            message=message,
            file_id=file_info["file_id"],
            original_filename=file_info["original_filename"],
            project_id=project_id,
            size=file_info["size"],
            status=db_file.status.value
        ))
    
    return responses


@app.get("/projects/{project_id}/files/{file_id}/status", response_model=FileStatusResponse)
def get_file_status(
    project_id: int,
    file_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db)
):
    """
    Get the processing status of an uploaded file.
    Accessible by project owner and members.
    """
    # Check if user has access to the project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Check if user is owner or member
    is_member = db.execute(
        project_members.select().where(
            (project_members.c.user_id == current_user.id) &
            (project_members.c.project_id == project_id)
        )
    ).first()
    
    if project.owner_id != current_user.id and not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project"
        )
    
    # Get file record
    db_file = db.query(File).filter(
        File.file_id == file_id,
        File.project_id == project_id
    ).first()
    
    if not db_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    return db_file


@app.get("/projects/{project_id}/files", response_model=list[FileStatusResponse])
def list_project_files(
    project_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db)
):
    """
    List all files in a project.
    Accessible by project owner and members.
    """
    # Check if user has access to the project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Check if user is owner or member
    is_member = db.execute(
        project_members.select().where(
            (project_members.c.user_id == current_user.id) &
            (project_members.c.project_id == project_id)
        )
    ).first()
    
    if project.owner_id != current_user.id and not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project"
        )
    
    # Get all files for this project
    files = db.query(File).filter(
        File.project_id == project_id
    ).order_by(File.created_at.desc()).all()
    
    return files


@app.get("/projects/{project_id}/files/{file_id}")
def get_file(
    project_id: int,
    file_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db)
):
    """
    Get file by ID. Returns metadata for documents, JSON content for transcripts.
    Accessible by project owner and members.
    """
    # Check if user has access to the project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Check if user is owner or member
    is_member = db.execute(
        project_members.select().where(
            (project_members.c.user_id == current_user.id) &
            (project_members.c.project_id == project_id)
        )
    ).first()
    
    if project.owner_id != current_user.id and not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project"
        )
    
    # Get file record
    db_file = db.query(File).filter(
        File.file_id == file_id,
        File.project_id == project_id
    ).first()
    
    if not db_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    # Check if this is a transcript by file extension
    is_transcript = db_file.original_filename and (
        db_file.original_filename.endswith('.vtt') or 
        db_file.original_filename.endswith('.txt')
    )
    
    if is_transcript and db_file.processed_path:
        # Return JSON content for transcripts
        try:
            import json
            # Get content from S3 or local storage
            content_bytes = storage_service.get_file_content(db_file.processed_path)
            if content_bytes is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Transcript file not found"
                )
            
            transcript_data = json.loads(content_bytes.decode('utf-8'))
            
            return {
                "file_id": db_file.file_id,
                "original_filename": db_file.original_filename,
                "project_id": db_file.project_id,
                "size": db_file.size,
                "status": db_file.status.value,
                "created_at": db_file.created_at,
                "type": "transcript",
                "content": transcript_data
            }
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error parsing transcript file"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error reading transcript file: {str(e)}"
            )
    
    # Return metadata for documents
    return db_file


@app.get("/projects/{project_id}/files/{file_id}/download")
def download_file(
    project_id: int,
    file_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db)
):
    """
    Download the raw file (PDF, document, etc.).
    Accessible by project owner and members.
    """
    # Check if user has access to the project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Check if user is owner or member
    is_member = db.execute(
        project_members.select().where(
            (project_members.c.user_id == current_user.id) &
            (project_members.c.project_id == project_id)
        )
    ).first()
    
    if project.owner_id != current_user.id and not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project"
        )
    
    # Get file record
    db_file = db.query(File).filter(
        File.file_id == file_id,
        File.project_id == project_id
    ).first()
    
    if not db_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    # Check if this is a VTT/TXT transcript (these don't have raw files stored)
    is_vtt_transcript = db_file.original_filename and (
        db_file.original_filename.endswith('.vtt') or 
        db_file.original_filename.endswith('.txt')
    )
    
    if is_vtt_transcript:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcripts don't have downloadable raw files. Use the regular file endpoint to get JSON content."
        )
    
    # For audio/video files, reconstruct the raw file path
    # Worker changes file_path to "transcript_*" but raw file is at projects/{project_id}/raw/{file_id}.ext
    audio_extensions = ('.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac', '.wma', '.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv')
    is_audio = db_file.original_filename and db_file.original_filename.lower().endswith(audio_extensions)
    
    if is_audio:
        # Reconstruct raw file path
        file_extension = Path(db_file.original_filename).suffix
        actual_file_path = f"projects/{project_id}/raw/{db_file.file_id}{file_extension}"
    else:
        # For documents, use the stored file_path
        actual_file_path = db_file.file_path
    
    # Generate download URL or serve file
    if settings.USE_S3:
        # Proxy the file through backend to avoid CORS issues
        try:
            # Determine media type based on file extension
            import mimetypes
            media_type = mimetypes.guess_type(db_file.original_filename)[0] or "application/octet-stream"
            
            # Stream file content directly
            from fastapi.responses import StreamingResponse
            
            return StreamingResponse(
                storage_service.get_file_stream(actual_file_path),
                media_type=media_type,
                headers={"Content-Disposition": f"attachment; filename={db_file.original_filename}"}
            )
        except Exception as e:
            if "File not found" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="File not found"
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve file: {str(e)}"
            )
    else:
        # Local file serving
        import os
        if not actual_file_path or not os.path.exists(actual_file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found on disk"
            )
        
        # Determine media type based on file extension
        import mimetypes
        media_type = mimetypes.guess_type(db_file.original_filename)[0] or "application/octet-stream"
        
        # Return the file
        return FileResponse(
            path=actual_file_path,
            media_type=media_type,
            filename=db_file.original_filename
        )


@app.get("/projects/{project_id}/files/{file_id}/transcript")
def download_transcript(
    project_id: int,
    file_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db)
):
    """
    Download the transcript JSON for an audio/video file.
    Returns the processed transcript in JSON format with turns, speakers, and timestamps.
    Accessible by project owner and members.
    """
    # Check if user has access to the project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Check if user is owner or member
    is_member = db.execute(
        project_members.select().where(
            (project_members.c.user_id == current_user.id) &
            (project_members.c.project_id == project_id)
        )
    ).first()
    
    if project.owner_id != current_user.id and not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project"
        )
    
    # Get file record
    db_file = db.query(File).filter(
        File.file_id == file_id,
        File.project_id == project_id
    ).first()
    
    if not db_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    # Check if this is an audio/video file
    audio_extensions = ('.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac', '.wma', '.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv')
    is_audio = db_file.original_filename and db_file.original_filename.lower().endswith(audio_extensions)
    
    if not is_audio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint is only for audio/video files. Use the document download endpoint for documents."
        )
    
    # Check if file has been processed
    if db_file.status != FileStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Transcript not ready yet. Current status: {db_file.status}"
        )
    
    # Check if processed_path exists
    if not db_file.processed_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript not found for this file"
        )
    
    # Get transcript from storage
    if settings.USE_S3:
        # Fetch from S3
        try:
            return StreamingResponse(
                storage_service.get_file_stream(db_file.processed_path),
                media_type="application/json",
                headers={"Content-Disposition": f"attachment; filename={file_id}_transcript.json"}
            )
        except Exception as e:
            if "File not found" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Transcript file not found in storage"
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve transcript: {str(e)}"
            )
    else:
        # Local file serving
        # The processed_path for local storage is typically: data/processed/{project_id}/{file_id}.json
        local_transcript_path = Path(f"data/processed/{project_id}/{file_id}.json")
        
        if not local_transcript_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transcript file not found on disk"
            )
        
        # Return the JSON file
        return FileResponse(
            path=str(local_transcript_path),
            media_type="application/json",
            filename=f"{file_id}_transcript.json"
        )


@app.get("/projects/{project_id}/files/{file_id}/audio-stream", response_model=AudioStreamURLResponse)
def get_audio_stream_url(
    project_id: int,
    file_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db),
    expires_in: int = 3600
):
    """
    Get a presigned URL for streaming the processed/compressed audio file.
    The URL supports HTTP Range requests, allowing the frontend to:
    - Seek to specific timestamps without downloading the entire file
    - Stream audio progressively
    - Jump to different positions in the audio
    
    Accessible by project owner and members.
    
    Args:
        project_id: Project ID
        file_id: File ID
        expires_in: URL expiration time in seconds (default: 3600 = 1 hour)
    
    Returns:
        Presigned URL for audio streaming
    """
    # Check if user has access to the project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Check if user is owner or member
    is_member = db.execute(
        project_members.select().where(
            (project_members.c.user_id == current_user.id) &
            (project_members.c.project_id == project_id)
        )
    ).first()
    
    if project.owner_id != current_user.id and not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project"
        )
    
    # Get file record
    db_file = db.query(File).filter(
        File.file_id == file_id,
        File.project_id == project_id
    ).first()
    
    if not db_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    # Check if this is an audio/video file
    audio_extensions = ('.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac', '.wma', '.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv')
    is_audio = db_file.original_filename and db_file.original_filename.lower().endswith(audio_extensions)
    
    if not is_audio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint is only for audio/video files"
        )
    
    # Check if file has been processed
    if db_file.status != FileStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Audio not ready yet. Current status: {db_file.status}"
        )
    
    # Construct path to compressed MP3 file
    # The worker saves compressed audio at: projects/{project_id}/processed/{file_id}.mp3
    compressed_audio_path = f"projects/{project_id}/processed/{file_id}.mp3"
    
    # Generate presigned URL or return local path
    if settings.USE_S3:
        try:
            # Generate presigned URL with specified expiration
            presigned_url = storage_service.get_file_url(
                file_path=compressed_audio_path,
                expires_in=expires_in
            )
            
            if not presigned_url:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Compressed audio file not found in storage"
                )
            
            return AudioStreamURLResponse(
                url=presigned_url,
                expires_in=expires_in,
                file_id=file_id,
                original_filename=db_file.original_filename
            )
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate streaming URL: {str(e)}"
            )
    else:
        # For local storage, return a route that serves the file
        # Frontend can use this route directly with HTML5 audio element
        local_audio_path = Path(f"data/processed/{project_id}/{file_id}.mp3")
        
        if not local_audio_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Compressed audio file not found on disk"
            )
        
        # Return a local URL that can be used for streaming
        # The frontend will call another endpoint to actually stream the file
        local_url = f"/projects/{project_id}/files/{file_id}/stream-local"
        
        return AudioStreamURLResponse(
            url=local_url,
            expires_in=expires_in,
            file_id=file_id,
            original_filename=db_file.original_filename
        )


@app.get("/projects/{project_id}/files/{file_id}/stream-local")
def stream_local_audio(
    project_id: int,
    file_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db)
):
    """
    Stream local audio file with Range request support.
    This endpoint is only used when USE_S3 is False.
    """
    # Same authentication checks
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    is_member = db.execute(
        project_members.select().where(
            (project_members.c.user_id == current_user.id) &
            (project_members.c.project_id == project_id)
        )
    ).first()
    
    if project.owner_id != current_user.id and not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # Get file and verify
    db_file = db.query(File).filter(
        File.file_id == file_id,
        File.project_id == project_id
    ).first()
    
    if not db_file or db_file.status != FileStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found or not ready"
        )
    
    # Serve the local MP3 file with Range support
    local_audio_path = Path(f"data/processed/{project_id}/{file_id}.mp3")
    
    if not local_audio_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found"
        )
    
    # FileResponse automatically supports Range requests
    return FileResponse(
        path=str(local_audio_path),
        media_type="audio/mpeg",
        filename=f"{file_id}.mp3"
    )


@app.get("/projects/{project_id}/download/document/{document_name}")
def download_by_document_name(
    project_id: int,
    document_name: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db)
):
    """
    Download a document by its original filename.
    Accessible by project owner and members.
    """
    # Check if user has access to the project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Check if user is owner or member
    is_member = db.execute(
        project_members.select().where(
            (project_members.c.user_id == current_user.id) &
            (project_members.c.project_id == project_id)
        )
    ).first()
    
    if project.owner_id != current_user.id and not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project"
        )
    
    # Find file by original filename
    db_file = db.query(File).filter(
        File.project_id == project_id,
        File.original_filename == document_name
    ).first()
    
    if not db_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_name}' not found"
        )
    
    # Check if this is a transcript
    is_transcript = db_file.original_filename and (
        db_file.original_filename.endswith('.vtt') or 
        db_file.original_filename.endswith('.txt')
    )
    
    if is_transcript:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use /download/transcript/{meeting_name} for transcript files"
        )
    
    # Generate download URL or serve file
    if settings.USE_S3:
        # Proxy the file through backend to avoid CORS issues
        try:
            # Determine media type based on file extension
            import mimetypes
            media_type = mimetypes.guess_type(db_file.original_filename)[0] or "application/octet-stream"
            
            # Stream file content directly
            from fastapi.responses import StreamingResponse
            
            return StreamingResponse(
                storage_service.get_file_stream(db_file.file_path),
                media_type=media_type,
                headers={"Content-Disposition": f"attachment; filename={db_file.original_filename}"}
            )
        except Exception as e:
            if "File not found" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="File not found"
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve file: {str(e)}"
            )
    else:
        # Local file serving
        import os
        if not db_file.file_path or not os.path.exists(db_file.file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found on disk"
            )
        
        # Determine media type
        import mimetypes
        media_type = mimetypes.guess_type(db_file.original_filename)[0] or "application/octet-stream"
        
        return FileResponse(
            path=db_file.file_path,
            media_type=media_type,
            filename=db_file.original_filename
        )


@app.get("/projects/{project_id}/download/transcript/{meeting_name}")
def download_by_meeting_name(
    project_id: int,
    meeting_name: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db)
):
    """
    Get transcript JSON by meeting name.
    Accessible by project owner and members.
    """
    # Check if user has access to the project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Check if user is owner or member
    is_member = db.execute(
        project_members.select().where(
            (project_members.c.user_id == current_user.id) &
            (project_members.c.project_id == project_id)
        )
    ).first()
    
    if project.owner_id != current_user.id and not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project"
        )
    
    # Find transcript by file_path pattern (transcript_{meeting_name}_{date})
    # Use LIKE to match the pattern
    from sqlalchemy import or_, func
    db_files = db.query(File).filter(
        File.project_id == project_id,
        File.file_path.like(f"transcript_{meeting_name}_%")
    ).all()
    
    if not db_files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transcript for meeting '{meeting_name}' not found"
        )
    
    # Use the first match (should be unique per meeting name)
    db_file = db_files[0]
    
    # Verify it's a processed transcript (has JSON output)
    # Allow both VTT/TXT files and audio/video files that have been processed
    allowed_original_extensions = ('.vtt', '.txt', '.mp3', '.wav', '.m4a', '.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv')
    is_valid_source = db_file.original_filename and db_file.original_filename.lower().endswith(allowed_original_extensions)
    
    if not is_valid_source:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is not a valid transcript or audio source"
        )
    
    # Return JSON content
    if db_file.processed_path:
        try:
            import json
            # Get content from S3 or local storage
            content_bytes = storage_service.get_file_content(db_file.processed_path)
            if content_bytes is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Transcript has not been processed yet"
                )
            
            transcript_data = json.loads(content_bytes.decode('utf-8'))
            
            return {
                "file_id": db_file.file_id,
                "original_filename": db_file.original_filename,
                "project_id": db_file.project_id,
                "size": db_file.size,
                "status": db_file.status.value,
                "created_at": db_file.created_at,
                "type": "transcript",
                "content": transcript_data
            }
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error parsing transcript file"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error reading transcript file: {str(e)}"
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript has not been processed yet"
        )


@app.delete("/projects/{project_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(
    project_id: int,
    file_id: str,
    project: Project = Depends(is_project_owner),
    db: Session = Depends(get_db)
):
    """
    Delete a file from the project. Only project owner can delete.
    Removes the file record, deletes chunks from ChromaDB, and removes the physical file.
    """
    # Get file record
    db_file = db.query(File).filter(
        File.file_id == file_id,
        File.project_id == project_id
    ).first()
    
    if not db_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    try:
        # Step 1: Delete chunks from ChromaDB
        import chromadb
        
        chroma_client = chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT
        )
        
        collection_name = f"project_{project_id}"
        
        try:
            collection = chroma_client.get_collection(name=collection_name)
            
            # Determine file type
            is_transcript = db_file.processed_path and db_file.processed_path.endswith('.json')
            audio_extensions = ('.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac', '.wma', '.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv')
            is_audio = db_file.original_filename and db_file.original_filename.lower().endswith(audio_extensions)
            
            chunks_to_delete = []
            
            if is_audio and is_transcript:
                # Audio transcripts: chunk IDs follow pattern {file_id}_chunk_{index}
                # Get all chunks and filter by file_id prefix
                print(f"🔍 Searching ChromaDB for audio chunks with file_id: {file_id}")
                try:
                    all_chunks = collection.get(include=[])
                    
                    # Filter chunks that start with file_id
                    for chunk_id in all_chunks['ids']:
                        if chunk_id.startswith(f"{file_id}_chunk_"):
                            chunks_to_delete.append(chunk_id)
                except Exception as e:
                    print(f"⚠️  Error getting chunks: {e}")
                
            elif is_transcript:
                # VTT/Meeting transcripts: search by meeting_name
                if db_file.file_path.startswith("transcript_"):
                    meeting_info = db_file.file_path.replace("transcript_", "").rsplit("_", 1)
                    if len(meeting_info) > 0:
                        meeting_name = meeting_info[0]
                        try:
                            results = collection.get(
                                where={"meeting_name": meeting_name},
                                include=[]
                            )
                            chunks_to_delete = results['ids']
                            print(f"🔍 Searching ChromaDB for meeting_name: {meeting_name}")
                        except Exception as e:
                            print(f"⚠️  Error searching meeting chunks: {e}")
            else:
                # Documents: search by document_name
                try:
                    results = collection.get(
                        where={"document_name": db_file.original_filename},
                        include=[]
                    )
                    chunks_to_delete = results['ids']
                    print(f"🔍 Searching ChromaDB for document_name: {db_file.original_filename}")
                except Exception as e:
                    print(f"⚠️  Error searching document chunks: {e}")
            
            # Delete chunks if any found
            if chunks_to_delete:
                collection.delete(ids=chunks_to_delete)
                print(f"🗑️  Deleted {len(chunks_to_delete)} chunks from ChromaDB for {db_file.original_filename}")
            else:
                print(f"⚠️  No chunks found in ChromaDB for {db_file.original_filename}")
        except Exception as e:
            print(f"⚠️  ChromaDB deletion warning: {e}")
            # Continue even if ChromaDB deletion fails
        
        # Step 2: Delete physical files from storage
        deleted_files = []
        
        # For audio/video files, reconstruct the raw file path
        # Worker changes file_path to "transcript_*" for searchability, but raw file is at projects/{project_id}/raw/{file_id}.ext
        audio_extensions = ('.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac', '.wma', '.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv')
        is_audio = db_file.original_filename and db_file.original_filename.lower().endswith(audio_extensions)
        
        if is_audio:
            # Reconstruct raw file path from file_id and original extension
            from pathlib import Path
            file_extension = Path(db_file.original_filename).suffix
            raw_file_path = f"projects/{project_id}/raw/{file_id}{file_extension}"
            
            try:
                success = storage_service.delete_file(raw_file_path)
                if success:
                    deleted_files.append(f"raw audio: {raw_file_path}")
                    print(f"🗑️  Deleted raw audio: {raw_file_path}")
                else:
                    print(f"⚠️  Failed to delete raw audio: {raw_file_path}")
            except Exception as e:
                print(f"⚠️  Error deleting raw audio: {e}")
        else:
            # For non-audio files, use the stored file_path
            if db_file.file_path:
                try:
                    success = storage_service.delete_file(db_file.file_path)
                    if success:
                        deleted_files.append(f"raw file: {db_file.file_path}")
                        print(f"🗑️  Deleted raw file: {db_file.file_path}")
                    else:
                        print(f"⚠️  Failed to delete raw file: {db_file.file_path}")
                except Exception as e:
                    print(f"⚠️  Error deleting raw file: {e}")
        
        # Delete processed JSON if exists
        if db_file.processed_path:
            try:
                success = storage_service.delete_file(db_file.processed_path)
                if success:
                    deleted_files.append(f"processed JSON: {db_file.processed_path}")
                    print(f"🗑️  Deleted processed JSON: {db_file.processed_path}")
                else:
                    print(f"⚠️  Failed to delete processed JSON: {db_file.processed_path}")
            except Exception as e:
                print(f"⚠️  Error deleting processed JSON: {e}")
        
        # Delete compressed audio file if it's an audio/video file (worker creates this)
        if is_audio:
            compressed_audio_path = f"projects/{project_id}/processed/{file_id}.mp3"
            try:
                success = storage_service.delete_file(compressed_audio_path)
                if success:
                    deleted_files.append(f"compressed audio: {compressed_audio_path}")
                    print(f"🗑️  Deleted compressed audio: {compressed_audio_path}")
                else:
                    print(f"⚠️  Compressed audio not found (may not exist): {compressed_audio_path}")
            except Exception as e:
                print(f"⚠️  Error deleting compressed audio: {e}")
        
        # Step 3: Delete file record from database
        db.delete(db_file)
        db.commit()
        
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting file: {str(e)}"
        )


@app.post("/projects/{project_id}/transcripts", response_model=TranscriptResponse)
async def upload_transcript(
    project_id: int,
    file: UploadFile = FileUpload(...),
    meeting_name: str = Form(...),
    meeting_date: str = Form(...),
    turns_per_chunk: int = Form(8),
    overlap: int = Form(3),
    current_user: Annotated[User, Depends(is_project_owner)] = None,
    db: Session = Depends(get_db)
):
    """
    Upload and process a VTT transcript file.
    Instantly processes the transcript and stores in ChromaDB.
    Only project owners can upload transcripts.
    """
    # Validate file type
    if not file.filename.endswith(('.vtt', '.txt')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .vtt or .txt files are allowed"
        )
    
    # Validate required parameters
    if not meeting_name or not meeting_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="meeting_name and meeting_date are required"
        )
    
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    try:
        # Read VTT content
        vtt_content = (await file.read()).decode('utf-8')
        file_size = len(vtt_content.encode('utf-8'))
        
        # Generate unique file ID
        import uuid
        file_id = str(uuid.uuid4())
        
        # Create File record
        db_file = File(
            file_id=file_id,
            original_filename=file.filename,
            file_path=f"transcript_{meeting_name}_{meeting_date}",
            project_id=project_id,
            size=file_size,
            status=FileStatus.PARTITIONING  # Set initial status
        )
        db.add(db_file)
        db.commit()
        db.refresh(db_file)
        
        # Parse transcript for JSON export
        from app.services.transcript import parse_vtt_to_turns, format_transcript_for_export
        turns = parse_vtt_to_turns(vtt_content)
        transcript_json = format_transcript_for_export(turns, meeting_name, meeting_date)
        
        # Save JSON to storage
        json_path = storage_service.save_json_transcript(
            project_id=project_id,
            file_id=file_id,
            transcript_data=transcript_json
        )
        
        # Process transcript immediately (in-process)
        result = process_transcript_file(
            vtt_content=vtt_content,
            meeting_name=meeting_name,
            meeting_date=meeting_date,
            project_id=project_id,
            project_name=project.name,
            turns_per_chunk=turns_per_chunk,
            overlap=overlap
        )
        
        if result["success"]:
            # Update file status to COMPLETED and save JSON path
            db_file.status = FileStatus.COMPLETED
            db_file.processed_path = json_path  # Store JSON path
            db.commit()
            
            return TranscriptResponse(
                message="Transcript processed and stored successfully",
                file_id=file_id,
                meeting_name=result["meeting_name"],
                meeting_date=result["meeting_date"],
                chunks_count=result["chunks_count"],
                speakers=result["speakers"],
                collection_name=result["collection_name"],
                status=FileStatus.COMPLETED.value
            )
        else:
            # Update file status to FAILED
            db_file.status = FileStatus.FAILED
            db_file.error_message = result.get("error", "Unknown error")
            db.commit()
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("error", "Failed to process transcript")
            )
    
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is not valid UTF-8 encoded text"
        )
    except Exception as e:
        # Update file status to FAILED if exists
        if 'db_file' in locals():
            db_file.status = FileStatus.FAILED
            db_file.error_message = str(e)
            db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing transcript: {str(e)}"
        )


@app.post("/projects/{project_id}/audio", response_model=AudioUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_audio(
    project_id: int,
    file: UploadFile = FileUpload(...),
    audio_name: str = Form(...),
    audio_date: str = Form(...),
    current_user: Annotated[User, Depends(is_project_owner)] = None,
    db: Session = Depends(get_db)
):
    """
    Upload an audio or video file for processing.
    File is uploaded to S3 raw directory and queued for worker processing.
    Worker will handle video-to-audio conversion, transcription with diarization, and embedding.
    Only project owners can upload audio/video files.
    """
    # Validate file type - support common audio and video formats
    allowed_extensions = (
        '.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac', '.wma',  # Audio formats
        '.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv'   # Video formats
    )
    if not file.filename.lower().endswith(allowed_extensions):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only audio/video files are allowed ({', '.join(allowed_extensions)})"
        )
    
    # Validate required parameters
    if not audio_name or not audio_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="audio_name and audio_date are required"
        )
    
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    try:
        # Save audio file to S3/local storage
        file_info = await storage_service.save_file(project_id=project_id, file=file)
        
        file_id = file_info["file_id"]
        file_path = file_info["file_path"]
        file_size = file_info["size"]
        
        # Create File record in database
        db_file = File(
            file_id=file_id,
            original_filename=file.filename,
            file_path=file_path,
            project_id=project_id,
            size=file_size,
            status=FileStatus.QUEUED  # Set status to QUEUED for worker processing
        )
        db.add(db_file)
        db.commit()
        db.refresh(db_file)
        
        # Create queue message for audio worker
        queue_message = create_audio_queue_message(
            file_id=file_id,
            project_id=project_id,
            project_name=project.name,
            original_filename=file.filename,
            file_path=file_path,
            audio_name=audio_name,
            audio_date=audio_date,
            file_size=file_size
        )
        
        # Push message to audio queue
        queue_pushed = queue_service.push_audio_message(queue_message)
        
        if not queue_pushed:
            raise Exception("Failed to push audio to processing queue")
        
        return AudioUploadResponse(
            message="Audio file uploaded and queued for processing",
            file_id=file_id,
            original_filename=file.filename,
            project_id=project_id,
            size=file_size,
            status=FileStatus.QUEUED.value,
            audio_name=audio_name,
            audio_date=audio_date
        )
        
    except HTTPException:
        raise
    except Exception as e:
        # Update file status to FAILED if exists
        if 'db_file' in locals():
            db_file.status = FileStatus.FAILED
            db_file.error_message = str(e)
            db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading audio file: {str(e)}"
        )

@app.post("/projects/{project_id}/query", response_model=QueryResponse)
def query_project(
    project_id: int,
    query_request: QueryRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db)
):
    """
    Query the project's RAG system with source filtering.
    Accessible by project owners and members.
    """
    # Check if user has access to the project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Check if user is owner or member
    is_member = db.execute(
        project_members.select().where(
            (project_members.c.user_id == current_user.id) &
            (project_members.c.project_id == project_id)
        )
    ).first()
    
    if project.owner_id != current_user.id and not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project"
        )
    
    # Validate filter parameter
    if query_request.filter not in ["unified", "document", "transcript"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filter. Must be 'unified', 'document', or 'transcript'"
        )
    
    try:
        # Execute RAG query
        result = quick_query(
            question=query_request.question,
            project_id=project_id,
            filter_type=query_request.filter,
            top_k=query_request.top_k
        )
        
        return QueryResponse(
            answer=result["answer"],
            sources=result["sources"]
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing query: {str(e)}"
        )


# ================== Chat Session Endpoints ==================

@app.post("/projects/{project_id}/sessions", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
def create_chat_session(
    project_id: int,
    session_data: ChatSessionCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db)
):
    """
    Create a new chat session for the current user in a project.
    """
    # Check if user has access to the project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Check if user is owner or member
    is_member = db.execute(
        project_members.select().where(
            (project_members.c.user_id == current_user.id) &
            (project_members.c.project_id == project_id)
        )
    ).first()
    
    if project.owner_id != current_user.id and not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project"
        )
    
    # Create new session
    new_session = ChatSession(
        user_id=current_user.id,
        project_id=project_id,
        name=session_data.name or f"Chat {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    
    return new_session


@app.get("/projects/{project_id}/sessions", response_model=list[ChatSessionResponse])
def list_chat_sessions(
    project_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db)
):
    """
    List all chat sessions for the current user in a project.
    """
    # Check if user has access to the project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Check if user is owner or member
    is_member = db.execute(
        project_members.select().where(
            (project_members.c.user_id == current_user.id) &
            (project_members.c.project_id == project_id)
        )
    ).first()
    
    if project.owner_id != current_user.id and not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project"
        )
    
    # Get all sessions for this user in this project
    sessions = db.query(ChatSession).filter(
        ChatSession.user_id == current_user.id,
        ChatSession.project_id == project_id
    ).order_by(ChatSession.updated_at.desc()).all()
    
    # Add message count to each session
    from sqlalchemy import func
    result = []
    for session in sessions:
        msg_count = db.query(func.count(ChatMessage.id)).filter(
            ChatMessage.session_id == session.id
        ).scalar()
        
        session_dict = {
            "id": session.id,
            "user_id": session.user_id,
            "project_id": session.project_id,
            "name": session.name,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "message_count": msg_count
        }
        result.append(ChatSessionResponse(**session_dict))
    
    return result


@app.delete("/projects/{project_id}/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat_session(
    project_id: int,
    session_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db)
):
    """
    Delete a chat session and all its messages.
    """
    # Get session and verify ownership
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.project_id == project_id,
        ChatSession.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or access denied"
        )
    
    db.delete(session)
    db.commit()
    
    return None


@app.post("/projects/{project_id}/chat/{session_id}")
async def chat_with_project(
    project_id: int,
    session_id: int,
    chat_request: ChatMessageRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db)
):
    """
    History-aware streaming chat with the project's RAG system.
    Uses conversation history to contextualize questions.
    Streams the response with Server-Sent Events.
    """
    # Validate that session exists and belongs to the user
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.project_id == project_id,
        ChatSession.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or access denied"
        )
    
    # Check if user has access to the project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Check if user is owner or member
    is_member = db.execute(
        project_members.select().where(
            (project_members.c.user_id == current_user.id) &
            (project_members.c.project_id == project_id)
        )
    ).first()
    
    if project.owner_id != current_user.id and not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project"
        )
    
    # Validate filter parameter
    if chat_request.filter not in ["unified", "document", "transcript"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filter. Must be 'unified', 'document', or 'transcript'"
        )
    
    try:
        # Step 1: Fetch last 5 messages from database
        history_messages = db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).order_by(ChatMessage.timestamp.desc()).limit(5).all()
        
        # Reverse to get chronological order
        history_messages.reverse()
        
        # Convert to dict format for rewriter
        history = [
            {"role": msg.role, "content": msg.content}
            for msg in history_messages
        ]
        
        # Step 2: Save user message to database
        user_message = ChatMessage(
            session_id=session_id,
            role="user",
            content=chat_request.question
        )
        db.add(user_message)
        
        # Update session's updated_at timestamp
        session.updated_at = datetime.utcnow()
        
        db.commit()
        
        # Step 3: Generate standalone question using rewriter
        standalone_question = get_standalone_question(chat_request.question, history)
        print(f"🔄 Rewritten question: {standalone_question}")
        
        # Step 4: Retrieve chunks using the standalone question
        retrieved_chunks = query_with_filter(
            question=standalone_question,
            project_id=project_id,
            top_k=chat_request.top_k,
            filter_type=chat_request.filter
        )
        
        if not retrieved_chunks:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No relevant information found in the database"
            )
        
        # Build chunks metadata (same as in generate_answer)
        chunks_metadata = {}
        for i, chunk in enumerate(retrieved_chunks):
            chunk_id = i + 1
            source_type = chunk.metadata.get("source_type", "document")
            
            if source_type == "meeting_transcript":
                import json as json_lib
                speakers_json = chunk.metadata.get("speakers_in_chunk", "[]")
                speakers = json_lib.loads(speakers_json) if isinstance(speakers_json, str) else speakers_json
                
                chunks_metadata[chunk_id] = {
                    "source_type": "meeting_transcript",
                    "meeting_name": chunk.metadata.get("meeting_name"),
                    "meeting_date": chunk.metadata.get("meeting_date"),
                    "start_time": chunk.metadata.get("start_time"),
                    "end_time": chunk.metadata.get("end_time"),
                    "speakers": speakers
                }
            else:
                import json as json_lib
                positions_str = chunk.metadata.get("positions", "[]")
                positions = json_lib.loads(positions_str) if isinstance(positions_str, str) else positions_str
                
                chunks_metadata[chunk_id] = {
                    "source_type": "document",
                    "page": chunk.metadata.get("page_number", "N/A"),
                    "document": chunk.metadata.get("document_name", "document.pdf"),
                    "positions": positions
                }
        
        # Step 5: Stream the response
        async def event_generator():
            full_answer = ""
            async for event in streaming_chat(
                question=chat_request.question,
                history=history,
                chunks=retrieved_chunks,
                chunks_metadata=chunks_metadata
            ):
                # Collect full answer from text events
                if 'data:' in event:
                    try:
                        import json as json_lib
                        data_str = event.replace('data: ', '').strip()
                        if data_str and data_str != '[DONE]':
                            data = json_lib.loads(data_str)
                            if data.get('type') == 'text':
                                full_answer += data.get('content', '')
                    except:
                        pass
                
                yield event
            
            # Step 6: Save assistant response to database after streaming completes
            if full_answer:
                # Convert chunks_metadata to sources list
                sources_list = []
                for chunk_id, metadata in chunks_metadata.items():
                    if metadata["source_type"] == "meeting_transcript":
                        sources_list.append({
                            "chunk_id": str(chunk_id),
                            "source_type": "transcript",
                            "meeting_name": metadata.get("meeting_name"),
                            "meeting_date": metadata.get("meeting_date"),
                            "start_time": metadata.get("start_time"),
                            "end_time": metadata.get("end_time"),
                            "speakers": metadata.get("speakers")
                        })
                    else:
                        sources_list.append({
                            "chunk_id": str(chunk_id),
                            "source_type": "document",
                            "document_name": metadata.get("document"),
                            "page_number": metadata.get("page"),
                            "positions": metadata.get("positions")
                        })
                
                assistant_message = ChatMessage(
                    session_id=session_id,
                    role="assistant",
                    content=full_answer,
                    sources=sources_list if sources_list else None
                )
                db.add(assistant_message)
                
                # Update session's updated_at timestamp
                session.updated_at = datetime.utcnow()
                
                db.commit()
        
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing chat: {str(e)}"
        )


@app.get("/projects/{project_id}/chat/{session_id}/history", response_model=list[ChatMessageResponse])
def get_chat_history(
    project_id: int,
    session_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db),
    limit: int = 50
):
    """
    Retrieve chat history for a specific session.
    """
    # Validate that session exists and belongs to the user
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.project_id == project_id,
        ChatSession.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or access denied"
        )
    
    # Check if user has access to the project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Check if user is owner or member
    is_member = db.execute(
        project_members.select().where(
            (project_members.c.user_id == current_user.id) &
            (project_members.c.project_id == project_id)
        )
    ).first()
    
    if project.owner_id != current_user.id and not is_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project"
        )
    
    # Fetch chat messages
    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.timestamp.asc()).limit(limit).all()
    
    return messages


@app.get("/")
def root():
    """Health check endpoint."""
    return {"message": "Auth & Project API is running"}
