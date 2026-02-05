"""
Audio file handling service for ingestion pipeline.
Handles queue operations for audio files to be processed by worker script.
"""
import json
from typing import Dict, Any
from datetime import datetime


def create_audio_queue_message(
    file_id: str,
    project_id: int,
    project_name: str,
    original_filename: str,
    file_path: str,
    audio_name: str,
    audio_date: str,
    file_size: int
) -> Dict[str, Any]:
    """
    Create a message for the audio processing queue.
    
    Args:
        file_id: Unique file identifier (UUID)
        project_id: Project ID for organization
        project_name: Name of the project
        original_filename: Original audio filename
        file_path: S3 key or local path to the audio file
        audio_name: Descriptive name for the audio
        audio_date: Date of the audio (YYYY-MM-DD format)
        file_size: Size of the audio file in bytes
        
    Returns:
        Dictionary containing queue message with all metadata
    """
    message = {
        "file_id": file_id,
        "project_id": project_id,
        "project_name": project_name,
        "original_filename": original_filename,
        "file_path": file_path,
        "audio_name": audio_name,
        "audio_date": audio_date,
        "file_size": file_size,
        "status": "uploaded",
        "created_at": datetime.utcnow().isoformat(),
        "message_type": "audio_ingestion"
    }
    return message
