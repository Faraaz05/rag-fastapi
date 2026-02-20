import os
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import boto3
from botocore.exceptions import ClientError

from fastapi import UploadFile

from app.core.config import settings


class StorageService:
    """Service for handling file storage (S3 or local fallback)."""

    def __init__(self):
        self.use_s3 = settings.USE_S3
        if self.use_s3:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_DEFAULT_REGION
            )
            self.bucket_name = settings.S3_BUCKET_NAME
        else:
            # Fallback to local storage
            self.base_dir = Path(settings.UPLOAD_DIR)

    async def save_file(self, project_id: int, file: UploadFile, file_id: str = None) -> dict:
        """
        Save an uploaded file to S3 or local storage using async chunked uploads.
        This prevents blocking the event loop for large files.

        Args:
            project_id: The ID of the project
            file: The uploaded file
            file_id: Optional pre-generated file ID (for creating DB record before upload)

        Returns:
            dict: Contains file_path/s3_key, file_id, original_filename, and size
        """
        # Generate unique filename
        if not file_id:
            file_id = str(uuid.uuid4())
        file_extension = Path(file.filename).suffix if file.filename else ""
        unique_filename = f"{file_id}{file_extension}"

        if self.use_s3:
            # S3 key structure: projects/{project_id}/raw/{unique_filename}
            s3_key = f"projects/{project_id}/raw/{unique_filename}"

            try:
                # Use multipart upload for large files (async friendly)
                import asyncio
                from concurrent.futures import ThreadPoolExecutor
                
                # Read file content in chunks to avoid blocking
                chunk_size = 8 * 1024 * 1024  # 8MB chunks
                chunks = []
                file_size = 0
                
                while True:
                    chunk = await file.read(chunk_size)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    file_size += len(chunk)
                
                # Combine chunks for upload (in thread pool to not block)
                content = b''.join(chunks)
                
                # Upload to S3 in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                with ThreadPoolExecutor() as pool:
                    await loop.run_in_executor(
                        pool,
                        lambda: self.s3_client.put_object(
                            Bucket=self.bucket_name,
                            Key=s3_key,
                            Body=content,
                            ContentType=file.content_type or 'application/octet-stream'
                        )
                    )

                file_path = s3_key  # Store S3 key as file_path

            except ClientError as e:
                raise Exception(f"Failed to upload file to S3: {str(e)}")

        else:
            # Local storage fallback using async file I/O
            import aiofiles
            
            project_dir = self.base_dir / str(project_id)
            project_dir.mkdir(parents=True, exist_ok=True)
            file_path = project_dir / unique_filename

            # Save file locally with async I/O (non-blocking)
            chunk_size = 1024 * 1024  # 1MB chunks
            file_size = 0
            
            async with aiofiles.open(file_path, "wb") as f:
                while True:
                    chunk = await file.read(chunk_size)
                    if not chunk:
                        break
                    await f.write(chunk)
                    file_size += len(chunk)

            file_path = str(file_path)

        # Reset file pointer for potential reuse
        await file.seek(0)

        return {
            "file_id": file_id,
            "file_path": file_path,  # S3 key or local path
            "original_filename": file.filename,
            "size": file_size
        }

    def save_json_transcript(self, project_id: int, file_id: str, transcript_data: dict) -> str:
        """
        Save parsed transcript as JSON file to S3 or local storage.

        Args:
            project_id: The ID of the project
            file_id: Unique file ID
            transcript_data: Parsed transcript data with turns

        Returns:
            str: Path to the saved JSON file (S3 key or local path)
        """
        import json

        # Convert data to JSON string
        json_content = json.dumps(transcript_data, indent=2, ensure_ascii=False)
        json_bytes = json_content.encode('utf-8')

        if self.use_s3:
            # S3 key structure: projects/{project_id}/processed/{file_id}.json
            s3_key = f"projects/{project_id}/processed/{file_id}.json"

            try:
                # Upload to S3
                self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=s3_key,
                    Body=json_bytes,
                    ContentType='application/json'
                )

                return s3_key

            except ClientError as e:
                raise Exception(f"Failed to upload JSON to S3: {str(e)}")

        else:
            # Local storage fallback
            processed_dir = Path(settings.PROCESSED_DIR) / str(project_id)
            processed_dir.mkdir(parents=True, exist_ok=True)

            # Save as JSON
            json_filename = f"{file_id}.json"
            json_path = processed_dir / json_filename

            with open(json_path, "w", encoding="utf-8") as f:
                f.write(json_content)

            return str(json_path)

    def get_file_stream(self, file_path: str):
        """
        Get file content as a stream from S3 or local storage.
        Yields chunks of data for memory-efficient streaming.

        Args:
            file_path: S3 key or local file path

        Yields:
            Bytes chunks of file content
        """
        if self.use_s3:
            try:
                response = self.s3_client.get_object(Bucket=self.bucket_name, Key=file_path)
                body = response['Body']
                for chunk in body.iter_chunks(chunk_size=8192):
                    yield chunk
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchKey':
                    raise Exception("File not found")
                raise Exception(f"Failed to get file from S3: {str(e)}")
        else:
            # Local storage
            if not os.path.exists(file_path):
                raise Exception("File not found")
            
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    yield chunk

    def get_file_content(self, file_path: str) -> Optional[bytes]:
        """
        Get full file content as bytes from S3 or local storage.

        Args:
            file_path: S3 key or local file path

        Returns:
            File content as bytes, or None if not found
        """
        if self.use_s3:
            try:
                response = self.s3_client.get_object(Bucket=self.bucket_name, Key=file_path)
                return response['Body'].read()
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchKey':
                    return None
                raise Exception(f"Failed to get file from S3: {str(e)}")
        else:
            # Local storage
            if not os.path.exists(file_path):
                return None
            
            with open(file_path, 'rb') as f:
                return f.read()

    def get_file_url(self, file_path: str, expires_in: int = 3600) -> Optional[str]:
        """
        Generate a presigned URL for S3 file or return local path.

        Args:
            file_path: S3 key or local file path
            expires_in: URL expiration time in seconds (for S3)

        Returns:
            Presigned URL or local path
        """
        if self.use_s3:
            try:
                url = self.s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': self.bucket_name, 'Key': file_path},
                    ExpiresIn=expires_in
                )
                return url
            except ClientError as e:
                raise Exception(f"Failed to generate presigned URL: {str(e)}")
        else:
            # For local files, return the path (will be served by FastAPI)
            return file_path

    def delete_file(self, file_path: str) -> bool:
        """
        Delete a file from S3 or local storage.

        Args:
            file_path: S3 key or local file path

        Returns:
            bool: True if deleted successfully, False otherwise
        """
        if self.use_s3:
            try:
                self.s3_client.delete_object(Bucket=self.bucket_name, Key=file_path)
                return True
            except ClientError:
                return False
        else:
            # Local storage
            try:
                Path(file_path).unlink(missing_ok=True)
                return True
            except Exception:
                return False

    def delete_directory(self, project_id: int) -> bool:
        """
        Delete all files for a project from S3 or local storage.

        Args:
            project_id: The project ID

        Returns:
            bool: True if deleted successfully
        """
        if self.use_s3:
            try:
                # Delete raw files
                raw_prefix = f"projects/{project_id}/raw/"
                self._delete_s3_prefix(raw_prefix)

                # Delete processed files
                processed_prefix = f"projects/{project_id}/processed/"
                self._delete_s3_prefix(processed_prefix)

                return True
            except ClientError:
                return False
        else:
            # Local storage
            try:
                import shutil

                # Delete raw files
                raw_project_dir = Path(settings.UPLOAD_DIR) / str(project_id)
                if raw_project_dir.exists():
                    shutil.rmtree(raw_project_dir, ignore_errors=True)

                # Delete processed files
                processed_project_dir = Path(settings.PROCESSED_DIR) / str(project_id)
                if processed_project_dir.exists():
                    shutil.rmtree(processed_project_dir, ignore_errors=True)

                return True
            except Exception:
                return False

    def _delete_s3_prefix(self, prefix: str):
        """Helper method to delete all objects with a given prefix from S3."""
        paginator = self.s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=self.bucket_name, Prefix=prefix)

        delete_keys = []
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    delete_keys.append({'Key': obj['Key']})

        if delete_keys:
            # Delete in batches of 1000 (S3 limit)
            for i in range(0, len(delete_keys), 1000):
                batch = delete_keys[i:i+1000]
                self.s3_client.delete_objects(
                    Bucket=self.bucket_name,
                    Delete={'Objects': batch}
                )


# Singleton instance
storage_service = StorageService()
