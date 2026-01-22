# Tulpar Express Bot - Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install fonts for product card generation (Pillow/PIL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

# Environment
ENV PYTHONUNBUFFERED=1

# For Railway/cloud: use GOOGLE_CREDENTIALS_JSON env var
# For local: mount credentials file and set GOOGLE_CREDENTIALS_PATH

# Run bot
CMD ["python", "-m", "src.main"]
