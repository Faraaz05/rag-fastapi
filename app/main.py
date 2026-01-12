from datetime import timedelta
from typing import Annotated

from fastapi import FastAPI, Depends, HTTPException, status, UploadFile
from fastapi import File as FileUpload
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.auth import (
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)
from app.core.config import settings
from app.models import Base, User, Project, project_members, File, FileStatus, ChatMessage
from app.schemas import (
    UserCreate,
    UserResponse,
    Token,
    ProjectCreate,
    ProjectResponse,
    MemberAdd,
    MemberResponse,
    UploadResponse,
    FileStatusResponse,
    TranscriptUpload,
    TranscriptResponse,
    QueryRequest,
    QueryResponse,
    ChatMessageRequest,
    ChatMessageResponse,
)
from app.services.storage import storage_service
from app.services.queue import queue_service
from app.services.transcript import process_transcript_file
from app.services.rag import quick_query, get_standalone_question, streaming_chat, query_with_filter

# Database setup
engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Auth & Project API")


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


# ==================== PROJECT ROUTES ====================

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


@app.post("/projects/{project_id}/upload", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_file(
    project_id: int,
    file: UploadFile = FileUpload(...),
    project: Project = Depends(is_project_owner),
    db: Session = Depends(get_db)
):
    """
    Upload a file to a project. Only project owner can upload.
    The file is saved locally and a message is sent to the ingestion queue.
    """
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
    
    # Prepare message for the ingestion queue
    message = {
        "project_id": project_id,
        "file_id": file_info["file_id"],
        "file_path": file_info["file_path"],
        "original_filename": file_info["original_filename"],
        "size": file_info["size"]
    }
    
    # Push message to Redis queue
    queue_success = queue_service.push_message(message)
    
    if not queue_success:
        # Update status to FAILED if queue push fails
        db_file.status = FileStatus.FAILED
        db_file.error_message = "Failed to queue file for processing"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue file for processing"
        )
    
    return UploadResponse(
        message="File uploaded successfully and queued for processing",
        file_id=file_info["file_id"],
        original_filename=file_info["original_filename"],
        project_id=project_id,
        size=file_info["size"],
        status=db_file.status.value
    )


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


@app.post("/projects/{project_id}/transcripts", response_model=TranscriptResponse)
async def upload_transcript(
    project_id: int,
    file: UploadFile = FileUpload(...),
    meeting_name: str = None,
    meeting_date: str = None,
    turns_per_chunk: int = 8,
    overlap: int = 3,
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
            # Update file status to COMPLETED
            db_file.status = FileStatus.COMPLETED
            db_file.processed_path = result["collection_name"]
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


@app.post("/projects/{project_id}/chat/{session_id}")
async def chat_with_project(
    project_id: int,
    session_id: str,
    chat_request: ChatMessageRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db)
):
    """
    History-aware streaming chat with the project's RAG system.
    Uses conversation history to contextualize questions.
    Streams the response with Server-Sent Events.
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
    if chat_request.filter not in ["unified", "document", "transcript"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filter. Must be 'unified', 'document', or 'transcript'"
        )
    
    try:
        # Step 1: Fetch last 5 messages from database
        history_messages = db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id,
            ChatMessage.project_id == project_id
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
            project_id=project_id,
            role="user",
            content=chat_request.question
        )
        db.add(user_message)
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
                assistant_message = ChatMessage(
                    session_id=session_id,
                    project_id=project_id,
                    role="assistant",
                    content=full_answer
                )
                db.add(assistant_message)
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
    session_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Session = Depends(get_db),
    limit: int = 50
):
    """
    Retrieve chat history for a specific session.
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
    
    # Fetch chat messages
    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id,
        ChatMessage.project_id == project_id
    ).order_by(ChatMessage.timestamp.asc()).limit(limit).all()
    
    return messages


@app.get("/")
def root():
    """Health check endpoint."""
    return {"message": "Auth & Project API is running"}
