#!/bin/bash
set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

echo "=== Building Docker image ==="
echo "Image: $ACR_REGISTRY/$IMAGE_NAME:$IMAGE_TAG"
echo ""

cd "$APP_DIR"

# Build
docker build -t "$ACR_REGISTRY/$IMAGE_NAME:$IMAGE_TAG" .

echo ""
echo "=== Logging into ACR ==="
ACR_NAME=$(echo "$ACR_REGISTRY" | cut -d'.' -f1)
az acr login --name "$ACR_NAME"

echo ""
echo "=== Pushing to ACR ==="
docker push "$ACR_REGISTRY/$IMAGE_NAME:$IMAGE_TAG"

echo ""
echo "=== Image pushed successfully ==="
echo "  $ACR_REGISTRY/$IMAGE_NAME:$IMAGE_TAG"
