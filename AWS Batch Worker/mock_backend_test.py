#!/usr/bin/env python3
"""
Mock Backend Script - Emulates FastAPI backend file upload and AWS Batch job triggering
Uploads a test PDF to S3 and runs the Docker container with proper environment variables.
"""
import os
import uuid
import boto3
import subprocess
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, Enum, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime
import enum

# Load environment variables
load_dotenv()

class FileStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PARTITIONING = "partitioning"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"

Base = declarative_base()

class File(Base):
    __tablename__ = "files"
    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(String, unique=True, index=True, nullable=False)
    project_id = Column(Integer, nullable=False)
    original_filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    status = Column(Enum(FileStatus), default=FileStatus.UPLOADED, nullable=False)
    error_message = Column(String, nullable=True)
    processed_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

def find_test_pdf():
    """Find the RHCSAMOCK8 PDF file in the current directory."""
    current_dir = Path(__file__).parent

    # Look for RHCSAMOCK8 file (with or without extension)
    possible_names = [
        "RHCSAMOCK8.pdf",
        "RHCSAMOCK8",
        "rhcsamock8.pdf",
        "rhcsamock8"
    ]

    for name in possible_names:
        pdf_path = current_dir / name
        if pdf_path.exists():
            print(f"✅ Found test PDF: {pdf_path}")
            return str(pdf_path)

    raise FileNotFoundError(
        f"❌ Could not find RHCSAMOCK8 PDF file in {current_dir}. "
        "Please place a PDF file named 'RHCSAMOCK8.pdf' in this directory."
    )

def upload_to_s3_like_backend(pdf_path: str, project_id: int):
    """Upload file to S3 using the same logic as the backend storage service."""
    s3_client = boto3.client('s3')
    bucket_name = os.getenv('S3_BUCKET_NAME', 'vector-trace-storage')

    # Generate unique filename for S3 (UUID)
    file_id = str(uuid.uuid4())
    file_extension = ".pdf"
    unique_filename = f"{file_id}{file_extension}"

    # S3 key structure: projects/{project_id}/raw/{unique_filename}
    s3_key = f"projects/{project_id}/raw/{unique_filename}"

    # Original filename is the actual file name
    original_filename = Path(pdf_path).name

    # Read and upload file
    with open(pdf_path, 'rb') as f:
        file_content = f.read()

    file_size = len(file_content)

    s3_client.put_object(
        Bucket=bucket_name,
        Key=s3_key,
        Body=file_content,
        ContentType='application/pdf'
    )

    print(f"✅ Uploaded to S3: s3://{bucket_name}/{s3_key}")
    return {
        'file_id': file_id,
        's3_key': s3_key,
        'original_filename': original_filename,
        'bucket_name': bucket_name,
        'size': file_size
    }

def insert_file_to_db(file_info: dict, project_id: int):
    """Insert file record into database like the backend does."""
    database_url = os.getenv('DATABASE_URL')
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine)
    
    db = SessionLocal()
    try:
        new_file = File(
            file_id=file_info['file_id'],
            project_id=project_id,
            original_filename=file_info['original_filename'],
            file_path=file_info['s3_key'],
            size=file_info['size'],
            status=FileStatus.QUEUED
        )
        db.add(new_file)
        db.commit()
        print(f"✅ Inserted file record into DB: {file_info['file_id']}")
    except Exception as e:
        db.rollback()
        print(f"❌ Failed to insert into DB: {str(e)}")
        raise
    finally:
        db.close()

def run_batch_container(file_info: dict, project_id: int):
    """Run the AWS Batch worker container with proper environment variables."""
    env_vars = {
        'DATABASE_URL': os.getenv('DATABASE_URL'),
        'GROQ_API_KEY': os.getenv('GROQ_API_KEY'),
        'GOOGLE_API_KEY': os.getenv('GOOGLE_API_KEY'),
        'PROJECT_ID': str(project_id),
        'FILE_ID': file_info['file_id'],
        'S3_PATH': file_info['s3_key'],
        'ORIGINAL_FILENAME': file_info['original_filename'],
        'S3_BUCKET_NAME': file_info['bucket_name'],
        'CHROMA_HOST': os.getenv('CHROMA_HOST', 'localhost'),
        'CHROMA_PORT': os.getenv('CHROMA_PORT', '8001'),
    }

    # Build docker run command
    cmd = ['docker', 'run', '--rm', '--gpus', 'all', '--network', 'host', '-v', '/home/faraaz/Development/RAG-FASTAPI/.env:/app/.env']

    # Add environment variables
    for key, value in env_vars.items():
        if value:  # Only add if value exists
            cmd.extend(['-e', f'{key}={value}'])

    # Add container name
    cmd.append('aws-batch-gpu-worker')

    print("🚀 Running AWS Batch container with command:")
    print(" ".join(cmd))
    print("\n📋 Environment variables:")
    for key, value in env_vars.items():
        if value:
            print(f"  {key}={value}")
        else:
            print(f"  {key}=<not set>")

    print("\n" + "="*50)
    print("CONTAINER OUTPUT:")
    print("="*50)

    # Run the container
    result = subprocess.run(cmd, cwd=os.path.dirname(__file__))

    return result.returncode == 0

def main():
    """Main execution flow."""
    print("🎯 Mock Backend - Testing AWS Batch Worker Container")
    print("="*55)

    # Configuration
    PROJECT_ID = 2  # Use project 2

    try:
        # 1. Find test PDF
        print("📄 Finding test PDF...")
        pdf_path = find_test_pdf()

        # 2. Upload to S3 (like backend does)
        print("\n☁️  Uploading to S3...")
        file_info = upload_to_s3_like_backend(pdf_path, PROJECT_ID)

        # 3. Insert into DB (like backend does)
        print("\n💾 Inserting file record into DB...")
        insert_file_to_db(file_info, PROJECT_ID)

        # 4. Run container (like AWS Batch would)
        print("\n🐳 Running AWS Batch worker container...")
        success = run_batch_container(file_info, PROJECT_ID)

        if success:
            print("\n🎉 Mock backend test completed successfully!")
            print(f"📊 Processed file: {file_info['original_filename']}")
            print(f"🆔 File ID: {file_info['file_id']}")
            print(f"📍 S3 Location: s3://{file_info['bucket_name']}/{file_info['s3_key']}")
        else:
            print("\n❌ Container execution failed!")
            exit(1)

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        exit(1)

if __name__ == "__main__":
    main()