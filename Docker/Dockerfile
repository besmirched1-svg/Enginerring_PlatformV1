# docker/Dockerfile
FROM python:3.11-slim

# Install system dependencies for OpenSCAD
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        openscad \
        ca-certificates \
        build-essential \
        libgl1 \
        libglu1-mesa \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

# Set working directory
WORKDIR /app

# Copy requirements first (better caching)
COPY --chown=appuser:appuser requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY --chown=appuser:appuser . /app

# Environment variable for output directory
ENV OUTPUT_DIR=/app/output

# Expose API port
EXPOSE 8000

# Healthcheck for container orchestration
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -f http://localhost:8000/health || exit 1

# Start the API
CMD ["python", "start_api.py"]
