# AWS Batch Worker Testing

## Prerequisites

1. **Running Services**: Make sure your docker-compose services are running:
   ```bash
   cd ..
   docker-compose up -d
   ```

2. **Test PDF**: Place your test PDF as `RHCSAMOCK8.pdf` in this directory

3. **Environment Variables**: Your `.env` file should contain:
   - `DATABASE_URL` (points to localhost:5432)
   - `GROQ_API_KEY`
   - `GOOGLE_API_KEY`
   - `S3_BUCKET_NAME`
   - `CHROMA_HOST=localhost`
   - `CHROMA_PORT=8001`

## Networking Setup

The container uses `--network host` to access your local services:

- **ChromaDB**: `localhost:8001` (from docker-compose)
- **PostgreSQL**: `localhost:5432` (from docker-compose)
- **Redis**: `localhost:6379` (from docker-compose)
- **S3**: Via internet (AWS credentials needed)

## Files Overview

- `aws_gpu_worker.py` - The main AWS Batch worker script
- `Dockerfile` - Container definition for GPU processing
- `requirements.txt` - Main Python dependencies
- `requirements-missing.txt` - Missing unstructured dependencies (separate layer)
- `test_container.sh` - Simple container test script
- `mock_backend_test.py` - Complete end-to-end test (recommended)

## Quick Test (Simple)

```bash
# Build and test container
./test_container.sh
```

## Full End-to-End Test (Recommended)

```bash
# 1. Place your test PDF file here as "RHCSAMOCK8.pdf"
cp /path/to/your/test.pdf ./RHCSAMOCK8.pdf

# 2. Run the mock backend test
python mock_backend_test.py
```

## What the Mock Backend Does

1. **Finds** the `RHCSAMOCK8.pdf` file in the current directory
2. **Uploads** it to S3 using the same logic as your FastAPI backend
3. **Runs** the Docker container with proper environment variables
4. **Processes** the document through the full pipeline
5. **Reports** success/failure

## Environment Variables Required

Make sure your `.env` file contains:
- `DATABASE_URL`
- `GROQ_API_KEY`
- `GOOGLE_API_KEY`
- `S3_BUCKET_NAME`
- `CHROMA_HOST` (defaults to localhost)
- `CHROMA_PORT` (defaults to 8001 for docker-compose)

## Expected Output

```
🎯 Mock Backend - Testing AWS Batch Worker Container
=======================================================
📄 Finding test PDF...
✅ Found test PDF: /path/to/RHCSAMOCK8.pdf
☁️  Uploading to S3...
✅ Uploaded to S3: s3://vector-trace-storage/projects/2/raw/12345678-1234-1234-1234-123456789abc.pdf
🐳 Running AWS Batch worker container...
🚀 Running AWS Batch container with command: ...
📋 Environment variables: ...
==================================================
CONTAINER OUTPUT:
==================================================
📥 Downloading s3://vector-trace-storage/projects/2/raw/12345678-1234-1234-1234-123456789abc.pdf
📄 Partitioning document: /tmp/.../12345678-1234-1234-1234-123456789abc.pdf
🔨 Creating smart chunks...
🚀 Starting LPU processing for X chunks...
🎉 Job Finished Successfully

🎉 Mock backend test completed successfully!
📊 Processed file: 12345678-1234-1234-1234-123456789abc.pdf
🆔 File ID: 12345678-1234-1234-1234-123456789abc
📍 S3 Location: s3://vector-trace-storage/projects/2/raw/12345678-1234-1234-1234-123456789abc.pdf
```