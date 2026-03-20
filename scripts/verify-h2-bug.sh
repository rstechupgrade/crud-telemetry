#!/bin/bash
set -e

echo "=== H2 Bug Verification: updated_at Staleness ==="
echo ""

echo ">>> Creating test record..."
RESULT=$(kubectl exec -n crud-telemetry deploy/cockroachdb -- \
  curl -s -X POST http://wmclientapp:5000/onboarding \
  -H "Content-Type: application/json" \
  -d '{"first_name":"After","last_name":"Bug","email_address":"h2_verify@test.com"}')

echo "$RESULT"
CLIENT_ID=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['client_id'])")
echo "Client ID: $CLIENT_ID"
echo ""

sleep 3

echo ">>> Updating record (setting occupation)..."
kubectl exec -n crud-telemetry deploy/cockroachdb -- \
  curl -s -X PUT "http://wmclientapp:5000/onboarding/$CLIENT_ID" \
  -H "Content-Type: application/json" \
  -d '{"occupation":"Engineer"}'
echo ""
echo ""

echo ">>> Reading record back..."
RECORD=$(kubectl exec -n crud-telemetry deploy/cockroachdb -- \
  curl -s "http://wmclientapp:5000/onboarding/$CLIENT_ID")

echo "$RECORD" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'  created_at = {d[\"created_at\"]}')
print(f'  updated_at = {d[\"updated_at\"]}')
if d['created_at'] == d['updated_at']:
    print('  RESULT: SAME -- BUG (timestamp NOT updating)')
else:
    print('  RESULT: DIFFERENT -- FIXED (timestamp updated)')
"

echo ""
echo ">>> Cleaning up test record..."
kubectl exec -n crud-telemetry deploy/cockroachdb -- \
  curl -s -X DELETE "http://wmclientapp:5000/onboarding/$CLIENT_ID"
echo ""
echo "=== Done ==="
