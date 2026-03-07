provider "aws" {
  region = var.aws_region
}

# --------------------
# S3 Config
# --------------------

# S3 BUCKET creation
resource "aws_s3_bucket" "vector_trace_storage" {
  bucket = var.s3_bucket_name

  tags = {
    Name    = "${var.project_name}-storage"
    Project = var.project_name
  }
}

# S3 BUCKET creation access policies

resource "aws_s3_bucket_public_access_block" "storage_pab" {
  bucket = aws_s3_bucket.vector_trace_storage.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}


# --------------------
# VPC Config
# --------------------


# VPC creation
resource "aws_vpc" "main" {
  cidr_block = var.vpc_cidr
  enable_dns_support = true
  enable_dns_hostnames = true

  tags = {
    Name    = "${var.project_name}-vpc"
    Project = var.project_name
  }

}

# ------------------------------------
# DHCP OPTIONS SET (for Cloud Map DNS)
# ------------------------------------

resource "aws_vpc_dhcp_options" "main" {
  domain_name_servers = ["AmazonProvidedDNS"]
  domain_name         = "${var.aws_region}.compute.internal"

  tags = {
    Name    = "${var.project_name}-dhcp-options"
    Project = var.project_name
  }
}

resource "aws_vpc_dhcp_options_association" "main" {
  vpc_id          = aws_vpc.main.id
  dhcp_options_id = aws_vpc_dhcp_options.main.id
}

# Internet Gateway

resource "aws_internet_gateway" "gw" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name    = "${var.project_name}-gw"
    Project = var.project_name
  }

}

# private subnet 1

resource "aws_subnet" "private-1" {
  vpc_id     = aws_vpc.main.id
  cidr_block = var.private_subnet_cidr
  availability_zone = var.availability_zone

  tags = {
    Name    = "${var.project_name}-private-1"
    Project = var.project_name
  }
}


# public subnet 1
resource "aws_subnet" "public-1" {
  vpc_id     = aws_vpc.main.id
  cidr_block = var.public_subnet_cidr
  availability_zone = var.availability_zone
  map_public_ip_on_launch = true  

  tags = {
    Name    = "${var.project_name}-public-1"
    Project = var.project_name
  }
}

# Public subnet 2 (required for ALB high availability)
resource "aws_subnet" "public-2" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidr_2
  availability_zone       = var.availability_zone_2
  map_public_ip_on_launch = true

  tags = {
    Name    = "${var.project_name}-public-2"
    Project = var.project_name
  }
}

# Route table association for public-2
resource "aws_route_table_association" "public-2" {
  subnet_id      = aws_subnet.public-2.id
  route_table_id = aws_route_table.public.id
}

# Elastic IP for nat gateway

resource "aws_eip" "nat-eip" {
  domain = "vpc"
}

# NAT gateway in public subnet 

resource "aws_nat_gateway" "nat" {
  allocation_id = aws_eip.nat-eip.id
  subnet_id     = aws_subnet.public-1.id

  tags = {
    Name    = "${var.project_name}-nat"
    Project = var.project_name
}

  # To ensure proper ordering, it is recommended to add an explicit dependency
  # on the Internet Gateway for the VPC.
  depends_on = [aws_internet_gateway.gw]
}

# Public route table

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.gw.id
  }

  tags = {
    Name    = "${var.project_name}-route-table-public"
    Project = var.project_name
}
}


# Private route table

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.nat.id
  }

  tags = {
    Name    = "${var.project_name}-route-table-private"
    Project = var.project_name
}
}

# Route table assiciation

resource "aws_route_table_association" "public-1" {
  subnet_id      = aws_subnet.public-1.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private-1" {
  subnet_id      = aws_subnet.private-1.id
  route_table_id = aws_route_table.private.id
}


# ---------------------------------
# SECURITY GROUPS (ALB)
# ---------------------------------

resource "aws_security_group" "alb-sg" {
  name        = "${var.project_name}-alb-sg"
  description = "Allow HTTP/S and SSH for Vector Trace Rag"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name    = "${var.project_name}-alb-sg"
    Project = var.project_name
}
}

# HTTP rule (Port 80) , allow all http ipv4
resource "aws_vpc_security_group_ingress_rule" "alb-allow_http_ipv4" {
  security_group_id = aws_security_group.alb-sg.id
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

# HTTPS rule (Port 443) , allow all https ipv4
resource "aws_vpc_security_group_ingress_rule" "alb-allow_https_ipv4" {
  security_group_id = aws_security_group.alb-sg.id
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

# Allow all IPv6 HTTP traffic
resource "aws_vpc_security_group_ingress_rule" "alb-allow_http_ipv6" {
  security_group_id = aws_security_group.alb-sg.id
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
  cidr_ipv6         = "::/0" 
}

# Allow all IPv6 HTTPS traffic
resource "aws_vpc_security_group_ingress_rule" "alb-allow_https_ipv6" {
  security_group_id = aws_security_group.alb-sg.id
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv6         = "::/0"
}

# Allow outbound to FastAPI port 8000
resource "aws_vpc_security_group_egress_rule" "alb-to-fastapi" {
  security_group_id = aws_security_group.alb-sg.id
  
  referenced_security_group_id = aws_security_group.fastapi-ecs-sg.id
  from_port   = 8000
  ip_protocol = "tcp"
  to_port     = 8000
}

# ------------------------------------
# SECURITY GROUP (FASTAPI)
# ------------------------------------

resource "aws_security_group" "fastapi-ecs-sg" {
  name        = "${var.project_name}-fastapi-ecs-sg"
  description = "Allow All outbound https and allow outbound 5432(rds) , 8000 chromadb and ingrress from ALB 8000 "
  vpc_id      = aws_vpc.main.id

  tags = {
    Name    = "${var.project_name}-fastapi-ecs-sg"
    Project = var.project_name
}
}


resource "aws_vpc_security_group_ingress_rule" "fastapi-allow-from-alb" {
  security_group_id = aws_security_group.fastapi-ecs-sg.id

  from_port         = 8000
  to_port           = 8000
  ip_protocol       = "tcp"
  referenced_security_group_id = aws_security_group.alb-sg.id
}


resource "aws_vpc_security_group_egress_rule" "fastapi-allow_outbound_https" {
  security_group_id = aws_security_group.fastapi-ecs-sg.id
  
  cidr_ipv4   = "0.0.0.0/0"
  from_port   = 443
  ip_protocol = "tcp"
  to_port     = 443
}

resource "aws_vpc_security_group_egress_rule" "fastapi-to-rds" {
  security_group_id = aws_security_group.fastapi-ecs-sg.id
  
  referenced_security_group_id = aws_security_group.rds-sg.id
  from_port   = 5432
  ip_protocol = "tcp"
  to_port     = 5432
}

resource "aws_vpc_security_group_egress_rule" "fastapi-to-chromadb" {
  security_group_id = aws_security_group.fastapi-ecs-sg.id
  
  referenced_security_group_id = aws_security_group.chromadb-ecs-sg.id
  from_port   = 8000
  ip_protocol = "tcp"
  to_port     = 8000
}

# ----------------------------
# SECURITY GROUP (CHROMADB)
# ----------------------------

resource "aws_security_group" "chromadb-ecs-sg" {
  name        = "${var.project_name}-chromadb-ecs-sg"
  description = "Allow All egress https ingress from FastAPI and GPU IMAGES"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name    = "${var.project_name}-chromadb-ecs-sg"
    Project = var.project_name
}
}

resource "aws_vpc_security_group_ingress_rule" "chromadb-from-fastapi" {
  security_group_id = aws_security_group.chromadb-ecs-sg.id

  from_port         = 8000
  to_port           = 8000
  ip_protocol       = "tcp"
  referenced_security_group_id = aws_security_group.fastapi-ecs-sg.id
}

resource "aws_vpc_security_group_ingress_rule" "chromadb-from-gpu-worker" {
  security_group_id = aws_security_group.chromadb-ecs-sg.id

  from_port         = 8000
  to_port           = 8000
  ip_protocol       = "tcp"
  referenced_security_group_id = aws_security_group.worker-ecs-sg.id
}


resource "aws_vpc_security_group_egress_rule" "chromadb-allow_outbound_https" {
  security_group_id = aws_security_group.chromadb-ecs-sg.id
  
  cidr_ipv4   = "0.0.0.0/0"
  from_port   = 443
  ip_protocol = "tcp"
  to_port     = 443
}

# Allow ChromaDB to connect to EFS on port 2049 (NFS)
resource "aws_vpc_security_group_egress_rule" "chromadb-to-efs" {
  security_group_id = aws_security_group.chromadb-ecs-sg.id
  
  referenced_security_group_id = aws_security_group.efs_sg.id
  from_port   = 2049
  ip_protocol = "tcp"
  to_port     = 2049
}

# -----------------------
# SECURITY GROUP (RDS)
# -------------------------

resource "aws_security_group" "rds-sg" {
  name        = "${var.project_name}-rds-sg"
  description = "Allow All egress https ingress from FastAPI and GPU IMAGES"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name    = "${var.project_name}-rds-sg"
    Project = var.project_name
}
}

resource "aws_vpc_security_group_ingress_rule" "rds-from-fastapi" {
  security_group_id = aws_security_group.rds-sg.id

  from_port         = 5432
  to_port           = 5432
  ip_protocol       = "tcp"
  referenced_security_group_id = aws_security_group.fastapi-ecs-sg.id
}


resource "aws_vpc_security_group_ingress_rule" "rds-from-gpu-worker" {
  security_group_id = aws_security_group.rds-sg.id

  from_port         = 5432
  to_port           = 5432
  ip_protocol       = "tcp"
  referenced_security_group_id = aws_security_group.worker-ecs-sg.id
}

# ------------------------------
# SECURITY GROUP (GPU IMAGES)
# -------------------------------

resource "aws_security_group" "worker-ecs-sg" {
  name        = "${var.project_name}-worker-ecs-sg"
  description = "Allow All egress https and egress to RDS and CHROMADB"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name    = "${var.project_name}-worker-ecs-sg"
    Project = var.project_name
}
}

resource "aws_vpc_security_group_egress_rule" "worker-to-chromadb" {
  security_group_id = aws_security_group.worker-ecs-sg.id
  
  referenced_security_group_id = aws_security_group.chromadb-ecs-sg.id
  from_port   = 8000
  ip_protocol = "tcp"
  to_port     = 8000
}

resource "aws_vpc_security_group_egress_rule" "worker-to-rds" {
  security_group_id = aws_security_group.worker-ecs-sg.id
  
  referenced_security_group_id = aws_security_group.rds-sg.id
  from_port   = 5432
  ip_protocol = "tcp"
  to_port     = 5432
}

resource "aws_vpc_security_group_egress_rule" "worker-allow_outbound_https" {
  security_group_id = aws_security_group.worker-ecs-sg.id
  
  cidr_ipv4   = "0.0.0.0/0"
  from_port   = 443
  ip_protocol = "tcp"
  to_port     = 443
}



# ------------------------------------
# SQS QUEUES
# ------------------------------------

# Dead Letter Queue for Document Processing
resource "aws_sqs_queue" "document_dlq" {
  name                      = "${var.project_name}-ingestion-queue-dlq"
  message_retention_seconds = 1209600  # 14 days

  tags = {
    Name    = "${var.project_name}-document-dlq"
    Project = var.project_name
  }
}

# Document Processing Queue (ingestion_queue)
resource "aws_sqs_queue" "document_queue" {
  name                       = "${var.project_name}-ingestion-queue"
  delay_seconds              = 0
  max_message_size           = 262144  # 256 KB
  message_retention_seconds  = var.sqs_message_retention_seconds
  visibility_timeout_seconds = var.sqs_visibility_timeout_seconds
  receive_wait_time_seconds  = 20  # Long polling

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.document_dlq.arn
    maxReceiveCount     = var.sqs_max_receive_count
  })

  tags = {
    Name    = "${var.project_name}-ingestion-queue"
    Project = var.project_name
  }
}

# Dead Letter Queue for Audio/Video Processing
resource "aws_sqs_queue" "audio_dlq" {
  name                      = "${var.project_name}-audio-queue-dlq"
  message_retention_seconds = 1209600  # 14 days

  tags = {
    Name    = "${var.project_name}-audio-dlq"
    Project = var.project_name
  }
}

# Audio/Video Processing Queue (audio_queue)
resource "aws_sqs_queue" "audio_queue" {
  name                       = "${var.project_name}-audio-queue"
  delay_seconds              = 0
  max_message_size           = 262144  # 256 KB
  message_retention_seconds  = var.sqs_message_retention_seconds
  visibility_timeout_seconds = var.sqs_visibility_timeout_seconds
  receive_wait_time_seconds  = 20  # Long polling

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.audio_dlq.arn
    maxReceiveCount     = var.sqs_max_receive_count
  })

  tags = {
    Name    = "${var.project_name}-audio-queue"
    Project = var.project_name
  }
}

# Outputs for queue URLs (needed for app config)
output "sqs_queue_url" {
  value       = aws_sqs_queue.document_queue.url
  description = "URL of document ingestion queue"
}

output "sqs_audio_queue_url" {
  value       = aws_sqs_queue.audio_queue.url
  description = "URL of audio/video processing queue"
}

output "document_dlq_url" {
  value       = aws_sqs_queue.document_dlq.url
  description = "URL of document DLQ"
}

output "audio_dlq_url" {
  value       = aws_sqs_queue.audio_dlq.url
  description = "URL of audio DLQ"
}

# Private subnet 2 (required for RDS subnet group)
resource "aws_subnet" "private-2" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.private_subnet_cidr_2
  availability_zone = var.availability_zone_2

  tags = {
    Name    = "${var.project_name}-private-2"
    Project = var.project_name
  }
}

# Route table association for private-2
resource "aws_route_table_association" "private-2" {
  subnet_id      = aws_subnet.private-2.id
  route_table_id = aws_route_table.private.id
}


# ------------------------------------
# RDS POSTGRESQL DATABASE
# ------------------------------------

# DB Subnet Group (requires 2+ subnets in different AZs)
resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-db-subnet-group"
  subnet_ids = [aws_subnet.private-1.id, aws_subnet.private-2.id]

  tags = {
    Name    = "${var.project_name}-db-subnet-group"
    Project = var.project_name
  }
}

# RDS PostgreSQL Instance
resource "aws_db_instance" "postgres" {
  identifier        = "${var.project_name}-postgres"
  engine            = "postgres"
  engine_version    = var.db_engine_version
  instance_class    = var.db_instance_class
  allocated_storage = var.db_allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  # Network
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds-sg.id]
  publicly_accessible    = false

  # Backups disabled
  backup_retention_period = 0  # No automated backups

  # HA disabled for cost savings
  multi_az = false

  # Deletion
  deletion_protection       = false
  skip_final_snapshot      = true

  # Monitoring
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
  auto_minor_version_upgrade      = true

  tags = {
    Name    = "${var.project_name}-postgres"
    Project = var.project_name
  }
}


# Outputs
output "rds_endpoint" {
  value       = aws_db_instance.postgres.endpoint
  description = "RDS endpoint (host:port)"
}

output "rds_address" {
  value       = aws_db_instance.postgres.address
  description = "RDS hostname"
}

# ------------------------------------
# IAM ROLES - ECS TASK EXECUTION
# ------------------------------------

# ECS Task Execution Role (used by ECS service to pull images, write logs)
resource "aws_iam_role" "ecs_task_execution_role" {
  name = "${var.project_name}-ecs-task-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name    = "${var.project_name}-ecs-task-execution-role"
    Project = var.project_name
  }
}

# Attach AWS managed policy for ECS task execution
resource "aws_iam_role_policy_attachment" "ecs_task_execution_role_policy" {
  role       = aws_iam_role.ecs_task_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Allow ECS task execution role to create CloudWatch log groups
resource "aws_iam_role_policy" "ecs_task_execution_logs" {
  name = "${var.project_name}-ecs-logs-policy"
  role = aws_iam_role.ecs_task_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/ecs/${var.project_name}-*"
      }
    ]
  })
}

# Allow ECS task execution role to read secrets from Secrets Manager
resource "aws_iam_role_policy" "ecs_task_execution_secrets" {
  name = "${var.project_name}-ecs-secrets-policy"
  role = aws_iam_role.ecs_task_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:*:secret:${var.project_name}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "secretsmanager.${var.aws_region}.amazonaws.com"
          }
        }
      }
    ]
  })
}

# Output the role ARN (needed for task definitions)
output "ecs_task_execution_role_arn" {
  value       = aws_iam_role.ecs_task_execution_role.arn
  description = "ARN of ECS task execution role"
}



# ------------------------------------
# IAM ROLE - FASTAPI TASK
# ------------------------------------

# FastAPI Task Role (used by FastAPI container at runtime)
resource "aws_iam_role" "fastapi_task_role" {
  name = "${var.project_name}-fastapi-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name    = "${var.project_name}-fastapi-task-role"
    Project = var.project_name
  }
}

# FastAPI permissions: S3, SQS write
resource "aws_iam_role_policy" "fastapi_task_policy" {
  name = "${var.project_name}-fastapi-policy"
  role = aws_iam_role.fastapi_task_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          "${aws_s3_bucket.vector_trace_storage.arn}",
          "${aws_s3_bucket.vector_trace_storage.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:GetQueueUrl",
          "sqs:GetQueueAttributes"
        ]
        Resource = [
          aws_sqs_queue.document_queue.arn,
          aws_sqs_queue.audio_queue.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "fastapi_task_ssm" {
  role       = aws_iam_role.fastapi_task_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Output FastAPI task role ARN
output "fastapi_task_role_arn" {
  value       = aws_iam_role.fastapi_task_role.arn
  description = "ARN of FastAPI task role"
}

# ------------------------------------
# IAM ROLE - CHROMADB TASK
# ------------------------------------

# ChromaDB Task Role (minimal permissions - no AWS service access needed)
resource "aws_iam_role" "chromadb_task_role" {
  name = "${var.project_name}-chromadb-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name    = "${var.project_name}-chromadb-task-role"
    Project = var.project_name
  }
}

# No additional policies needed - ChromaDB only needs EFS mount (handled by ECS)

# Output ChromaDB task role ARN
output "chromadb_task_role_arn" {
  value       = aws_iam_role.chromadb_task_role.arn
  description = "ARN of ChromaDB task role"
}


# ------------------------------------
# IAM ROLE - PDF WORKER TASK
# ------------------------------------

# PDF Worker Task Role (used by document processing container)
resource "aws_iam_role" "pdf_worker_task_role" {
  name = "${var.project_name}-pdf-worker-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name    = "${var.project_name}-pdf-worker-task-role"
    Project = var.project_name
  }
}

# PDF Worker permissions: S3, SQS read/delete
resource "aws_iam_role_policy" "pdf_worker_task_policy" {
  name = "${var.project_name}-pdf-worker-policy"
  role = aws_iam_role.pdf_worker_task_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          "${aws_s3_bucket.vector_trace_storage.arn}",
          "${aws_s3_bucket.vector_trace_storage.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = aws_sqs_queue.document_queue.arn
      }
    ]
  })
}

# Output PDF worker task role ARN
output "pdf_worker_task_role_arn" {
  value       = aws_iam_role.pdf_worker_task_role.arn
  description = "ARN of PDF worker task role"
}

# ------------------------------------
# IAM ROLE - AUDIO WORKER TASK
# ------------------------------------

# Audio Worker Task Role (used by audio/video processing container)
resource "aws_iam_role" "audio_worker_task_role" {
  name = "${var.project_name}-audio-worker-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name    = "${var.project_name}-audio-worker-task-role"
    Project = var.project_name
  }
}

# Audio Worker permissions: S3, SQS read/delete
resource "aws_iam_role_policy" "audio_worker_task_policy" {
  name = "${var.project_name}-audio-worker-policy"
  role = aws_iam_role.audio_worker_task_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          "${aws_s3_bucket.vector_trace_storage.arn}",
          "${aws_s3_bucket.vector_trace_storage.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = aws_sqs_queue.audio_queue.arn
      }
    ]
  })
}

# Output Audio worker task role ARN
output "audio_worker_task_role_arn" {
  value       = aws_iam_role.audio_worker_task_role.arn
  description = "ARN of Audio worker task role"
}


# ------------------------------------
# EFS - CHROMADB PERSISTENT STORAGE
# ------------------------------------

# Security Group for EFS
resource "aws_security_group" "efs_sg" {
  name        = "${var.project_name}-efs-sg"
  description = "Allow NFS access from ChromaDB ECS tasks"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name    = "${var.project_name}-efs-sg"
    Project = var.project_name
  }
}

# Allow NFS (2049) from ChromaDB security group
resource "aws_vpc_security_group_ingress_rule" "efs_from_chromadb" {
  security_group_id = aws_security_group.efs_sg.id

  from_port                    = 2049
  to_port                      = 2049
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.chromadb-ecs-sg.id
}

# Allow outbound to ChromaDB (for mount confirmation)
resource "aws_vpc_security_group_egress_rule" "efs_to_chromadb" {
  security_group_id = aws_security_group.efs_sg.id

  from_port                    = 2049
  to_port                      = 2049
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.chromadb-ecs-sg.id
}

# EFS File System
resource "aws_efs_file_system" "chromadb" {
  creation_token   = "${var.project_name}-chromadb-efs"
  performance_mode = var.efs_performance_mode
  throughput_mode  = var.efs_throughput_mode

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"  # Move to Infrequent Access after 30 days (cost savings)
  }

  tags = {
    Name    = "${var.project_name}-chromadb-efs"
    Project = var.project_name
  }
}


# EFS Mount Target in Private Subnet 1
resource "aws_efs_mount_target" "chromadb_private_1" {
  file_system_id  = aws_efs_file_system.chromadb.id
  subnet_id       = aws_subnet.private-1.id
  security_groups = [aws_security_group.efs_sg.id]
}

# EFS Mount Target in Private Subnet 2
resource "aws_efs_mount_target" "chromadb_private_2" {
  file_system_id  = aws_efs_file_system.chromadb.id
  subnet_id       = aws_subnet.private-2.id
  security_groups = [aws_security_group.efs_sg.id]
}


resource "aws_efs_access_point" "chromadb" {
  file_system_id = aws_efs_file_system.chromadb.id

  root_directory {
    path = "/chromadb"
    creation_info {
      owner_gid   = 1000
      owner_uid   = 1000
      permissions = "755"
    }
  }

  posix_user {
    gid = 1000
    uid = 1000
  }

  tags = {
    Name    = "${var.project_name}-chromadb-access-point"
    Project = var.project_name
  }
}

# Outputs
output "efs_id" {
  value       = aws_efs_file_system.chromadb.id
  description = "EFS file system ID"
}

output "efs_access_point_id" {
  value       = aws_efs_access_point.chromadb.id
  description = "EFS access point ID for ChromaDB"
}


# ------------------------------------
# ECS CLUSTER
# ------------------------------------

# ECS Cluster for all services
resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-${var.ecs_cluster_name}"

  setting {
    name  = "containerInsights"
    value = "enabled"  # CloudWatch Container Insights for monitoring
  }

  tags = {
    Name    = "${var.project_name}-ecs-cluster"
    Project = var.project_name
  }
}

# ECS Cluster Capacity Providers
resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]  # For FastAPI + ChromaDB

  # Default to Fargate for non-GPU tasks
  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1
  }
}

# Output
output "ecs_cluster_id" {
  value       = aws_ecs_cluster.main.id
  description = "ECS cluster ID"
}

output "ecs_cluster_name" {
  value       = aws_ecs_cluster.main.name
  description = "ECS cluster name"
}


# ------------------------------------
# ECS TASK DEFINITION - FASTAPI
# ------------------------------------

resource "aws_ecs_task_definition" "fastapi" {
  family                   = "${var.project_name}-fastapi"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.fastapi_cpu
  memory                   = var.fastapi_memory
  
  execution_role_arn = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn      = aws_iam_role.fastapi_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "fastapi"
      image     = var.ecr_fastapi_image
      essential = true

      portMappings = [
        {
          containerPort = var.fastapi_container_port
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "DATABASE_URL"
          value = "postgresql://${var.db_username}:${var.db_password}@${aws_db_instance.postgres.address}:5432/${var.db_name}"
        },
        {
          name  = "CHROMA_HOST"
          value = "chromadb.${aws_service_discovery_private_dns_namespace.main.name}"  
        },  
        {
          name  = "CHROMA_PORT"
          value = tostring(var.chromadb_container_port)
        },
        {
          name  = "S3_BUCKET_NAME"
          value = var.s3_bucket_name
        },
        {
          name  = "SQS_QUEUE_URL"
          value = aws_sqs_queue.document_queue.url
        },
        {
          name  = "SQS_AUDIO_QUEUE_URL"
          value = aws_sqs_queue.audio_queue.url
        },
        {
          name  = "USE_SQS"
          value = "true"
        },
        {
          name  = "USE_S3"
          value = "true"
        },
        {
          name  = "AWS_DEFAULT_REGION"
          value = var.aws_region
        },
        {
          name  = "ALGORITHM"
          value = "HS256"
        },
        {
          name  = "ACCESS_TOKEN_EXPIRE_MINUTES"
          value = "300"
        }
      ]

      # Secrets from manually created Secrets Manager
      secrets = [
        {
          name      = "SECRET_KEY"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:372885057927:secret:${var.project_name}/fastapi/app-secrets:SECRET_KEY::"
        },
        {
          name      = "GROQ_API_KEY"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:372885057927:secret:${var.project_name}/fastapi/app-secrets:GROQ_API_KEY::"
        },
        {
          name      = "GOOGLE_API_KEY"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:372885057927:secret:${var.project_name}/fastapi/app-secrets:GOOGLE_API_KEY::"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/${var.project_name}-fastapi"
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "fastapi"
          "awslogs-create-group"  = "true"
        }
      }

      # healthCheck = {
      #   command     = ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
      #   interval    = 30
      #   timeout     = 5
      #   retries     = 3
      #   startPeriod = 60
      # }
    }
  ])

  tags = {
    Name    = "${var.project_name}-fastapi-task"
    Project = var.project_name
  }
}


# ------------------------------------
# ECS TASK DEFINITION - CHROMADB
# ------------------------------------

resource "aws_ecs_task_definition" "chromadb" {
  family                   = "${var.project_name}-chromadb"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.chromadb_cpu
  memory                   = var.chromadb_memory
  
  execution_role_arn = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn      = aws_iam_role.chromadb_task_role.arn

  # EFS volume for persistent storage
  volume {
    name = "chromadb-data"

    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.chromadb.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.chromadb.id
        iam             = "ENABLED"
      }
    }
  }

  container_definitions = jsonencode([
    {
      name      = "chromadb"
      image     = var.ecr_chromadb_image
      essential = true

      portMappings = [
        {
          containerPort = var.chromadb_container_port
          protocol      = "tcp"
        }
      ]

      mountPoints = [
        {
          sourceVolume  = "chromadb-data"
          containerPath = "/chroma/chroma"
          readOnly      = false
        }
      ]

      environment = [
        {
          name  = "IS_PERSISTENT"
          value = "TRUE"
        },
        {
          name  = "PERSIST_DIRECTORY"
          value = "/chroma/chroma"
        },
        {
          name  = "ANONYMIZED_TELEMETRY"
          value = "FALSE"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/${var.project_name}-chromadb"
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "chromadb"
          "awslogs-create-group"  = "true"
        }
      }

      # healthCheck = {
      #   command     = ["CMD-SHELL", "curl -f http://localhost:8000/api/v1/heartbeat || exit 1"]
      #   interval    = 30
      #   timeout     = 5
      #   retries     = 3
      #   startPeriod = 60
      # }
    }
  ])

  tags = {
    Name    = "${var.project_name}-chromadb-task"
    Project = var.project_name
  }
}

# Output
output "chromadb_task_definition_arn" {
  value       = aws_ecs_task_definition.chromadb.arn
  description = "ARN of ChromaDB task definition"
}


# ------------------------------------
# AWS CLOUD MAP - SERVICE DISCOVERY
# ------------------------------------

# Private DNS namespace for service-to-service communication
resource "aws_service_discovery_private_dns_namespace" "main" {
  name        = "${var.project_name}.local"
  description = "Private DNS namespace for ECS service discovery"
  vpc         = aws_vpc.main.id

  tags = {
    Name    = "${var.project_name}-service-discovery"
    Project = var.project_name
  }
}

# Service discovery for ChromaDB
resource "aws_service_discovery_service" "chromadb" {
  name = "chromadb"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  tags = {
    Name    = "${var.project_name}-chromadb-discovery"
    Project = var.project_name
  }
}

# ------------------------------------
# ECS SERVICE - CHROMADB
# ------------------------------------

# ChromaDB service (deploy first - FastAPI depends on it)
resource "aws_ecs_service" "chromadb" {
  name            = "chromadb-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.chromadb.arn
  desired_count   = var.chromadb_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = [aws_subnet.private-1.id]
    security_groups  = [aws_security_group.chromadb-ecs-sg.id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.chromadb.arn
  }

  enable_execute_command = true  # For debugging with ECS Exec

  tags = {
    Name    = "${var.project_name}-chromadb-service"
    Project = var.project_name
  }

  depends_on = [
    aws_efs_mount_target.chromadb_private_1,
    aws_efs_mount_target.chromadb_private_2
  ]
}

# ------------------------------------
# ECS SERVICE - FASTAPI
# ------------------------------------

resource "aws_ecs_service" "fastapi" {
  name            = "fastapi-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.fastapi.arn
  desired_count   = var.fastapi_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = [aws_subnet.private-1.id]
    security_groups  = [aws_security_group.fastapi-ecs-sg.id]
    assign_public_ip = false  # Will use ALB for public access
  }

  enable_execute_command = true  # For debugging with ECS Exec

  load_balancer {
    target_group_arn = aws_lb_target_group.fastapi.arn
    container_name   = "fastapi"
    container_port   = var.fastapi_container_port
  }

  tags = {
    Name    = "${var.project_name}-fastapi-service"
    Project = var.project_name
  }

  depends_on = [
    aws_ecs_service.chromadb  # Wait for ChromaDB to be running
  ]
}

# Outputs
output "chromadb_service_name" {
  value       = aws_ecs_service.chromadb.name
  description = "ChromaDB ECS service name"
}

output "fastapi_service_name" {
  value       = aws_ecs_service.fastapi.name
  description = "FastAPI ECS service name"
}

output "chromadb_dns" {
  value       = "chromadb.${var.project_name}.local"
  description = "ChromaDB service discovery DNS"
}

# ------------------------------------
# APPLICATION LOAD BALANCER
# ------------------------------------

# ALB in public subnet
resource "aws_lb" "main" {
  name               = "${var.project_name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb-sg.id]
  subnets            = [aws_subnet.public-1.id, aws_subnet.public-2.id]  # ALB needs 2+ subnets

  enable_deletion_protection = false  # Set true for production
  enable_http2              = true
  idle_timeout              = var.alb_idle_timeout

  tags = {
    Name    = "${var.project_name}-alb"
    Project = var.project_name
  }
}

# Target Group for FastAPI
resource "aws_lb_target_group" "fastapi" {
  name        = "${var.project_name}-fastapi-tg"
  port        = var.fastapi_container_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"  # Required for Fargate

  # health_check {
  #   enabled             = true
  #   healthy_threshold   = 2
  #   unhealthy_threshold = 3
  #   timeout             = 5
  #   interval            = 30
  #   path                = var.health_check_path
  #   protocol            = "HTTP"
  #   matcher             = "200"
  # }

  deregistration_delay = 30

  tags = {
    Name    = "${var.project_name}-fastapi-tg"
    Project = var.project_name
  }
}

# HTTP Listener (Port 80)
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = "80"
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.fastapi.arn
  }

  tags = {
    Name    = "${var.project_name}-http-listener"
    Project = var.project_name
  }
}

# Outputs
output "alb_dns_name" {
  value       = aws_lb.main.dns_name
  description = "ALB DNS name (use this to access FastAPI)"
}

output "alb_url" {
  value       = "http://${aws_lb.main.dns_name}"
  description = "FastAPI URL via ALB"
}



# ------------------------------------
# GPU EC2 INSTANCE (Custom AMI)
# ------------------------------------


# ------------------------------------
# IAM ROLE - GPU EC2 INSTANCE (Docker Workers)
# ------------------------------------

# EC2 Instance Role
resource "aws_iam_role" "gpu_instance_role" {
  name = "${var.project_name}-gpu-instance-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name    = "${var.project_name}-gpu-instance-role"
    Project = var.project_name
  }
}

# S3 + SQS permissions
resource "aws_iam_role_policy" "gpu_instance_policy" {
  name = "${var.project_name}-gpu-instance-policy"
  role = aws_iam_role.gpu_instance_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          "${aws_s3_bucket.vector_trace_storage.arn}",
          "${aws_s3_bucket.vector_trace_storage.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = [
          aws_sqs_queue.document_queue.arn,
          aws_sqs_queue.audio_queue.arn
        ]
      }
    ]
  })
}

# SSM access (for AWS Systems Manager Session Manager - no SSH needed)
resource "aws_iam_role_policy_attachment" "gpu_instance_ssm" {
  role       = aws_iam_role.gpu_instance_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# EC2 Instance Profile (wraps the IAM role for EC2)
resource "aws_iam_instance_profile" "gpu_instance_profile" {
  name = "${var.project_name}-gpu-instance-profile"
  role = aws_iam_role.gpu_instance_role.name

  tags = {
    Name    = "${var.project_name}-gpu-instance-profile"
    Project = var.project_name
  }
}


# ------------------------------------
# GPU EC2 USER DATA - START DOCKER COMPOSE
# ------------------------------------

# User data script to start docker-compose on boot
# ------------------------------------
# GPU EC2 USER DATA - START DOCKER COMPOSE
# ------------------------------------

# User data script to start docker-compose on boot
data "template_file" "gpu_docker_compose_startup" {
  template = <<-EOF
    #!/bin/bash
    set -e
    
    # Get directory from docker-compose path
    COMPOSE_DIR=$(dirname "${var.gpu_docker_compose_path}")
    
    # Navigate to docker-compose directory
    cd $COMPOSE_DIR
    
    # Start docker-compose workers in detached mode
    docker-compose -f ${var.gpu_docker_compose_path} up -d
  EOF
}

# GPU EC2 Instance with Custom AMI
resource "aws_instance" "gpu_worker" {
  ami           = var.gpu_custom_ami
  instance_type = var.gpu_instance_type

  subnet_id              = aws_subnet.private-1.id
  vpc_security_group_ids = [aws_security_group.worker-ecs-sg.id]
  iam_instance_profile   = aws_iam_instance_profile.gpu_instance_profile.name

  user_data = data.template_file.gpu_docker_compose_startup.rendered

  private_dns_name_options {
    enable_resource_name_dns_a_record = true
    hostname_type                      = "ip-name"
  }

  tags = {
    Name    = "${var.project_name}-gpu-worker"
    Project = var.project_name
    Type    = "docker-worker"
  }

  depends_on = [
    aws_vpc_dhcp_options_association.main  # Wait for DHCP options
  ]
}

# Outputs
output "gpu_instance_id" {
  value       = aws_instance.gpu_worker.id
  description = "GPU EC2 instance ID"
}

output "gpu_instance_private_ip" {
  value       = aws_instance.gpu_worker.private_ip
  description = "GPU EC2 private IP (for ChromaDB/RDS access)"
}

# ------------------------------------
# S3 BUCKET FOR FRONTEND
# ------------------------------------

resource "aws_s3_bucket" "frontend" {
  bucket = "${var.project_name}-frontend"

  tags = {
    Name    = "${var.project_name}-frontend"
    Project = var.project_name
  }
}

# Public access block (CloudFront will access via OAC)
resource "aws_s3_bucket_public_access_block" "frontend_pab" {
  bucket = aws_s3_bucket.frontend.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Enable static website hosting
resource "aws_s3_bucket_website_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "index.html"  # For React Router (SPA)
  }
}

# ------------------------------------
# CLOUDFRONT DISTRIBUTION
# ------------------------------------

# Origin Access Control (OAC) for S3
resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${var.project_name}-frontend-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# CloudFront distribution
resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100"  # Use only North America and Europe (cheapest)

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "S3-${aws_s3_bucket.frontend.id}"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  default_cache_behavior {
    allowed_methods  = ["GET", "HEAD", "OPTIONS"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "S3-${aws_s3_bucket.frontend.id}"

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    viewer_protocol_policy = "redirect-to-https"
    min_ttl                = 0
    default_ttl            = 3600   # 1 hour
    max_ttl                = 86400  # 24 hours
    compress               = true
  }

  # SPA routing (redirect 404 to index.html)
  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = {
    Name    = "${var.project_name}-frontend-cdn"
    Project = var.project_name
  }
}

# S3 bucket policy (allow CloudFront to read)
resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudFrontServicePrincipal"
        Effect = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.frontend.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.frontend.arn
          }
        }
      }
    ]
  })
}

# Outputs
output "frontend_bucket_name" {
  value       = aws_s3_bucket.frontend.id
  description = "S3 bucket for frontend"
}

output "cloudfront_url" {
  value       = "https://${aws_cloudfront_distribution.frontend.domain_name}"
  description = "CloudFront URL for frontend"
}

output "cloudfront_distribution_id" {
  value       = aws_cloudfront_distribution.frontend.id
  description = "CloudFront distribution ID (for cache invalidation)"
}

# ------------------------------------
# CODEBUILD - FRONTEND DEPLOYMENT
# ------------------------------------

# IAM Role for CodeBuild
resource "aws_iam_role" "codebuild_frontend" {
  name = "${var.project_name}-codebuild-frontend"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "codebuild.amazonaws.com"
        }
      }
    ]
  })
}

# IAM Policy for CodeBuild
resource "aws_iam_role_policy" "codebuild_frontend" {
  role = aws_iam_role.codebuild_frontend.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/aws/codebuild/${var.project_name}-frontend:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:DeleteObject"
        ]
        Resource = [
          "${aws_s3_bucket.frontend.arn}",
          "${aws_s3_bucket.frontend.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "cloudfront:CreateInvalidation"
        ]
        Resource = aws_cloudfront_distribution.frontend.arn
      },
      {
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:DescribeLoadBalancers",
          "elasticloadbalancing:DescribeTargetHealth"
        ]
        Resource = "*"
      }
    ]
  })
}

# CodeBuild Project
resource "aws_codebuild_project" "frontend" {
  name          = "${var.project_name}-frontend"
  service_role  = aws_iam_role.codebuild_frontend.arn
  build_timeout = 15

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/standard:7.0"
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"

    environment_variable {
      name  = "FRONTEND_BUCKET"
      value = aws_s3_bucket.frontend.id
    }

    environment_variable {
      name  = "CLOUDFRONT_DISTRIBUTION_ID"
      value = aws_cloudfront_distribution.frontend.id
    }

    environment_variable {
      name  = "ALB_DNS_NAME"
      value = aws_cloudfront_distribution.api_proxy.domain_name
    }

    environment_variable {
      name  = "AWS_REGION"
      value = var.aws_region
    }
  }

  source {
    type            = "GITHUB"
    location        = var.frontend_github_repo  # e.g., "https://github.com/user/frontend-repo.git"
    git_clone_depth = 1
    buildspec       = "buildspec.yml"
  }

  logs_config {
    cloudwatch_logs {
      status      = "ENABLED"
      group_name  = "/aws/codebuild/${var.project_name}-frontend"
    }
  }

  tags = {
    Name    = "${var.project_name}-frontend-build"
    Project = var.project_name
  }
}

# ------------------------------------
# CLOUDFRONT API PROXY (HTTPS WRAPPER)
# ------------------------------------

resource "aws_cloudfront_distribution" "api_proxy" {
  enabled = true
  comment = "API proxy for HTTPS termination"

  origin {
    domain_name = aws_lb.main.dns_name
    origin_id   = "ALB-Backend"

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "http-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_keepalive_timeout = 60
      origin_read_timeout      = 60
    }

    # Add origin shield to reduce load (optional)
    origin_shield {
      enabled              = false
      origin_shield_region = var.aws_region
    }
  }

  default_cache_behavior {
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "ALB-Backend"
    viewer_protocol_policy = "redirect-to-https"

    # Use managed cache policy (no caching for API)
    cache_policy_id            = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"  # CachingDisabled
    origin_request_policy_id   = "216adef6-5c7f-47e4-b989-5492eafa07d3"  # AllViewer

    compress = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = {
    Name    = "${var.project_name}-api-proxy"
    Project = var.project_name
  }
}

# Output
output "api_proxy_url" {
  value       = "https://${aws_cloudfront_distribution.api_proxy.domain_name}"
  description = "CloudFront HTTPS API endpoint"
}