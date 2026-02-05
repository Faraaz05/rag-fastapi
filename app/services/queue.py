import json
from typing import Any

import redis
import boto3
from botocore.exceptions import ClientError

from app.core.config import settings


class QueueService:
    """Service for managing message queue (Redis for local, SQS for AWS)."""
    
    def __init__(self):
        self.use_sqs = settings.USE_SQS
        
        if self.use_sqs:
            # AWS SQS client
            self.sqs_client = boto3.client(
                'sqs',
                region_name=settings.AWS_DEFAULT_REGION,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
            )
            self.queue_url = settings.SQS_QUEUE_URL
            self.audio_queue_url = settings.SQS_AUDIO_QUEUE_URL
        else:
            # Redis client (local development)
            self.redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
            self.queue_name = settings.QUEUE_NAME
            self.audio_queue_name = settings.AUDIO_QUEUE_NAME
    
    def push_message(self, message: dict[str, Any]) -> bool:
        """
        Push a message to the ingestion queue (SQS or Redis).
        
        Args:
            message: Dictionary containing message data
            
        Returns:
            bool: True if message was pushed successfully
        """
        try:
            message_json = json.dumps(message)
            
            if self.use_sqs:
                # Send to SQS
                response = self.sqs_client.send_message(
                    QueueUrl=self.queue_url,
                    MessageBody=message_json
                )
                return response.get('MessageId') is not None
            else:
                # Send to Redis
                self.redis_client.rpush(self.queue_name, message_json)
                return True
                
        except ClientError as e:
            print(f"Error pushing message to SQS: {e}")
            return False
        except Exception as e:
            print(f"Error pushing message to queue: {e}")
            return False
    
    def get_queue_length(self) -> int:
        """
        Get the current length of the ingestion queue.
        Note: For SQS, this is an approximate count.
        
        Returns:
            int: Number of messages in the queue
        """
        try:
            if self.use_sqs:
                # Get approximate message count from SQS
                response = self.sqs_client.get_queue_attributes(
                    QueueUrl=self.queue_url,
                    AttributeNames=['ApproximateNumberOfMessages']
                )
                return int(response['Attributes'].get('ApproximateNumberOfMessages', 0))
            else:
                # Get exact count from Redis
                return self.redis_client.llen(self.queue_name)
        except Exception:
            return 0
    
    def health_check(self) -> bool:
        """
        Check if queue connection is healthy.
        
        Returns:
            bool: True if queue is reachable
        """
        try:
            if self.use_sqs:
                # Check SQS queue exists and is accessible
                self.sqs_client.get_queue_attributes(
                    QueueUrl=self.queue_url,
                    AttributeNames=['QueueArn']
                )
                return True
            else:
                # Check Redis connection
                self.redis_client.ping()
                return True
        except Exception:
            return False

    def push_audio_message(self, message: dict[str, Any]) -> bool:
        """
        Push a message to the audio processing queue (SQS or Redis).
        
        Args:
            message: Dictionary containing audio metadata and file info
            
        Returns:
            bool: True if message was pushed successfully
        """
        try:
            message_json = json.dumps(message)
            
            if self.use_sqs:
                # Send to SQS audio queue
                response = self.sqs_client.send_message(
                    QueueUrl=self.audio_queue_url,
                    MessageBody=message_json
                )
                return response.get('MessageId') is not None
            else:
                # Send to Redis audio queue
                self.redis_client.rpush(self.audio_queue_name, message_json)
                return True
                
        except ClientError as e:
            print(f"Error pushing audio message to SQS: {e}")
            return False
        except Exception as e:
            print(f"Error pushing audio message to queue: {e}")
            return False

    def get_audio_queue_length(self) -> int:
        """
        Get the current length of the audio processing queue.
        Note: For SQS, this is an approximate count.
        
        Returns:
            int: Number of messages in the audio queue
        """
        try:
            if self.use_sqs:
                # Get approximate message count from SQS
                response = self.sqs_client.get_queue_attributes(
                    QueueUrl=self.audio_queue_url,
                    AttributeNames=['ApproximateNumberOfMessages']
                )
                return int(response['Attributes'].get('ApproximateNumberOfMessages', 0))
            else:
                # Get exact count from Redis
                return self.redis_client.llen(self.audio_queue_name)
        except Exception:
            return 0


# Singleton instance
queue_service = QueueService()
