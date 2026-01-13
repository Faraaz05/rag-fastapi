import os
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings


class StorageService:
    """Service for handling local file storage."""
    
    def __init__(self):
        self.base_dir = Path(settings.UPLOAD_DIR)
    
    async def save_file(self, project_id: int, file: UploadFile) -> dict:
        """
        Save an uploaded file to local storage.
        
        Args:
            project_id: The ID of the project
            file: The uploaded file
            
        Returns:
            dict: Contains file_path, file_id, original_filename, and size
        """
        # Create project directory if it doesn't exist
        project_dir = self.base_dir / str(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate unique filename
        file_id = str(uuid.uuid4())
        file_extension = Path(file.filename).suffix if file.filename else ""
        unique_filename = f"{file_id}{file_extension}"
        file_path = project_dir / unique_filename
        
        # Save file
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        
        # Reset file pointer for potential reuse
        await file.seek(0)
        
        return {
            "file_id": file_id,
            "file_path": str(file_path),
            "original_filename": file.filename,
            "size": len(content)
        }
    
    def save_json_transcript(self, project_id: int, file_id: str, transcript_data: dict) -> str:
        """
        Save parsed transcript as JSON file.
        
        Args:
            project_id: The ID of the project
            file_id: Unique file ID
            transcript_data: Parsed transcript data with turns
            
        Returns:
            str: Path to the saved JSON file
        """
        import json
        
        # Create processed directory for project
        processed_dir = Path(settings.PROCESSED_DIR) / str(project_id)
        processed_dir.mkdir(parents=True, exist_ok=True)
        
        # Save as JSON
        json_filename = f"{file_id}.json"
        json_path = processed_dir / json_filename
        
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(transcript_data, f, indent=2, ensure_ascii=False)
        
        return str(json_path)
    
    def delete_file(self, file_path: str) -> bool:
        """
        Delete a file from local storage.
        
        Args:
            file_path: Path to the file
            
        Returns:
            bool: True if deleted successfully, False otherwise
        """
        try:
            Path(file_path).unlink(missing_ok=True)
            return True
        except Exception:
            return False


# Singleton instance
storage_service = StorageService()
