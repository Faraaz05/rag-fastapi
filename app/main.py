from datetime import timedelta
from typing import Annotated

from fastapi import FastAPI, Depends, HTTPException, status, UploadFile
from fastapi import File as FileUpload
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
from app.models import Base, User, Project, project_members, File, FileStatus
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
)
from app.services.storage import storage_service
from app.services.queue import queue_service

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


@app.get("/")
def root():
    """Health check endpoint."""
    return {"message": "Auth & Project API is running"}
