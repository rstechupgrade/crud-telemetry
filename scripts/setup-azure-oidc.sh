#!/bin/bash
set -e

# One-time setup: Create Azure AD App Registration with OIDC federation for GitHub Actions.
# Run this locally with Azure CLI logged in.
#
# Prerequisites:
#   - az cli logged in with Owner/Contributor on the subscription
#   - GitHub repo already created
#
# After running, add these to your GitHub repo:
#   Secrets:  AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID
#   Variables: ACR_REGISTRY, AKS_CLUSTER_NAME, AKS_RESOURCE_GROUP

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

# --- Configuration ---
APP_DISPLAY_NAME="github-crud-telemetry-cicd"
GITHUB_ORG="rstechupgrade"
GITHUB_REPO="crud-telemetry"
AKS_CLUSTER="tipaks2"
AKS_RG="infrastructure"

if [ -z "$GITHUB_ORG" ] || [ -z "$GITHUB_REPO" ]; then
    echo "ERROR: Set GITHUB_ORG and GITHUB_REPO in this script before running."
    exit 1
fi

echo "=============================================================="
echo "  Azure OIDC Setup for GitHub Actions"
echo "=============================================================="

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)
echo "Subscription: $SUBSCRIPTION_ID"
echo "Tenant: $TENANT_ID"

# Step 1: Create App Registration
echo ""
echo "=== Step 1: Creating App Registration ==="
APP_ID=$(az ad app create --display-name "$APP_DISPLAY_NAME" --query appId -o tsv)
echo "App ID: $APP_ID"

# Step 2: Create Service Principal
echo ""
echo "=== Step 2: Creating Service Principal ==="
SP_OBJECT_ID=$(az ad sp create --id "$APP_ID" --query id -o tsv)
echo "SP Object ID: $SP_OBJECT_ID"

# Step 3: Assign roles
echo ""
echo "=== Step 3: Assigning Roles ==="

ACR_RESOURCE_ID=$(az acr show --name "$(echo "$ACR_REGISTRY" | cut -d'.' -f1)" --query id -o tsv)
echo "ACR Resource: $ACR_RESOURCE_ID"

AKS_RESOURCE_ID=$(az aks show --resource-group "$AKS_RG" --name "$AKS_CLUSTER" --query id -o tsv)
echo "AKS Resource: $AKS_RESOURCE_ID"

az role assignment create \
    --assignee "$SP_OBJECT_ID" \
    --role "AcrPush" \
    --scope "$ACR_RESOURCE_ID" \
    --output none
echo "  Assigned AcrPush on ACR"

az role assignment create \
    --assignee "$SP_OBJECT_ID" \
    --role "Azure Kubernetes Service Cluster User Role" \
    --scope "$AKS_RESOURCE_ID" \
    --output none
echo "  Assigned AKS Cluster User Role"

# Step 4: Create OIDC federated credential for GitHub Actions (main branch)
echo ""
echo "=== Step 4: Creating OIDC Federated Credential ==="

az ad app federated-credential create --id "$APP_ID" --parameters '{
    "name": "github-actions-main",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:'"$GITHUB_ORG/$GITHUB_REPO"':ref:refs/heads/main",
    "audiences": ["api://AzureADTokenExchange"]
}'
echo "  Created federated credential for main branch"

# Also allow workflow_dispatch and pull requests
az ad app federated-credential create --id "$APP_ID" --parameters '{
    "name": "github-actions-pr",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:'"$GITHUB_ORG/$GITHUB_REPO"':pull_request",
    "audiences": ["api://AzureADTokenExchange"]
}'
echo "  Created federated credential for pull requests"

# Step 5: Output
echo ""
echo "=============================================================="
echo "  Setup Complete!"
echo "=============================================================="
echo ""
echo "Add these to your GitHub repo settings:"
echo ""
echo "  Secrets (Settings > Secrets and variables > Actions > Secrets):"
echo "    AZURE_CLIENT_ID       = $APP_ID"
echo "    AZURE_TENANT_ID       = $TENANT_ID"
echo "    AZURE_SUBSCRIPTION_ID = $SUBSCRIPTION_ID"
echo ""
echo "  Variables (Settings > Secrets and variables > Actions > Variables):"
echo "    ACR_REGISTRY      = $ACR_REGISTRY"
echo "    AKS_CLUSTER_NAME  = $AKS_CLUSTER"
echo "    AKS_RESOURCE_GROUP = $AKS_RG"
echo ""
echo "Then push to main to trigger the pipeline."
