# Multi-Tenant RAG System with FastAPI

A production-grade Retrieval-Augmented Generation (RAG) system built with FastAPI, featuring multi-tenant architecture, hybrid document processing (GPU-accelerated PDF partitioning and audio transcription), and cloud-native deployment on AWS.

## Project Repositories

This project consists of multiple repositories:

- **Backend API** (this repository): FastAPI server, database models, RAG pipeline
- **Frontend**: [Next.js Web Application](https://github.com/Faraaz05/RAG-FRONTEND)
- **PDF Worker**: [GPU-Accelerated Document Processing](https://github.com/Faraaz05/RAG-GPU-IMAGE)
- **Audio Worker**: [GPU-Accelerated Audio Transcription](https://github.com/Faraaz05/RAG-AUDIO-IMAGE)

---

## Project Highlights

- **Multi-Tenant RAG Pipeline**: Isolated vector databases per project with unified query engine
- **Cloud-Native Architecture**: Production deployment on AWS using ECS Fargate, RDS PostgreSQL, S3, SQS, and CloudFront
- **Hybrid Processing Architecture**: GPU-heavy workloads (document partitioning, audio transcription) on dedicated EC2 instances, REST API on serverless Fargate containers
- **Infrastructure as Code**: Complete AWS infrastructure provisioned with Terraform
- **CI/CD Pipeline**: Automated frontend deployment via AWS CodeBuild with GitHub webhooks
- **Custom Domain with SSL**: CloudFront distributions with ACM certificates for HTTPS
- **Service Discovery**: AWS Cloud Map for internal service-to-service communication
- **Scalable Storage**: Hybrid storage model (local development, S3 production) with async file uploads

---

## Architecture Overview

This project demonstrates comprehensive cloud architecture skills including containerization, serverless computing, networking, security, infrastructure automation, and cost optimization strategies.

**Key Cloud Technologies**: AWS ECS Fargate, Application Load Balancer, CloudFront CDN, RDS PostgreSQL, S3, SQS, Route 53, ACM, VPC, NAT Gateway, Cloud Map, Secrets Manager, CloudWatch, ECR, CodeBuild, Terraform


---

## Table of Contents

1. [Features](#features)
2. [Technology Stack](#technology-stack)
3. [Application Architecture](#application-architecture)
4. [Cloud Infrastructure Architecture](#cloud-infrastructure-architecture)
5. [Local Development](#local-development)

---

### Screenshots

#### File Upload View / Dashboard
![File Upload Screenshot](./docs/images/file_upload.png)

#### Chat Interface With Document Citations
![Chat Interface (Document Citations)](./docs/images/doc_citations.png)

#### Chat Interface With Audio/Video Citations
![Chat Interface (Audio/Video Citations)](./docs/images/audio_citations.png)

#### Member Management
![Member Management](./docs/images/member_management.png)

#### Audio/Video View
![Video View](./docs/images/audio_view.png)


---

## Features

### Core Functionality

- **Multi-Tenant Project Management**: Users can create multiple isolated projects with role-based access control (Owner/Member)
- **Document Processing Pipeline**: Upload PDF/DOCX files with automatic conversion, GPU-accelerated partitioning using Unstructured.io
- **Audio Transcription Pipeline**: Upload audio files for speaker-diarized transcription using Faster-Whisper and Pyannote
- **Unified Vector Search**: Query across documents and transcripts within a project using ChromaDB vector database
- **Conversational RAG**: Context-aware chat with citation tracking and conversation history
- **Real-Time Processing Status**: WebSocket updates for file processing progress
- **Source Attribution**: All RAG responses include document/transcript sources with chunk references

### Technical Features

- **Asynchronous File Uploads**: Chunked uploads with non-blocking I/O for large files
- **Queue-Based Processing**: Redis (local) and AWS SQS (production) for decoupled worker architecture
- **JWT Authentication**: Secure token-based authentication with role-based authorization
- **Database Migrations**: SQLAlchemy ORM with Alembic migrations for schema versioning
- **API Rate Limiting**: Request throttling to prevent abuse
- **Comprehensive Logging**: Structured logging with CloudWatch integration
- **Error Handling**: Graceful error recovery with detailed error messages
- **CORS Support**: Configured CORS for frontend-backend communication

---

## Technology Stack

### Backend

- **Framework**: FastAPI (Python 3.11)
- **Vector Database**: ChromaDB (HTTP client mode)
- **Relational Database**: PostgreSQL 15
- **Embeddings**: Google Generative AI Embeddings (text-embedding-004)
- **LLM**: Groq API (llama-3.1-70b-versatile)
- **Document Processing**: Unstructured.io (hi_res strategy with Detectron2)
- **Audio Processing**: Faster-Whisper (OpenAI Whisper), Pyannote Audio (speaker diarization)
- **Task Queue**: Redis (local), AWS SQS (production)
- **Object Storage**: Local filesystem (dev), AWS S3 (production)
- **ORM**: SQLAlchemy 2.0
- **Authentication**: JWT (python-jose)

### Frontend

- **Framework**: Next.js 14 (React 18, TypeScript)
- **Styling**: Tailwind CSS
- **HTTP Client**: Axios
- **State Management**: React hooks
- **Deployment**: Static export to S3 + CloudFront

### Infrastructure

- **Cloud Provider**: AWS (ap-south-1 region)
- **Container Orchestration**: AWS ECS Fargate
- **Load Balancing**: Application Load Balancer (ALB)
- **CDN**: CloudFront with custom domain and ACM SSL certificates
- **DNS**: Route 53 with hosted zones
- **Container Registry**: Amazon ECR
- **CI/CD**: AWS CodeBuild with GitHub webhooks
- **Infrastructure as Code**: Terraform 1.5+
- **Service Discovery**: AWS Cloud Map (private DNS)
- **Secrets Management**: AWS Secrets Manager
- **Monitoring**: CloudWatch Logs and Metrics
- **Networking**: VPC with public/private subnets, NAT Gateway, Internet Gateway

### GPU Processing

- **Instance Type**: AWS EC2 g4dn.xlarge (NVIDIA T4 GPU)
- **Container Runtime**: Docker with NVIDIA Container Toolkit
- **Orchestration**: Docker Compose for local development, standalone containers on EC2

---

## Application Architecture

### System Design

The application follows a microservices architecture with clear separation of concerns:

#### Components

1. **FastAPI Backend** (Stateless REST API)
   - User authentication and authorization
   - Project and file management
   - Query orchestration
   - Conversation management
   - File upload coordination

2. **ChromaDB Vector Store** (Persistent HTTP server)
   - Per-project collections (multi-tenant isolation)
   - Document and transcript embeddings
   - Similarity search with metadata filtering

3. **PostgreSQL Database** (Relational data)
   - User accounts and credentials
   - Project metadata and memberships
   - File records and processing status
   - Chat sessions and message history

4. **GPU Worker Containers** (Async processing)
   - PDF Worker: Document partitioning, element classification, image extraction
   - Audio Worker: Transcription, speaker diarization, timestamp alignment

5. **Message Queue** (Async communication)
   - Document ingestion queue
   - Audio processing queue
   - Decouples API from heavy processing

6. **Storage Layer**
   - Raw files (uploaded documents/audio)
   - Processed artifacts (JSON chunks, embeddings)

### Data Flow

#### Document Upload Flow

1. User uploads PDF/DOCX via frontend
2. FastAPI creates database record with QUEUED status
3. File saved to S3 (async chunked upload)
4. Job message pushed to SQS document queue
5. GPU worker polls queue, downloads file from S3
6. Unstructured.io partitions document (GPU-accelerated)
7. Elements embedded using Google Gemini embeddings
8. Chunks stored in project-specific ChromaDB collection
9. Database status updated to COMPLETED

#### Audio Upload Flow

1. User uploads audio file via frontend
2. FastAPI creates database record with QUEUED status
3. Audio file saved to S3
4. Job message pushed to SQS audio queue
5. GPU worker polls queue, downloads audio from S3
6. Faster-Whisper transcribes audio (GPU inference)
7. Pyannote performs speaker diarization
8. Transcript segments embedded and indexed in ChromaDB
9. Database status updated to COMPLETED

#### Query Flow

1. User submits question via frontend
2. FastAPI receives query, retrieves conversation history
3. LangChain rewrites question as standalone query
4. Question embedded using Google Gemini
5. ChromaDB performs similarity search (top-k chunks)
6. Context + chat history sent to Groq LLM
7. LLM generates answer with citations
8. Response streamed back to frontend
9. Conversation saved to PostgreSQL

### RAG Pipeline Details

The RAG implementation follows the unified query pipeline from the reference notebooks:

**Query Processing**:
- Conversation history retrieved from database
- Question rewritten as standalone query using LLM
- Embedding generated for standalone question
- ChromaDB queried with metadata filters (document/transcript/unified)

**Context Assembly**:
- Top-k chunks retrieved (default k=5)
- Source metadata preserved (file_id, page/timestamp, source_type)
- Chunks formatted with source attribution

**Answer Generation**:
- System prompt defines RAG behavior and citation format
- Context + conversation history + question sent to LLM
- Streaming response for better UX
- Citations extracted and validated against sources

**Citation Tracking**:
- Regex parsing of citation format: [Source: file_id - location]
- Cross-reference with retrieved chunks
- Frontend displays clickable source links

---

## Cloud Infrastructure Architecture

### Architecture Diagram

![Infrastructure Diagram Full AWS Architecture](./docs/images/Architecture-Diagram.svg)


### High-Level Architecture

The infrastructure is designed for production workloads with emphasis on security, scalability, cost optimization, and operational excellence.

#### Network Architecture

**VPC Design** (10.0.0.0/16):
- **Public Subnets** (2 AZs for high availability):
  - `public-1`: 10.0.1.0/24 (ap-south-1a)
  - `public-2`: 10.0.3.0/24 (ap-south-1b)
  - Hosts: Application Load Balancer, NAT Gateway
  - Internet Gateway attached for public internet access

- **Private Subnets** (2 AZs for high availability):
  - `private-1`: 10.0.11.0/24 (ap-south-1a)
  - `private-2`: 10.0.12.0/24 (ap-south-1b)
  - Hosts: ECS Fargate tasks (FastAPI, ChromaDB), RDS PostgreSQL
  - Egress via NAT Gateway for external API calls

**Routing**:
- Public subnets route 0.0.0.0/0 to Internet Gateway
- Private subnets route 0.0.0.0/0 to NAT Gateway in public subnet
- VPC CIDR routes to local

**DNS**:
- AWS Cloud Map private DNS namespace: `vector-trace-rag.local`
- Service discovery for `chromadb.vector-trace-rag.local:8000`
- Route 53 public hosted zone for custom domain

### Compute Architecture

#### ECS Fargate Cluster

**Cluster**: `vector-trace-rag-main-cluster`

**Services**:

1. **FastAPI Service**
   - Task Definition: 1 vCPU, 2GB RAM
   - Desired Count: 1 (autoscaling configured)
   - Launch Type: Fargate
   - Network Mode: awsvpc
   - Subnets: private-1, private-2
   - Security Group: Allow inbound from ALB (port 8000)
   - Service Discovery: None (accessed via ALB)
   - Health Check: ALB target group health checks
   - IAM Task Role: S3 read/write, SQS send/receive, Secrets Manager read
   - Environment Variables: Database URL, SQS queue URLs, S3 bucket, ChromaDB host
   - Secrets: JWT secret, API keys (from Secrets Manager)
   - Logging: CloudWatch Logs `/ecs/vector-trace-rag-fastapi`

2. **ChromaDB Service**
   - Task Definition: 1 vCPU, 2GB RAM
   - Desired Count: 1
   - Launch Type: Fargate
   - Persistent Storage: EFS volume mounted at `/chroma/chroma`
   - Network Mode: awsvpc
   - Subnets: private-1, private-2
   - Security Group: Allow inbound from FastAPI security group (port 8000)
   - Service Discovery: Registered in Cloud Map as `chromadb.vector-trace-rag.local`
   - Health Check: HTTP GET /api/v2/heartbeat
   - Logging: CloudWatch Logs `/ecs/vector-trace-rag-chromadb`

**Autoscaling** (configured but not active):
- Target Tracking: CPU 70%, Memory 80%
- Scale out: +1 task when above threshold for 2 minutes
- Scale in: -1 task when below threshold for 5 minutes
- Min: 1, Max: 3

#### GPU Worker (EC2)

**Instance**: g4dn.xlarge (stopped to save costs)
- vCPUs: 4
- RAM: 16GB
- GPU: NVIDIA T4 (16GB VRAM)
- Storage: 100GB gp3 EBS
- AMI: Deep Learning AMI (Ubuntu 22.04) with CUDA 12.8, PyTorch 2.3
- Subnet: public-1 (for easier management)
- Security Group: SSH from specific IP, outbound HTTPS for S3/SQS

**Workers**: Docker containers managed with Docker Compose
- PDF Worker: Polls SQS document queue, processes with Unstructured.io
- Audio Worker: Polls SQS audio queue, transcribes with Faster-Whisper

### Load Balancing and CDN

#### Application Load Balancer

**Configuration**:
- Scheme: Internet-facing
- Subnets: public-1, public-2 (must span 2 AZs)
- Security Group: Allow inbound HTTP (80) from 0.0.0.0/0
- Target Group: FastAPI ECS tasks (port 8000)
- Health Check: GET / (200 OK), 30s interval, 2 consecutive successes

**Listeners**:
- HTTP:80 → Forward to FastAPI target group

**Target Health**:
- Targets: ECS tasks with dynamic port mapping
- Health: Continuous monitoring, unhealthy targets removed from rotation

#### CloudFront Distributions

**Frontend Distribution**:
- Origin: S3 static website bucket
- Alternate Domains: `vector-trace.faraaz-bhojawala.me`
- SSL Certificate: ACM certificate (us-east-1)
- Default Root Object: index.html
- Error Pages: 404 → 200 /index.html (SPA routing)
- Cache Behavior: Default CloudFront managed cache policy
- Compression: Enabled (Gzip, Brotli)
- HTTP/2, HTTP/3 enabled
- Security: HTTPS only (redirect HTTP to HTTPS)

**API Distribution** (optional HTTPS wrapper for ALB):
- Origin: Application Load Balancer
- Path Pattern: /api/*
- SSL Certificate: ACM certificate (us-east-1)
- Cache: Disabled for dynamic API responses
- Origin Protocol: HTTP (ALB → CloudFront)
- Viewer Protocol: HTTPS only

### Data Layer

#### RDS PostgreSQL


**Configuration**:
- Engine: PostgreSQL 15.4
- Instance Class: db.t3.micro (2 vCPU, 1GB RAM)
- Storage: 20GB gp2 (autoscaling enabled to 100GB)
- Multi-AZ: Disabled (single instance for cost optimization)
- Subnet Group: private-1, private-2
- Security Group: Allow inbound PostgreSQL (5432) from FastAPI security group
- Backup: Automated daily backups, 7-day retention
- Maintenance Window: Saturday 03:00-04:00 UTC
- Deletion Protection: Enabled
- Encryption: At rest (KMS default key)

**Schema**:
- Users table (authentication)
- Projects table (tenant isolation)
- Project members table (RBAC)
- Files table (document/audio metadata)
- Chat sessions table (conversation context)
- Chat messages table (message history)
- Database enums: FileStatus (UPLOADED, QUEUED, PROCESSING, COMPLETED, FAILED)

#### S3 Buckets

1. **Document Storage Bucket** (`vector-trace-rag-storage`)
   - Structure: `projects/{project_id}/raw/{file_id}.pdf`
   - Lifecycle: Transition to Intelligent-Tiering after 30 days
   - Versioning: Disabled
   - Encryption: SSE-S3 (AES-256)
   - Access: Private (IAM role-based access only)

2. **Processed Data Bucket** (`vector-trace-rag-processed`)
   - Structure: `projects/{project_id}/processed/{file_id}.json`
   - Contains: Partitioned chunks, embeddings metadata
   - Lifecycle: Transition to Infrequent Access after 90 days
   - Encryption: SSE-S3

3. **Frontend Bucket** (`vector-trace-rag-frontend`)
   - Structure: Static website files (index.html, _next/*, assets/*)
   - Hosting: S3 static website hosting
   - Access: Public read via CloudFront OAI (Origin Access Identity)
   - Encryption: SSE-S3

**S3 Access**:
- ECS task role has `s3:GetObject`, `s3:PutObject` for storage buckets
- EC2 instance role has `s3:GetObject`, `s3:PutObject` for processing
- CloudFront OAI has `s3:GetObject` for frontend bucket

#### EFS File System

**Purpose**: Persistent storage for ChromaDB vector database

**Configuration**:
- Performance Mode: General Purpose
- Throughput Mode: Bursting
- Encryption: At rest (KMS)
- Mount Targets: private-1, private-2
- Security Group: Allow NFS (2049) from ChromaDB ECS task security group

**Mount**:
- ChromaDB container mounts EFS at `/chroma/chroma`
- SQLite database and vector data persist across container restarts

### Message Queues

#### SQS Queues

1. **Document Ingestion Queue**
   - Visibility Timeout: 300 seconds (5 minutes for processing)
   - Message Retention: 4 days
   - Max Message Size: 256KB
   - Receive Wait Time: 20 seconds (long polling)
   - Dead Letter Queue: Configured with maxReceiveCount=3

2. **Audio Processing Queue**
   - Visibility Timeout: 600 seconds (10 minutes for transcription)
   - Message Retention: 4 days
   - Max Message Size: 256KB
   - Receive Wait Time: 20 seconds

**Message Format**:
```json
{
  "project_id": "1",
  "file_id": "uuid",
  "s3_key": "projects/1/raw/uuid.pdf",
  "original_filename": "document.pdf",
  "bucket_name": "vector-trace-rag-storage"
}
```

**Access**:
- FastAPI task role: `sqs:SendMessage`
- EC2 worker instance role: `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:ChangeMessageVisibility`

### Security Architecture

#### IAM Roles and Policies


1. **ECS Task Execution Role**
   - Purpose: Pull images from ECR, write to CloudWatch Logs
   - Policies: `AmazonECSTaskExecutionRolePolicy`
   - Additional: Secrets Manager read for specific secrets

2. **FastAPI Task Role**
   - S3 access: Read/write to storage and processed buckets
   - SQS access: Send messages to both queues
   - Secrets Manager: Read secrets (API keys, JWT secret)
   - CloudWatch: PutMetricData for custom metrics

3. **ChromaDB Task Role**
   - Minimal permissions (no external service access)
   - CloudWatch Logs write only

4. **EC2 Worker Instance Role**
   - S3 access: Read/write to all application buckets
   - SQS access: Receive/delete from both queues
   - CloudWatch Logs: Write worker logs
   - SSM: Session Manager access (no SSH keys needed)

5. **CodeBuild Service Role**
   - S3 access: Write to frontend bucket
   - CloudFront: CreateInvalidation for cache clearing
   - CloudWatch Logs: Write build logs
   - Secrets Manager: Read GitHub token

#### Security Groups

**Network Segmentation**:

1. **ALB Security Group**
   - Inbound: 0.0.0.0/0:80 (HTTP)
   - Outbound: FastAPI SG:8000

2. **FastAPI Security Group**
   - Inbound: ALB SG:8000
   - Outbound: ChromaDB SG:8000, RDS SG:5432, 0.0.0.0/0:443 (external APIs)

3. **ChromaDB Security Group**
   - Inbound: FastAPI SG:8000
   - Outbound: 0.0.0.0/0:443 (telemetry, updates)

4. **RDS Security Group**
   - Inbound: FastAPI SG:5432
   - Outbound: None

5. **EFS Security Group**
   - Inbound: ChromaDB SG:2049 (NFS)
   - Outbound: None

6. **GPU Worker Security Group**
   - Inbound: My IP:22 (SSH)
   - Outbound: 0.0.0.0/0:443 (S3, SQS, external APIs)

#### Secrets Management

**AWS Secrets Manager**:
- Secret: `vector-trace-rag/fastapi/app-secrets`
- Keys: SECRET_KEY, GROQ_API_KEY, GOOGLE_API_KEY
- Rotation: Manual (API keys from third parties)
- Access: ECS task execution role retrieves at container startup
- Encryption: KMS-encrypted

**Environment Variables** (non-sensitive):
- Database URL (private VPC, no internet exposure)
- S3 bucket names
- SQS queue URLs
- Region, algorithm, timeouts

### DNS and Domain Configuration

#### Route 53

**Hosted Zone**: `faraaz-bhojawala.me`
- Name servers: Configured in Namecheap registrar
- TTL: 300 seconds

**Records**:
- A record: `vector-trace.faraaz-bhojawala.me` → CloudFront (alias)
- CNAME records: ACM certificate validation records (auto-created by Terraform)

#### ACM Certificates

**Certificate**: `*.faraaz-bhojawala.me` (wildcard) or specific subdomain
- Validation: DNS validation via Route 53
- Region: us-east-1 (required for CloudFront)

### Monitoring and Logging

#### CloudWatch Logs

**Log Groups**:
- `/ecs/vector-trace-rag-fastapi`: API logs (INFO, ERROR levels)
- `/ecs/vector-trace-rag-chromadb`: Vector DB logs
- `/aws/codebuild/vector-trace-backend`: Backend CI/CD logs
- `/aws/codebuild/vector-trace-frontend`: Frontend CI/CD logs
- `/aws/lambda/...`: Future Lambda function logs

**Retention**: 7 days (configurable, adjust for cost vs. debugging needs)

**Log Insights Queries**:
- API errors: `fields @timestamp, @message | filter @message like /ERROR/`
- Slow queries: `fields @timestamp, @message | filter @message like /query_with_filter/ | stats avg(duration)`

#### CloudWatch Metrics

**Default Metrics**:
- ECS: CPUUtilization, MemoryUtilization per service
- ALB: RequestCount, TargetResponseTime, HTTPCode_Target_5XX_Count
- RDS: DatabaseConnections, FreeableMemory, ReadLatency, WriteLatency
- S3: BucketSizeBytes, NumberOfObjects


### CI/CD Pipeline

#### Architecture

**Trigger**: GitHub webhook on push to `main` branch

**Backend Pipeline** (Docker-based):
1. Developer pushes code to GitHub
2. GitHub Actions CI runs tests (optional)
3. Manual Docker build and push to ECR:
   ```bash
   docker build -t <ECR_REPO>:fastapi-latest .
   docker push <ECR_REPO>:fastapi-latest
   ```
4. ECS service update with force new deployment:
   ```bash
   aws ecs update-service --cluster vector-trace-rag-main-cluster \
     --service fastapi-service --force-new-deployment
   ```
5. ECS pulls new image from ECR
6. Rolling update (stop old task, start new task)
7. Health checks verify new task before removing old task

**Frontend Pipeline** (CodeBuild):
1. Developer pushes code to GitHub (frontend repo)
2. GitHub webhook triggers CodeBuild
3. CodeBuild executes `buildspec.yml`:
   - Install Node.js dependencies
   - Inject API URL as environment variable
   - Build Next.js static export (`npm run build`)
   - Sync build artifacts to S3 frontend bucket
   - Invalidate CloudFront cache
4. CloudFront serves updated frontend

**Rollback Strategy**:
- Backend: Revert to previous image tag in ECR, force new deployment
- Frontend: S3 versioning enabled, restore previous version

### Infrastructure as Code

**Terraform Structure**:
```
terraform/
├── main.tf              # All resource definitions
├── variables.tf         # Input variables
├── terraform.tfvars     # Variable values (not in Git)
├── outputs.tf           # Output values (ALB DNS, ECR URLs, etc.)
└── terraform.tfstate    # State file (not in Git)
```

**Resource Count**: ~60 resources managed by Terraform
- VPC resources: 15 (VPC, subnets, route tables, IGW, NAT, etc.)
- ECS resources: 10 (cluster, services, task definitions)
- Load balancing: 6 (ALB, target groups, listeners)
- Data layer: 8 (RDS, EFS, S3 buckets)
- Security: 12 (security groups, IAM roles/policies)
- CloudFront: 4 (distributions, OAI)
- DNS: 3 (hosted zone, records)
- Other: 5 (SQS, Secrets Manager references, CloudWatch)

**Terraform Commands**:
```bash
terraform init          # Initialize providers
terraform plan          # Preview changes
terraform apply         # Apply changes
terraform destroy       # Destroy all resources
terraform state list    # List managed resources
```
---

## Local Development

### Prerequisites

- Docker and Docker Compose
- Python 3.11
- PostgreSQL 15 (or use Docker)
- Redis (or use Docker)

### Setup

1. **Clone repository**:
   ```bash
   git clone https://github.com/Faraaz05/RAG-FASTAPI.git
   cd RAG-FASTAPI
   ```

2. **Create `.env` file**:
   ```env
   SECRET_KEY=your-local-secret-key
   ALGORITHM=HS256
   ACCESS_TOKEN_EXPIRE_MINUTES=300
   
   DATABASE_URL=postgresql://rag_user:your_secure_password@localhost:5432/rag_db
   REDIS_URL=redis://localhost:6379/0
   
   UPLOAD_DIR=./data/raw
   PROCESSED_DIR=./data/processed
   
   CHROMA_HOST=chromadb
   CHROMA_PORT=8000
   CHROMA_DB_PATH=./chroma_data
   
   GROQ_API_KEY=your-groq-api-key
   GOOGLE_API_KEY=your-google-api-key
   
   USE_S3=false
   USE_SQS=false
   ```

3. **Start infrastructure services**:
   ```bash
   docker compose up -d postgres redis chromadb
   ```

4. **Create database schema**:
   ```bash
   # Install dependencies
   pip install -r requirements_clean.txt
   
   # Run migrations
   alembic upgrade head
   ```

5. **Run FastAPI backend**:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

6. **Access API docs**:
   Open `http://localhost:8000/docs`

### Development with GPU Workers

For local document/audio processing:

```bash
# Ensure NVIDIA Docker runtime is installed
# docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi

# Start GPU workers
docker compose up -d pdf-worker faster-whisper

# Monitor logs
docker compose logs -f pdf-worker
```

### Frontend Development

See frontend repository for Next.js development setup.

**API Documentation**: Access interactive API documentation at `http://localhost:8000/docs` (Swagger UI) or `http://localhost:8000/redoc` (ReDoc)

---

## License

[Specify License - MIT, Apache 2.0, etc.]

---

## Contact

**Project Maintainer**: [Faraaz-Bhojawala]

**Email**: [bhojawalafaraaz@gmail.com]

**LinkedIn**: [https://www.linkedin.com/in/faraaz-bhojawala/](https://www.linkedin.com/in/faraaz-bhojawala/)

**GitHub**: [https://github.com/Faraaz05](https://github.com/Faraaz05)

---

## Acknowledgments

- **LangChain**: RAG orchestration framework
- **ChromaDB**: Vector database for embeddings
- **Unstructured.io**: Document partitioning library
- **Faster-Whisper**: GPU-accelerated speech recognition
- **Pyannote Audio**: Speaker diarization toolkit
- **FastAPI**: Modern Python web framework
- **Terraform**: Infrastructure as code

---
