# AWS Batch GPU Worker Dockerfile
FROM nvidia/cuda:12.1.0-base-ubuntu22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    python3-venv \
    libreoffice-writer-nogui \
    libreoffice-java-common \
    poppler-utils \
    tesseract-ocr \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3 as default
RUN ln -s /usr/bin/python3 /usr/bin/python

# Create app directory
WORKDIR /app

RUN pip install --no-cache-dir --timeout=10000 \
    onnxruntime-gpu==1.19.2 \
    torch==2.5.1 \
    torchvision==0.20.1 \
    --extra-index-url https://download.pytorch.org/whl/cu121

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install missing unstructured dependencies (separate layer for faster rebuilds)
COPY requirements-missing.txt .
RUN pip install --no-cache-dir -r requirements-missing.txt

RUN python3 -m pip uninstall -y pdfminer pdfminer-six

COPY other.txt .
RUN python3 -m pip install --no-cache-dir -r other.txt

COPY warmup.py .
COPY test_complex.pdf .

# Run the warmup to trigger ~1.2GB of model downloads
RUN python3 warmup.py && rm warmup.py test_complex.pdf

# 5. Final Worker Script
COPY aws_gpu_worker.py .

# Running as root as requested to simplify cache access
CMD ["python", "aws_gpu_worker.py"]