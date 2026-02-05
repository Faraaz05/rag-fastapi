from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    DATABASE_URL: str = "postgresql://rag_user:your_secure_password@localhost:5432/rag_db"
    REDIS_URL: str = "redis://localhost:6379/0"
    UPLOAD_DIR: str = "./data/raw"
    PROCESSED_DIR: str = "./data/processed"
    
    # PostgreSQL Settings
    POSTGRES_USER: str = "rag_user"
    POSTGRES_PASSWORD: str = "your_secure_password"
    POSTGRES_DB: str = "rag_db"
        # AWS S3 Settings
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    AWS_DEFAULT_REGION: str = "ap-south-1"
    S3_BUCKET_NAME: str | None = None
    USE_S3: bool = False
    
    # Queue Settings (Redis for local, SQS for AWS)
    USE_SQS: bool = False
    SQS_QUEUE_URL: str | None = None
    QUEUE_NAME: str = "ingestion_queue"
    AUDIO_QUEUE_NAME: str = "audio_queue"
    SQS_AUDIO_QUEUE_URL: str | None = None
    
    # ChromaDB Settings
    CHROMA_HOST: str = "chromadb"
    CHROMA_PORT: int = 8001
    CHROMA_DB_PATH: str = "./unified_chroma_db"
    
    # AI API Keys (optional for basic functionality)
    GROQ_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None

    class Config:
        env_file = ".env"
        extra = "ignore"  # Ignore extra fields in .env


settings = Settings()
