#!/usr/bin/env python3
"""
Test all CRUD operations against the Kubernetes-deployed application.
Captures and displays trace IDs for each operation.
"""
import subprocess
import json
import time
import sys
import re
from dataclasses import dataclass
from typing import Optional, List

# Configuration
NAMESPACE = "crud-telemetry"
SERVICE_NAME = "wmclientapp"
SERVICE_PORT = 5000


@dataclass
class TestResult:
    name: str
    success: bool
    trace_id: Optional[str]
    response: dict
    duration_ms: float


def kubectl_exec_curl(method: str, path: str, data: dict = None) -> tuple:
    """Execute a curl command via kubectl and return response + trace_id."""
    url = f"http://{SERVICE_NAME}.{NAMESPACE}.svc.cluster.local:{SERVICE_PORT}{path}"
    
    # Use a unique marker to identify status code
    curl_cmd = f"curl -s -w '|||STATUS:%{{http_code}}|||' -X {method} '{url}'"
    if data:
        curl_cmd += f" -H 'Content-Type: application/json' -d '{json.dumps(data)}'"
    
    pod_name = f"test-curl-{int(time.time())}"
    cmd = f"kubectl run {pod_name} --rm -i --restart=Never --image=curlimages/curl -- {curl_cmd}"
    
    start = time.perf_counter()
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    duration_ms = (time.perf_counter() - start) * 1000
    
    # Get raw output and extract status using marker
    output = result.stdout
    
    # Extract status code using marker
    status_code = 200  # default
    if '|||STATUS:' in output and '|||' in output.split('|||STATUS:')[1]:
        try:
            status_part = output.split('|||STATUS:')[1].split('|||')[0]
            status_code = int(status_part)
        except:
            pass
    
    # Remove status marker and kubectl noise for body
    body = output
    if '|||STATUS:' in body:
        body = body.split('|||STATUS:')[0]
    
    # Clean up kubectl noise
    clean_lines = []
    for line in body.split('\n'):
        line_stripped = line.strip()
        if line_stripped and not any(line_stripped.startswith(p) for p in 
            ('All commands', 'If you', 'warning:', 'pod "', '|||')):
            clean_lines.append(line_stripped)
    
    body = '\n'.join(clean_lines)
    
    try:
        response = json.loads(body) if body else {}
    except:
        response = {"raw": body}
    
    response["_status_code"] = status_code
    
    return response, duration_ms


def get_trace_id_from_logs(search_term: str) -> Optional[str]:
    """Search application logs for a trace_id related to the search term."""
    cmd = f"kubectl logs -n {NAMESPACE} -l app={SERVICE_NAME} --tail=50"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    for line in reversed(result.stdout.split('\n')):
        if search_term in line:
            match = re.search(r'trace_id=([a-f0-9]+)', line)
            if match:
                return match.group(1)
    return None


def run_crud_tests() -> List[TestResult]:
    """Run all CRUD tests and collect results."""
    results = []
    
    print("\n" + "=" * 70)
    print("  CRUD API Tests - Kubernetes Deployment")
    print("=" * 70)
    
    # Test 1: Health Check
    print("\n[1] HEALTH CHECK - GET /healthz")
    resp, duration = kubectl_exec_curl("GET", "/healthz")
    success = resp.get("_status_code") == 200 and resp.get("status") == "healthy"
    print(f"    Status: {'✓ PASS' if success else '✗ FAIL'}")
    print(f"    Response: {resp}")
    print(f"    Duration: {duration:.2f}ms")
    results.append(TestResult("Health Check", success, None, resp, duration))
    
    # Test 2: Create
    print("\n[2] CREATE - POST /onboarding")
    test_email = f"test.k8s.{int(time.time())}@example.com"
    create_data = {
        "first_name": "Kubernetes",
        "last_name": "Test",
        "email_address": test_email,
        "occupation": "DevOps Engineer",
        "citizenship": "US",
        "phone_number": "+1-555-0123"
    }
    resp, duration = kubectl_exec_curl("POST", "/onboarding", create_data)
    success = resp.get("_status_code") == 201 and "client_id" in resp
    client_id = resp.get("client_id", "")
    trace_id = get_trace_id_from_logs(client_id) if client_id else None
    print(f"    Status: {'✓ PASS' if success else '✗ FAIL'}")
    print(f"    Client ID: {client_id}")
    print(f"    Trace ID: {trace_id}")
    print(f"    Duration: {duration:.2f}ms")
    results.append(TestResult("Create", success, trace_id, resp, duration))
    
    if not client_id:
        print("\n    ERROR: Cannot continue without client_id")
        return results
    
    # Test 3: Read by ID
    print(f"\n[3] READ - GET /onboarding/{client_id}")
    resp, duration = kubectl_exec_curl("GET", f"/onboarding/{client_id}")
    success = resp.get("_status_code") == 200 and resp.get("first_name") == "Kubernetes"
    trace_id = get_trace_id_from_logs(f"Fetched onboarding: {client_id}")
    print(f"    Status: {'✓ PASS' if success else '✗ FAIL'}")
    print(f"    Found: {resp.get('first_name', 'N/A')} {resp.get('last_name', 'N/A')}")
    print(f"    Trace ID: {trace_id}")
    print(f"    Duration: {duration:.2f}ms")
    results.append(TestResult("Read by ID", success, trace_id, resp, duration))
    
    # Test 4: Read by Email
    print(f"\n[4] READ BY EMAIL - GET /onboarding?email={test_email}")
    resp, duration = kubectl_exec_curl("GET", f"/onboarding?email={test_email}")
    success = resp.get("_status_code") == 200 and resp.get("email_address") == test_email
    trace_id = get_trace_id_from_logs(f"Fetched by email: {test_email}")
    print(f"    Status: {'✓ PASS' if success else '✗ FAIL'}")
    print(f"    Trace ID: {trace_id}")
    print(f"    Duration: {duration:.2f}ms")
    results.append(TestResult("Read by Email", success, trace_id, resp, duration))
    
    # Test 5: Update
    print(f"\n[5] UPDATE - PUT /onboarding/{client_id}")
    update_data = {
        "occupation": "Senior DevOps Engineer",
        "application_status": "Approved",
        "annual_income": 150000
    }
    resp, duration = kubectl_exec_curl("PUT", f"/onboarding/{client_id}", update_data)
    success = resp.get("_status_code") == 200 and resp.get("rows_affected", 0) > 0
    trace_id = get_trace_id_from_logs(f"Updated onboarding: {client_id}")
    print(f"    Status: {'✓ PASS' if success else '✗ FAIL'}")
    print(f"    Rows affected: {resp.get('rows_affected', 0)}")
    print(f"    Trace ID: {trace_id}")
    print(f"    Duration: {duration:.2f}ms")
    results.append(TestResult("Update", success, trace_id, resp, duration))
    
    # Test 6: List
    print("\n[6] LIST - GET /onboarding/list?limit=5")
    resp, duration = kubectl_exec_curl("GET", "/onboarding/list?limit=5")
    success = resp.get("_status_code") == 200 and "data" in resp
    trace_id = get_trace_id_from_logs("Listed")
    print(f"    Status: {'✓ PASS' if success else '✗ FAIL'}")
    print(f"    Count: {resp.get('count', 0)}")
    print(f"    Trace ID: {trace_id}")
    print(f"    Duration: {duration:.2f}ms")
    results.append(TestResult("List", success, trace_id, resp, duration))
    
    # Test 7: Delete
    print(f"\n[7] DELETE - DELETE /onboarding/{client_id}")
    resp, duration = kubectl_exec_curl("DELETE", f"/onboarding/{client_id}")
    success = resp.get("_status_code") == 200 and resp.get("message") == "deleted"
    trace_id = get_trace_id_from_logs(f"Deleted onboarding: {client_id}")
    print(f"    Status: {'✓ PASS' if success else '✗ FAIL'}")
    print(f"    Trace ID: {trace_id}")
    print(f"    Duration: {duration:.2f}ms")
    results.append(TestResult("Delete", success, trace_id, resp, duration))
    
    # Test 8: Verify Deletion (should return 404)
    print(f"\n[8] VERIFY DELETION - GET /onboarding/{client_id}")
    resp, duration = kubectl_exec_curl("GET", f"/onboarding/{client_id}")
    success = resp.get("_status_code") == 404
    print(f"    Status: {'✓ PASS (404 as expected)' if success else '✗ FAIL'}")
    print(f"    Duration: {duration:.2f}ms")
    results.append(TestResult("Verify Deletion", success, None, resp, duration))
    
    return results


def print_summary(results: List[TestResult]):
    """Print test summary."""
    print("\n" + "=" * 70)
    print("  Test Summary")
    print("=" * 70)
    
    passed = sum(1 for r in results if r.success)
    failed = len(results) - passed
    
    print(f"\n  Total: {len(results)} tests")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    
    if failed > 0:
        print("\n  Failed tests:")
        for r in results:
            if not r.success:
                print(f"    - {r.name}")
    
    # Print trace IDs for debugging
    print("\n  Trace IDs captured:")
    for r in results:
        if r.trace_id:
            print(f"    {r.name}: {r.trace_id}")
    
    print("\n  To fetch telemetry data for a trace:")
    print("    python fetch_telemetry.py --trace-id <trace_id>")
    print("")
    
    return failed == 0


def main():
    try:
        results = run_crud_tests()
        success = print_summary(results)
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
