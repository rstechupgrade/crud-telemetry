# CRUD Telemetry - Complete End-to-End Observability Stack

A complete, production-ready observability setup with distributed tracing from HTTP requests through to database server operations.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              OBSERVABILITY STACK                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │   Grafana    │◄───│    Tempo     │◄───│    Loki      │                  │
│  │  (UI:3000)   │    │  (Traces)    │    │   (Logs)     │                  │
│  └──────────────┘    └──────────────┘    └──────────────┘                  │
│         ▲                   ▲                   ▲                           │
│         │                   │                   │                           │
│         └───────────────────┼───────────────────┘                           │
│                             │                                               │
│  ┌──────────────────────────┴──────────────────────────┐                   │
│  │                   OTEL Collector                     │                   │
│  │              (Receives traces & logs)                │                   │
│  └──────────────────────────┬──────────────────────────┘                   │
│                             │                                               │
│  ┌──────────────────────────┴──────────────────────────┐                   │
│  │                    wmclientapp                       │                   │
│  │         (Flask + OpenTelemetry Instrumentation)      │                   │
│  │                                                      │                   │
│  │  trace_id=abc123 ──► HTTP Span                      │                   │
│  │                      └── DB Span                     │                   │
│  └──────────────────────────┬──────────────────────────┘                   │
│                             │                                               │
│  ┌──────────────────────────┴──────────────────────────┐                   │
│  │                   CockroachDB                        │                   │
│  │           (PostgreSQL-compatible + Tracing)          │                   │
│  │                                                      │                   │
│  │  ApplicationName: "wmclientapp:trace_id=abc123"     │                   │
│  │  Server logs contain trace context!                  │                   │
│  └──────────────────────────────────────────────────────┘                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
crud-telemetry/
├── README.md                    # This file
├── app/                         # Application source code
│   ├── app.py                   # Flask application with OTel
│   ├── requirements.txt         # Python dependencies
│   └── Dockerfile              # Container build file
├── k8s/                        # Kubernetes manifests
│   ├── 00-namespace.yaml       # Namespace creation
│   ├── 01-cockroachdb.yaml     # CockroachDB deployment
│   ├── 02-otel-collector.yaml  # OpenTelemetry Collector
│   ├── 03-app.yaml             # Application deployment
│   └── 04-init-db.yaml         # Database initialization job
├── helm-values/                # Helm chart configurations
│   ├── tempo-values.yaml       # Tempo distributed config
│   ├── loki-values.yaml        # Loki stack config
│   └── grafana-datasources.yaml # Grafana datasource config
├── scripts/                    # Deployment and utility scripts
│   ├── 01-deploy-all.sh        # Full deployment script
│   ├── 02-build-push-app.sh    # Build and push Docker image
│   ├── 03-cleanup.sh           # Cleanup script
│   └── config.sh               # Configuration variables
└── tests/                      # Test scripts
    ├── test_local_docker.py    # Test app locally in Docker
    ├── test_api_crud.py        # Test all CRUD operations
    └── fetch_telemetry.py      # Fetch logs/traces from Loki/Tempo
```

## Quick Start

### 1. Configure
```bash
cd /home/azureuser/factory/crud-telemetry
# Edit scripts/config.sh with your ACR registry name
```

### 2. Deploy Everything
```bash
./scripts/01-deploy-all.sh
```

### 3. Test Locally (Optional)
```bash
python tests/test_local_docker.py
```

### 4. Test in Kubernetes
```bash
python tests/test_api_crud.py
```

### 5. Fetch Telemetry Data
```bash
python tests/fetch_telemetry.py --trace-id <trace_id>
```

## Components

| Component | Version | Purpose |
|-----------|---------|---------|
| CockroachDB | v23.2.0 | PostgreSQL-compatible DB with trace-aware logging |
| Tempo | Latest | Distributed tracing backend |
| Loki | Latest | Log aggregation |
| Grafana | Latest | Visualization |
| OpenTelemetry | 1.21.0 | Instrumentation SDK |

## Trace Correlation

Every API request generates a single `trace_id` that appears in:
1. **Application logs** (Loki) - `trace_id=xxx span_id=yyy`
2. **Application traces** (Tempo) - Full span hierarchy
3. **CockroachDB server logs** - `ApplicationName: "wmclientapp:trace_id=xxx"`

This enables true end-to-end debugging from HTTP request to database operation.
