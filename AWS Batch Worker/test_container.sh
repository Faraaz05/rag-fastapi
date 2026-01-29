#!/bin/bash
# Test script for AWS Batch GPU Worker Docker container

echo "🏗️ Building AWS Batch Worker Docker image..."
docker build -t aws-batch-gpu-worker .

echo "🚀 Running container with test environment variables..."

# Load your .env file if it exists
if [ -f "../../.env" ]; then
    echo "📄 Loading environment from .env file..."
    export $(grep -v '^#' ../../.env | xargs)
fi

# Run the container with required environment variables
docker run --rm \
    --gpus all \
    --network host \
    -e DATABASE_URL="${DATABASE_URL:-postgresql://user:pass@localhost:5432/db}" \
    -e GROQ_API_KEY="${GROQ_API_KEY:-your-groq-key}" \
    -e GOOGLE_API_KEY="${GOOGLE_API_KEY:-your-google-key}" \
    -e PROJECT_ID="2" \
    -e FILE_ID="rhcsa-mock-8-test" \
    -e S3_PATH="projects/2/raw/RHCSA Mock 8.pdf" \
    -e ORIGINAL_FILENAME="RHCSA Mock 8.pdf" \
    -e S3_BUCKET_NAME="${S3_BUCKET_NAME:-vector-trace-storage}" \
    -e CHROMA_HOST="${CHROMA_HOST:-localhost}" \
    -e CHROMA_PORT="${CHROMA_PORT:-8001}" \
    aws-batch-gpu-worker

echo "✅ Container test completed!"