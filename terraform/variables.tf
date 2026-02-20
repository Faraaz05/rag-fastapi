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