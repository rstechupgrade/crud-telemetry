#!/bin/bash
set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

echo "=============================================================="
echo "  CRUD Telemetry - Cleanup"
echo "=============================================================="
echo ""

read -p "This will delete ALL resources in namespace '$NAMESPACE' (including observability stack). Continue? (y/N) " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "=== Deleting namespace (this removes everything) ==="
kubectl delete namespace $NAMESPACE --ignore-not-found --wait=true

echo ""
echo "=== Deleting cluster-scoped resources ==="
kubectl delete clusterrole promtail-crud-telemetry --ignore-not-found 2>/dev/null || true
kubectl delete clusterrolebinding promtail-crud-telemetry --ignore-not-found 2>/dev/null || true

echo ""
echo "=== Cleanup complete ==="
echo ""
echo "All resources in namespace '$NAMESPACE' have been deleted."
