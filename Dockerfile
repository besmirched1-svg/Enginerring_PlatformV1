FROM python:3.11-slim

# Phase 16.5 Docker parity:
#   - OpenSCAD's STL export works headless; the PNG snapshot does
#     not (it needs an OpenGL context). Install xvfb + the OpenSCAD
#     Mesa drivers so PNG snapshots succeed under Docker.
#   - The renderer automatically wraps the PNG command in xvfb-run
#     when it sees the OPENSCAD_USE_XVFB=1 env var, which is set
#     below. See app/cad/renderer.py for the seam.

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENGINEERING_ENV=production \
    OPENSCAD_USE_XVFB=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    openscad \
    xvfb \
    xauth \
    libgl1-mesa-dri \
    mesa-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Default command runs the unified CLI; docker-compose.yml overrides
# this with uvicorn for the API service.
CMD ["python", "run.py", "start"]
