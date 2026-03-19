#!/bin/bash
# Configuration variables for CRUD Telemetry deployment
# This is a FULLY SELF-CONTAINED deployment - all components in one namespace

# Azure Container Registry
export ACR_REGISTRY="tipacrregistry2025prefinale.azurecr.io"
export IMAGE_NAME="wmclientapp"
export IMAGE_TAG_DEFAULT="crud-telemetry"
export IMAGE_TAG="${IMAGE_TAG:-$IMAGE_TAG_DEFAULT}"

# Kubernetes - everything in ONE namespace
export NAMESPACE="crud-telemetry"

# App settings
export APP_REPLICAS=2

# Paths
export SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
export APP_DIR="$PROJECT_ROOT/app"
export K8S_DIR="$PROJECT_ROOT/k8s"
