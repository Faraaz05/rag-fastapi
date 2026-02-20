provider "aws" {
  region = var.aws_region
}

# --------------------
# S3 Config
# --------------------

# S3 BUCKET creation
resource "aws_s3_bucket" "vector_trace_storage" {
  bucket = var.s3_bucket_name

  lifecycle {
    prevent_destroy = true  
  }

  tags = {
    Name    = "${var.project_name}-storage"
    Project = var.project_name
  }
}

# S3 BUCKET creation access policies

resource "aws_s3_bucket_public_access_block" "storage_pab" {
  bucket = aws_s3_bucket.vector_trace_storage.id

  lifecycle {
    prevent_destroy = true 
  }

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
  description = "Allow All outbound https and allow outbound 5432(rds) , 8001 chromadb and ingrress from ALB 8000 "
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
  from_port   = 8001
  ip_protocol = "tcp"
  to_port     = 8001
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

  from_port         = 8001
  to_port           = 8001
  ip_protocol       = "tcp"
  referenced_security_group_id = aws_security_group.fastapi-ecs-sg.id
}

resource "aws_vpc_security_group_ingress_rule" "chromadb-from-gpu-worker" {
  security_group_id = aws_security_group.chromadb-ecs-sg.id

  from_port         = 8001
  to_port           = 8001
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
  from_port   = 8001
  ip_protocol = "tcp"
  to_port     = 8001
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