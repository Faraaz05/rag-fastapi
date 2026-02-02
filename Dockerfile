# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements_clean.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the FastAPI application code and scripts
COPY app/ app/
COPY scripts/ scripts/

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]