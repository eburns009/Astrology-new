# ---------------------------------------
# Base image
# ---------------------------------------
FROM python:3.11-slim

# Avoid prompts during installs and keep Python lean
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps needed to build pyswisseph (C extension) + cleanups
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      tzdata \
 && rm -rf /var/lib/apt/lists/*

# Set workdir
WORKDIR /app

# Copy requirement spec first to leverage Docker layer caching
COPY requirements.txt /app/

# Install Python deps (no cache = smaller image)
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY main.py /app/main.py

# Create a non-root user and take ownership
RUN useradd -m appuser \
 && chown -R appuser:appuser /app
USER appuser

# Expose the app port
EXPOSE 8000

# Start the server (Gunicorn)
# Bind to all interfaces and the expected Render port
CMD ["gunicorn", "main:app", "-b", "0.0.0.0:8000"]
