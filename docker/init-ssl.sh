#!/bin/bash

# Initialize SSL certificates with Let's Encrypt
# Run this script once during initial server setup

set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '#' | xargs)
fi

if [ -z "$DOMAIN" ]; then
    echo "Error: DOMAIN not set in .env"
    exit 1
fi

echo "Initializing SSL for domain: $DOMAIN"

# Create directories
mkdir -p certbot/conf certbot/www

# Stop nginx if running
docker-compose stop nginx 2>/dev/null || true

# Get initial certificate
docker-compose run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email admin@$DOMAIN \
    --agree-tos \
    --no-eff-email \
    -d $DOMAIN

# Start all services
docker-compose up -d

echo "SSL initialized successfully!"
echo "n8n is available at: https://$DOMAIN"
