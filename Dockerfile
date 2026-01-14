# Tulpar Express Bot - Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

# Copy credentials (in production, use secrets/volume mount)
COPY docker/google-service-account.json ./credentials/

# Environment
ENV PYTHONUNBUFFERED=1
ENV GOOGLE_CREDENTIALS_PATH=/app/credentials/google-service-account.json

# Run bot
CMD ["python", "-m", "src.main"]
