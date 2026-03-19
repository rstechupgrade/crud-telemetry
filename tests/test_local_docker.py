#!/usr/bin/env python3
"""
Test the application locally using Docker Compose.
Starts CockroachDB and the app, runs tests, then cleans up.
"""
import subprocess
import time
import requests
import sys
import os

# Configuration
APP_PORT = 5000
CRDB_PORT = 26257
NETWORK_NAME = "crud-telemetry-test"
CRDB_CONTAINER = "test-cockroachdb"
APP_CONTAINER = "test-wmclientapp"

def run_cmd(cmd, check=True, capture=False):
    """Run a shell command."""
    print(f"  > {cmd}")
    if capture:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip()
    else:
        subprocess.run(cmd, shell=True, check=check)

def cleanup():
    """Clean up Docker containers and network."""
    print("\n=== Cleaning up ===")
    run_cmd(f"docker rm -f {APP_CONTAINER} 2>/dev/null || true", check=False)
    run_cmd(f"docker rm -f {CRDB_CONTAINER} 2>/dev/null || true", check=False)
    run_cmd(f"docker network rm {NETWORK_NAME} 2>/dev/null || true", check=False)

def setup():
    """Set up Docker network and containers."""
    print("\n=== Setting up test environment ===")
    
    # Create network
    run_cmd(f"docker network create {NETWORK_NAME} 2>/dev/null || true", check=False)
    
    # Start CockroachDB
    print("\nStarting CockroachDB...")
    run_cmd(f"""docker run -d --name {CRDB_CONTAINER} \
        --network {NETWORK_NAME} \
        -p {CRDB_PORT}:26257 \
        cockroachdb/cockroach:v23.2.0 \
        start-single-node --insecure""")
    
    # Wait for CockroachDB
    print("Waiting for CockroachDB to be ready...")
    for i in range(30):
        try:
            result = subprocess.run(
                f"docker exec {CRDB_CONTAINER} /cockroach/cockroach sql --insecure -e 'SELECT 1'",
                shell=True, capture_output=True
            )
            if result.returncode == 0:
                print("  CockroachDB is ready!")
                break
        except:
            pass
        time.sleep(1)
    else:
        print("ERROR: CockroachDB failed to start")
        return False
    
    # Initialize database
    print("\nInitializing database...")
    init_sql = """
    CREATE DATABASE IF NOT EXISTS onboarding_db;
    CREATE USER IF NOT EXISTS roach;
    GRANT ALL ON DATABASE onboarding_db TO roach;
    USE onboarding_db;
    CREATE TABLE IF NOT EXISTS client_onboarding (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        first_name STRING,
        last_name STRING,
        date_of_birth STRING,
        ssn_tax_id STRING,
        citizenship STRING,
        marital_status STRING,
        address_street STRING,
        address_city STRING,
        address_state STRING,
        address_zip STRING,
        phone_number STRING,
        email_address STRING UNIQUE,
        occupation STRING,
        employer_name STRING,
        annual_income DECIMAL,
        investment_horizon STRING,
        risk_tolerance STRING,
        primary_investment_goal STRING,
        account_type STRING,
        preferred_communication STRING,
        application_status STRING DEFAULT 'Pending Review',
        created_at TIMESTAMP DEFAULT now(),
        updated_at TIMESTAMP DEFAULT now()
    );
    GRANT ALL ON TABLE client_onboarding TO roach;
    """
    run_cmd(f"docker exec {CRDB_CONTAINER} /cockroach/cockroach sql --insecure -e \"{init_sql}\"")
    
    # Build app image
    print("\nBuilding application image...")
    app_dir = os.path.join(os.path.dirname(__file__), "..", "app")
    run_cmd(f"docker build -t wmclientapp-test {app_dir}")
    
    # Start app
    print("\nStarting application...")
    run_cmd(f"""docker run -d --name {APP_CONTAINER} \
        --network {NETWORK_NAME} \
        -p {APP_PORT}:5000 \
        -e DB_HOST={CRDB_CONTAINER} \
        -e DB_PORT=26257 \
        -e DB_USER=roach \
        -e DB_NAME=onboarding_db \
        -e OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
        wmclientapp-test""")
    
    # Wait for app
    print("Waiting for application to be ready...")
    for i in range(30):
        try:
            resp = requests.get(f"http://localhost:{APP_PORT}/healthz", timeout=2)
            if resp.status_code == 200:
                print("  Application is ready!")
                return True
        except:
            pass
        time.sleep(1)
    
    print("ERROR: Application failed to start")
    return False

def run_tests():
    """Run CRUD tests against the local app."""
    base_url = f"http://localhost:{APP_PORT}"
    
    print("\n" + "=" * 60)
    print("  Running CRUD Tests")
    print("=" * 60)
    
    # Test 1: Health check
    print("\n[1] Health Check")
    resp = requests.get(f"{base_url}/healthz")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    print(f"  ✓ Status: {resp.json()}")
    
    # Test 2: Create
    print("\n[2] CREATE - POST /onboarding")
    test_email = f"test.local.{int(time.time())}@example.com"
    data = {
        "first_name": "Local",
        "last_name": "Test",
        "email_address": test_email,
        "occupation": "Tester"
    }
    resp = requests.post(f"{base_url}/onboarding", json=data)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"
    result = resp.json()
    client_id = result["client_id"]
    print(f"  ✓ Created: {client_id}")
    
    # Test 3: Read
    print("\n[3] READ - GET /onboarding/<id>")
    resp = requests.get(f"{base_url}/onboarding/{client_id}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    result = resp.json()
    assert result["first_name"] == "Local"
    print(f"  ✓ Found: {result['first_name']} {result['last_name']}")
    
    # Test 4: Update
    print("\n[4] UPDATE - PUT /onboarding/<id>")
    update_data = {"occupation": "Senior Tester", "application_status": "Approved"}
    resp = requests.put(f"{base_url}/onboarding/{client_id}", json=update_data)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    print(f"  ✓ Updated: {resp.json()}")
    
    # Test 5: List
    print("\n[5] LIST - GET /onboarding/list")
    resp = requests.get(f"{base_url}/onboarding/list?limit=5")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    result = resp.json()
    print(f"  ✓ Listed: {result['count']} records")
    
    # Test 6: Delete
    print("\n[6] DELETE - DELETE /onboarding/<id>")
    resp = requests.delete(f"{base_url}/onboarding/{client_id}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    print(f"  ✓ Deleted: {resp.json()}")
    
    # Test 7: Verify deletion
    print("\n[7] Verify deletion")
    resp = requests.get(f"{base_url}/onboarding/{client_id}")
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
    print(f"  ✓ Confirmed not found")
    
    print("\n" + "=" * 60)
    print("  All tests passed!")
    print("=" * 60)
    return True

def main():
    try:
        cleanup()
        if not setup():
            cleanup()
            sys.exit(1)
        
        success = run_tests()
        cleanup()
        sys.exit(0 if success else 1)
        
    except Exception as e:
        print(f"\nERROR: {e}")
        cleanup()
        sys.exit(1)

if __name__ == "__main__":
    main()
