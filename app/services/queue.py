import json
from typing import Any

import redis

from app.core.config import settings


class QueueService:
    """Service for managing Redis message queue."""
    
    def __init__(self):
        self.redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.queue_name = settings.QUEUE_NAME
    
    def push_message(self, message: dict[str, Any]) -> bool:
        """
        Push a message to the ingestion queue.
        
        Args:
            message: Dictionary containing message data
            
        Returns:
            bool: True if message was pushed successfully
        """
        try:
            message_json = json.dumps(message)
            self.redis_client.rpush(self.queue_name, message_json)
            return True
        except Exception as e:
            print(f"Error pushing message to queue: {e}")
            return False
    
    def get_queue_length(self) -> int:
        """
        Get the current length of the ingestion queue.
        
        Returns:
            int: Number of messages in the queue
        """
        try:
            return self.redis_client.llen(self.queue_name)
        except Exception:
            return 0
    
    def health_check(self) -> bool:
        """
        Check if Redis connection is healthy.
        
        Returns:
            bool: True if Redis is reachable
        """
        try:
            self.redis_client.ping()
            return True
        except Exception:
            return False


# Singleton instance
queue_service = QueueService()
