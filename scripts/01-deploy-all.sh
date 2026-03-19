#!/bin/bash
set -e

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

echo "=============================================================="
echo "  CRUD Telemetry - Full Deployment (Self-Contained)"
echo "=============================================================="
echo ""
echo "Configuration:"
echo "  ACR Registry: $ACR_REGISTRY"
echo "  Namespace: $NAMESPACE"
echo "  Image: $ACR_REGISTRY/$IMAGE_NAME:$IMAGE_TAG"
echo ""

# Step 1: Build and push Docker image
echo "=== Step 1: Building and pushing Docker image ==="
"$SCRIPT_DIR/02-build-push-app.sh"

# Step 2: Create namespace
echo ""
echo "=== Step 2: Creating namespace ==="
kubectl apply -f "$K8S_DIR/00-namespace.yaml"

# Step 3: Deploy CockroachDB
echo ""
echo "=== Step 3: Deploying CockroachDB ==="
kubectl apply -f "$K8S_DIR/01-cockroachdb.yaml"
echo "Waiting for CockroachDB to be ready..."
kubectl wait --for=condition=available deployment/cockroachdb -n $NAMESPACE --timeout=120s

# Step 4: Initialize database
echo ""
echo "=== Step 4: Initializing database ==="
kubectl delete job init-cockroachdb -n $NAMESPACE --ignore-not-found 2>/dev/null || true
kubectl apply -f "$K8S_DIR/04-init-db.yaml"
echo "Waiting for database initialization..."
kubectl wait --for=condition=complete job/init-cockroachdb -n $NAMESPACE --timeout=120s

# Step 5: Deploy Tempo (Tracing)
echo ""
echo "=== Step 5: Deploying Tempo (Distributed Tracing) ==="
kubectl apply -f "$K8S_DIR/05-tempo.yaml"
kubectl wait --for=condition=available deployment/tempo -n $NAMESPACE --timeout=120s
echo "✓ Tempo deployed"

# Step 6: Deploy Loki (Logging)
echo ""
echo "=== Step 6: Deploying Loki (Log Aggregation) ==="
kubectl apply -f "$K8S_DIR/06-loki.yaml"
kubectl wait --for=condition=available deployment/loki -n $NAMESPACE --timeout=120s
echo "✓ Loki deployed"

# Step 7: Deploy Promtail (Log Shipping)
echo ""
echo "=== Step 7: Deploying Promtail (Log Shipper) ==="
kubectl apply -f "$K8S_DIR/07-promtail.yaml"
sleep 5
echo "✓ Promtail deployed"

# Step 8: Deploy Grafana (Visualization)
echo ""
echo "=== Step 8: Deploying Grafana (Visualization) ==="
kubectl apply -f "$K8S_DIR/08-grafana.yaml"
kubectl wait --for=condition=available deployment/grafana -n $NAMESPACE --timeout=120s
echo "✓ Grafana deployed"

# Step 9: Deploy OTEL Collector
echo ""
echo "=== Step 9: Deploying OpenTelemetry Collector ==="
kubectl apply -f "$K8S_DIR/02-otel-collector.yaml"
kubectl wait --for=condition=available deployment/otel-collector -n $NAMESPACE --timeout=60s
echo "✓ OTEL Collector deployed"

# Step 10: Deploy Application
echo ""
echo "=== Step 10: Deploying Application ==="
# Replace image placeholder in manifest
export IMAGE_TAG="${IMAGE_TAG:-$IMAGE_TAG_DEFAULT}"
sed "s|\${ACR_REGISTRY}|$ACR_REGISTRY|g; s|\${IMAGE_TAG}|$IMAGE_TAG|g" "$K8S_DIR/03-app.yaml" | kubectl apply -f -
echo "Waiting for application to be ready..."
kubectl wait --for=condition=available deployment/wmclientapp -n $NAMESPACE --timeout=120s
echo "✓ Application deployed"

# Step 11: Verify deployment
echo ""
echo "=== Step 11: Verifying deployment ==="
echo ""
echo "Pods in $NAMESPACE:"
kubectl get pods -n $NAMESPACE
echo ""
echo "Services in $NAMESPACE:"
kubectl get svc -n $NAMESPACE

echo ""
echo "=============================================================="
echo "  Deployment Complete!"
echo "=============================================================="
echo ""
echo "All components deployed in namespace: $NAMESPACE"
echo ""
echo "To test the API:"
echo "  python3 $PROJECT_ROOT/tests/test_api_crud.py"
echo ""
echo "To fetch telemetry:"
echo "  python3 $PROJECT_ROOT/tests/fetch_telemetry.py --trace-id <trace_id>"
echo ""
echo "To access Grafana:"
echo "  kubectl port-forward svc/grafana 3000:3000 -n $NAMESPACE"
echo "  Open http://localhost:3000 (admin/admin)"
echo ""
