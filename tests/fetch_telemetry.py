#!/usr/bin/env python3
"""
Fetch telemetry data from Loki (logs) and Tempo (traces) for a given trace_id.
Also fetches CockroachDB server logs for the same trace.
"""
import subprocess
import json
import argparse
import sys
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import urllib.parse


# Configuration - All in one namespace (self-contained)
NAMESPACE = "crud-telemetry"
LOKI_SERVICE = "loki"
TEMPO_SERVICE = "tempo"


def kubectl_exec_curl(url: str, method: str = "GET") -> str:
    """Execute curl via kubectl exec on an existing pod."""
    cmd = f'kubectl exec -n {NAMESPACE} deploy/cockroachdb -- sh -c "curl -s \'{url}\'"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    return result.stdout.strip()


def fetch_loki_logs(trace_id: str, hours: int = 1) -> List[Dict]:
    """Fetch logs from Loki containing the trace_id."""
    print(f"\n{'='*60}")
    print(f"  Fetching Logs from Loki")
    print(f"{'='*60}")
    
    # Build query
    query = f'{{namespace="crud-telemetry", container="wmclientapp"}} |= "{trace_id}"'
    encoded_query = urllib.parse.quote(query)
    
    end_time = datetime.utcnow()  # noqa: DTZ003
    start_time = end_time - timedelta(hours=hours)
    start_ns = int(start_time.timestamp() * 1e9)
    end_ns = int(end_time.timestamp() * 1e9)
    
    url = f"http://{LOKI_SERVICE}.{NAMESPACE}.svc.cluster.local:3100/loki/api/v1/query_range"
    url += f"?query={encoded_query}&start={start_ns}&end={end_ns}&limit=100"
    
    try:
        response = kubectl_exec_curl(url)
        data = json.loads(response)
        
        logs = []
        if data.get("status") == "success" and data.get("data", {}).get("result"):
            for stream in data["data"]["result"]:
                for ts, line in stream.get("values", []):
                    logs.append({
                        "timestamp": datetime.fromtimestamp(int(ts) / 1e9).isoformat(),
                        "line": line
                    })
        
        if logs:
            print(f"\n  Found {len(logs)} log entries:")
            print("-" * 60)
            for log in sorted(logs, key=lambda x: x["timestamp"]):
                # Truncate long lines
                line = log["line"]
                if len(line) > 120:
                    line = line[:120] + "..."
                print(f"  {log['timestamp']}")
                print(f"    {line}")
                print()
        else:
            print(f"\n  No logs found for trace_id={trace_id}")
        
        return logs
        
    except Exception as e:
        print(f"\n  Error fetching from Loki: {e}")
        return []


def fetch_tempo_trace(trace_id: str) -> Optional[Dict]:
    """Fetch trace from Tempo."""
    print(f"\n{'='*60}")
    print(f"  Fetching Trace from Tempo")
    print(f"{'='*60}")
    
    url = f"http://{TEMPO_SERVICE}.{NAMESPACE}.svc.cluster.local:3200/api/traces/{trace_id}"
    
    try:
        response = kubectl_exec_curl(url)
        
        if not response or response.startswith("error") or "not found" in response.lower():
            print(f"\n  Trace not found in Tempo (may not be flushed yet)")
            return None
        
        data = json.loads(response)
        
        if "batches" in data:
            print(f"\n  Trace found! Spans:")
            print("-" * 60)
            
            for batch in data.get("batches", []):
                resource = batch.get("resource", {})
                service_name = "unknown"
                for attr in resource.get("attributes", []):
                    if attr.get("key") == "service.name":
                        service_name = attr.get("value", {}).get("stringValue", "unknown")
                
                for scope_span in batch.get("scopeSpans", []):
                    for span in scope_span.get("spans", []):
                        span_id = span.get("spanId", "")
                        name = span.get("name", "")
                        start_time = int(span.get("startTimeUnixNano", 0))
                        end_time = int(span.get("endTimeUnixNano", 0))
                        duration_ms = (end_time - start_time) / 1e6
                        
                        print(f"\n  Service: {service_name}")
                        print(f"  Span: {name}")
                        print(f"  Span ID: {span_id}")
                        print(f"  Duration: {duration_ms:.2f}ms")
                        
                        # Print attributes
                        attrs = span.get("attributes", [])
                        if attrs:
                            print(f"  Attributes:")
                            for attr in attrs[:10]:  # Limit to 10
                                key = attr.get("key", "")
                                value = attr.get("value", {})
                                val_str = value.get("stringValue") or value.get("intValue") or value.get("doubleValue") or str(value)
                                print(f"    {key}: {val_str}")
            
            return data
        else:
            print(f"\n  Unexpected response format")
            return None
        
    except json.JSONDecodeError:
        print(f"\n  Trace not found or invalid response")
        return None
    except Exception as e:
        print(f"\n  Error fetching from Tempo: {e}")
        return None


def fetch_cockroachdb_logs(trace_id: str) -> List[str]:
    """Fetch CockroachDB server logs containing the trace_id."""
    print(f"\n{'='*60}")
    print(f"  Fetching CockroachDB Server Logs")
    print(f"{'='*60}")
    
    # Get logs from CockroachDB pod
    cmd = f"kubectl exec -n {NAMESPACE} deploy/cockroachdb -- cat /cockroach/cockroach-data/logs/cockroach-sql-exec.log"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    matching_logs = []
    for line in result.stdout.split('\n'):
        if trace_id in line:
            matching_logs.append(line)
    
    if matching_logs:
        print(f"\n  Found {len(matching_logs)} CockroachDB log entries:")
        print("-" * 60)
        for log in matching_logs:
            # Parse and display
            try:
                data = json.loads(log.split(' =')[1] if ' =' in log else '{}')
                print(f"\n  Operation: {data.get('Tag', 'N/A')}")
                print(f"  Statement: {data.get('Statement', 'N/A')[:100]}...")
                print(f"  User: {data.get('User', 'N/A')}")
                print(f"  App: {data.get('ApplicationName', 'N/A')}")
                print(f"  Rows: {data.get('NumRows', 'N/A')}")
                print(f"  Age: {data.get('Age', 'N/A')}ms")
            except:
                print(f"  {log[:150]}...")
    else:
        print(f"\n  No CockroachDB logs found for trace_id={trace_id}")
    
    return matching_logs


def fetch_app_logs_kubectl(trace_id: str) -> List[str]:
    """Fetch application logs directly via kubectl."""
    print(f"\n{'='*60}")
    print(f"  Fetching Application Logs (kubectl)")
    print(f"{'='*60}")
    
    cmd = f"kubectl logs -n {NAMESPACE} -l app=wmclientapp --tail=200"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    matching_logs = []
    for line in result.stdout.split('\n'):
        if trace_id in line:
            matching_logs.append(line)
    
    if matching_logs:
        print(f"\n  Found {len(matching_logs)} application log entries:")
        print("-" * 60)
        for log in matching_logs:
            print(f"  {log}")
    else:
        print(f"\n  No application logs found for trace_id={trace_id}")
    
    return matching_logs


def main():
    parser = argparse.ArgumentParser(description="Fetch telemetry data for a trace ID")
    parser.add_argument("--trace-id", "-t", required=True, help="Trace ID to search for")
    parser.add_argument("--hours", "-H", type=int, default=1, help="Hours of logs to search (default: 1)")
    parser.add_argument("--skip-loki", action="store_true", help="Skip Loki query")
    parser.add_argument("--skip-tempo", action="store_true", help="Skip Tempo query")
    parser.add_argument("--skip-crdb", action="store_true", help="Skip CockroachDB logs")
    
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"  Telemetry Fetch for Trace ID")
    print(f"{'='*60}")
    print(f"\n  Trace ID: {args.trace_id}")
    print(f"  Time Range: Last {args.hours} hour(s)")
    
    # Fetch from all sources
    if not args.skip_loki:
        fetch_app_logs_kubectl(args.trace_id)
        fetch_loki_logs(args.trace_id, args.hours)
    
    if not args.skip_tempo:
        fetch_tempo_trace(args.trace_id)
    
    if not args.skip_crdb:
        fetch_cockroachdb_logs(args.trace_id)
    
    print(f"\n{'='*60}")
    print(f"  Telemetry Fetch Complete")
    print(f"{'='*60}")
    print(f"\n  To view in Grafana:")
    print(f"    kubectl port-forward svc/grafana 3000:3000 -n {NAMESPACE}")
    print(f"    Open http://localhost:3000 (admin/admin)")
    print(f"    Go to Explore > Loki > Query: {{namespace=\"crud-telemetry\", container=\"wmclientapp\"}} |= \"{args.trace_id}\"")
    print("")


if __name__ == "__main__":
    main()
