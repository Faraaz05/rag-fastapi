# AWS Region
variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "ap-south-1"
}

# Project Identification
variable "project_name" {
  description = "Project name for resource tagging"
  type        = string
  default     = "vector-trace-rag"
}

# S3 Storage
variable "s3_bucket_name" {
  description = "S3 bucket name for storage"
  type        = string
  default     = "vector-trace-storage"
}


# VPC Variables

variable "vpc_cidr" {
  default = "10.0.0.0/16"
}

variable "availability_zone" {
  default = "ap-south-1a"
}

variable "public_subnet_cidr" {
  default = "10.0.1.0/24"
}

variable "private_subnet_cidr" {
  default = "10.0.11.0/24"
}

# SQS Queue Configuration
variable "sqs_message_retention_seconds" {
  description = "Time SQS retains messages (4 days default)"
  type        = number
  default     = 345600  # 4 days
}

variable "sqs_visibility_timeout_seconds" {
  description = "Time a message is invisible after being received"
  type        = number
  default     = 3600  # 1 hour (GPU processing can take time)
}

variable "sqs_max_receive_count" {
  description = "Max receives before sending to DLQ"
  type        = number
  default     = 3
}

variable "private_subnet_cidr_2" {
  description = "CIDR block for second private subnet (RDS requirement)"
  type        = string
  default     = "10.0.12.0/24"
}

variable "availability_zone_2" {
  description = "Second availability zone (RDS requirement)"
  type        = string
  default     = "ap-south-1b"
}


# RDS Database Configuration
variable "db_instance_class" {
  description = "RDS instance type"
  type        = string
  default     = "db.t3.micro"  # Free tier eligible, upgrade to db.t3.small for production
}

variable "db_allocated_storage" {
  description = "Allocated storage in GB"
  type        = number
  default     = 20  # Minimum for free tier
}

variable "db_engine_version" {
  description = "PostgreSQL engine version"
  type        = string
  default     = "15"  # Match your docker-compose postgres:15
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "rag_db"  # Matches POSTGRES_DB in docker-compose
}

variable "db_username" {
  description = "Master username for RDS"
  type        = string
  default     = "rag"
  sensitive   = true
}

variable "db_password" {
  description = "Master password for RDS"
  type        = string
  sensitive   = true
  # Set via environment variable: export TF_VAR_db_password="your_secure_password"
}

# EFS Configuration for ChromaDB
variable "efs_performance_mode" {
  description = "EFS performance mode"
  type        = string
  default     = "generalPurpose"  # or "maxIO" for high throughput
}

variable "efs_throughput_mode" {
  description = "EFS throughput mode"
  type        = string
  default     = "bursting"  # or "provisioned" for consistent performance
}


# ECS Task Configuration
variable "fastapi_cpu" {
  description = "CPU units for FastAPI task (1024 = 1 vCPU)"
  type        = number
  default     = 512  # 0.5 vCPU
}

variable "fastapi_memory" {
  description = "Memory for FastAPI task in MB"
  type        = number
  default     = 1024  # 1 GB
}

variable "chromadb_cpu" {
  description = "CPU units for ChromaDB task"
  type        = number
  default     = 512  # 0.5 vCPU
}

variable "chromadb_memory" {
  description = "Memory for ChromaDB task in MB"
  type        = number
  default     = 1024  # 1 GB
}

variable "fastapi_container_port" {
  description = "Port FastAPI listens on"
  type        = number
  default     = 8000
}

variable "chromadb_container_port" {
  description = "Port ChromaDB listens on"
  type        = number
  default     = 8000
}

variable "ecr_fastapi_image" {
  description = "ECR image URI for FastAPI"
  type        = string
  default     = "372885057927.dkr.ecr.ap-south-1.amazonaws.com/rag-fastapi:latest"

}

variable "ecr_chromadb_image" {
  description = "ECR image URI for ChromaDB"
  type        = string
  default     = "chromadb/chroma:latest"  # Official ChromaDB image
}

# ECS Service Configuration
variable "fastapi_desired_count" {
  description = "Number of FastAPI tasks to run"
  type        = number
  default     = 1
}

variable "chromadb_desired_count" {
  description = "Number of ChromaDB tasks to run"
  type        = number
  default     = 1
}

# ECS Cluster Configuration
variable "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  type        = string
  default     = "main-cluster"
}

# ALB Configuration
variable "alb_idle_timeout" {
  description = "ALB idle timeout in seconds"
  type        = number
  default     = 60
}

# variable "health_check_path" {
#   description = "Health check endpoint for FastAPI"
#   type        = string
#   default     = "/health"
# }

# GPU EC2 Instance Configuration
variable "gpu_instance_type" {
  description = "GPU instance type for workers"
  type        = string
  default     = "g4dn.xlarge"
}

variable "gpu_custom_ami" {
  description = "Custom AMI with Docker images pre-loaded"
  type        = string
}

variable "gpu_docker_compose_path" {
  description = "Path to docker-compose.workers.yml on EC2"
  type        = string
  default     = "/home/ubuntu/app/docker-compose.yml"
}

variable "frontend_github_repo" {
  description = "Frontend GitHub repository URL"
  type        = string
}

variable "public_subnet_cidr_2" {
  description = "CIDR block for public subnet 2"
  type        = string
  default     = "10.0.3.0/24"
}