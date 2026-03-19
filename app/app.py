"""
CRUD Telemetry Application
Flask application with full OpenTelemetry instrumentation for distributed tracing.
Connects to CockroachDB with trace context propagation.
"""
import os
import json
import logging
import datetime
import time
import uuid
from typing import Dict, Any, Optional
from flask import Flask, jsonify, request, g
import psycopg2
from psycopg2.extras import RealDictCursor
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
from opentelemetry.trace import Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes


# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================
class TraceContextFilter(logging.Filter):
    """Injects trace_id and span_id into all log records."""
    def filter(self, record):
        span = trace.get_current_span()
        span_context = span.get_span_context()
        if span_context.is_valid:
            record.trace_id = format(span_context.trace_id, '032x')
            record.span_id = format(span_context.span_id, '016x')
        else:
            record.trace_id = "0" * 32
            record.span_id = "0" * 16
        return True


LOG_FORMAT = "%(asctime)s [%(levelname)s] trace_id=%(trace_id)s span_id=%(span_id)s %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("wmclientapp")
logger.addFilter(TraceContextFilter())

# Reduce noise from libraries
logging.getLogger("opentelemetry").setLevel(logging.ERROR)
logging.getLogger("werkzeug").setLevel(logging.WARNING)


# ============================================================================
# OPENTELEMETRY CONFIGURATION
# ============================================================================
OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "wmclientapp")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")

resource = Resource.create({
    "service.name": SERVICE_NAME,
    "service.version": SERVICE_VERSION,
    "deployment.environment": ENVIRONMENT
})

trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer(__name__)

try:
    span_exporter = OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)
    trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(span_exporter))
    logger.info(f"OpenTelemetry configured to export to {OTEL_ENDPOINT}")
except Exception as e:
    logger.warning(f"Failed to configure OTLP exporter: {e}")

# Instrument libraries
Psycopg2Instrumentor().instrument(enable_commenter=True, commenter_options={"opentelemetry_values": True})
LoggingInstrumentor().instrument(set_logging_format=True)


# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================
DB_HOST = os.getenv("DB_HOST", "cockroachdb")
DB_PORT = int(os.getenv("DB_PORT", "26257"))
DB_USER = os.getenv("DB_USER", "roach")
DB_NAME = os.getenv("DB_NAME", "onboarding_db")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")


def get_trace_context() -> tuple:
    """Get current trace context for injection into DB connection."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        return format(ctx.trace_id, '032x'), format(ctx.span_id, '016x')
    return "0" * 32, "0" * 16


def get_db_connection():
    """
    Get a database connection with trace context in application_name.
    This allows CockroachDB server logs to be correlated with the trace.
    """
    trace_id, span_id = get_trace_context()
    app_name = f"{SERVICE_NAME}:trace_id={trace_id}:span_id={span_id[:8]}"
    
    conn_params = {
        "host": DB_HOST,
        "port": DB_PORT,
        "user": DB_USER,
        "dbname": DB_NAME,
        "application_name": app_name[:63]
    }
    if DB_PASSWORD:
        conn_params["password"] = DB_PASSWORD
    
    return psycopg2.connect(**conn_params)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
MAX_BODY_LOG_SIZE = 4096
SENSITIVE_FIELDS = {'password', 'ssn', 'ssn_tax_id', 'secret', 'token', 'api_key'}

ALLOWED_UPDATE_FIELDS = {
    'first_name', 'last_name', 'date_of_birth', 'ssn_tax_id', 'citizenship',
    'marital_status', 'address_street', 'address_city', 'address_state', 'address_zip',
    'phone_number', 'email_address', 'occupation', 'employer_name', 'annual_income',
    'investment_horizon', 'risk_tolerance', 'primary_investment_goal',
    'account_type', 'preferred_communication', 'application_status'
}


def sanitize_dict(d: dict) -> dict:
    """Mask sensitive fields in dictionaries."""
    if not isinstance(d, dict):
        return d
    return {k: ('***' if any(s in k.lower() for s in SENSITIVE_FIELDS) else v) 
            for k, v in d.items()}


def truncate(s: str, max_len: int = MAX_BODY_LOG_SIZE) -> str:
    """Truncate long strings for logging."""
    return s[:max_len] + "..." if len(s) > max_len else s


def serialize_row(row: dict) -> dict:
    """Convert database row to JSON-serializable format."""
    result = {}
    for k, v in row.items():
        if isinstance(v, (uuid.UUID, datetime.datetime, datetime.date)):
            result[k] = str(v)
        elif isinstance(v, datetime.timedelta):
            result[k] = v.total_seconds()
        else:
            result[k] = v
    return result


# ============================================================================
# FLASK APPLICATION
# ============================================================================
app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)


@app.errorhandler(Exception)
def handle_exception(e):
    """Global exception handler with trace recording."""
    span = trace.get_current_span()
    span.record_exception(e)
    span.set_status(Status(StatusCode.ERROR, str(e)))
    logger.error(f"Unhandled exception: {type(e).__name__}: {e}")
    return jsonify({"error": str(e), "type": type(e).__name__}), 500


@app.before_request
def before_request():
    """Capture request start time and log incoming request."""
    g.start_time = time.perf_counter()
    span = trace.get_current_span()
    span.set_attribute("http.method", request.method)
    span.set_attribute("http.url", request.url)
    span.set_attribute("http.path", request.path)
    span.set_attribute("http.client_ip", request.remote_addr or "unknown")
    
    if request.is_json:
        try:
            body = request.get_json(force=True, silent=True)
            if body:
                span.set_attribute("http.request.body", truncate(json.dumps(sanitize_dict(body))))
        except Exception:
            pass
    
    logger.info(f"Request: {request.method} {request.path}")


@app.after_request
def after_request(response):
    """Log response and record duration."""
    duration_ms = (time.perf_counter() - g.start_time) * 1000 if hasattr(g, 'start_time') else 0
    
    span = trace.get_current_span()
    span.set_attribute("http.status_code", response.status_code)
    span.set_attribute("http.duration_ms", round(duration_ms, 2))
    
    if response.status_code >= 400:
        span.set_status(Status(StatusCode.ERROR, f"HTTP {response.status_code}"))
    
    logger.info(f"Response: {response.status_code} ({duration_ms:.2f}ms)")
    return response


# ============================================================================
# API ROUTES
# ============================================================================
@app.route("/")
def root():
    """Service info endpoint."""
    return jsonify({
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "database": "CockroachDB",
        "status": "running"
    })


@app.route("/healthz")
def health():
    """Health check endpoint with database connectivity test."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return jsonify({"status": "healthy", "database": "connected"})
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({"status": "unhealthy", "error": str(e)}), 503


@app.route("/onboarding", methods=["POST"])
def create_onboarding():
    """Create a new client onboarding record."""
    data = request.get_json(force=True) or {}
    
    required = ["first_name", "last_name", "email_address"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400
    
    with tracer.start_as_current_span("db.insert") as span:
        span.set_attribute(SpanAttributes.DB_SYSTEM, "cockroachdb")
        span.set_attribute(SpanAttributes.DB_NAME, DB_NAME)
        span.set_attribute(SpanAttributes.DB_OPERATION, "INSERT")
        
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            sql = """
                INSERT INTO client_onboarding 
                (first_name, last_name, date_of_birth, ssn_tax_id, citizenship, 
                 marital_status, address_street, address_city, address_state, address_zip,
                 phone_number, email_address, occupation, employer_name, annual_income,
                 investment_horizon, risk_tolerance, primary_investment_goal,
                 account_type, preferred_communication)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """
            params = (
                data.get("first_name"), data.get("last_name"), data.get("date_of_birth"),
                data.get("ssn_tax_id"), data.get("citizenship"), data.get("marital_status"),
                data.get("address_street"), data.get("address_city"),
                data.get("address_state"), data.get("address_zip"),
                data.get("phone_number"), data.get("email_address"), data.get("occupation"),
                data.get("employer_name"), data.get("annual_income"),
                data.get("investment_horizon"), data.get("risk_tolerance"),
                data.get("primary_investment_goal"), data.get("account_type"),
                data.get("preferred_communication")
            )
            
            start = time.perf_counter()
            cur.execute(sql, params)
            result = cur.fetchone()
            conn.commit()
            duration_ms = (time.perf_counter() - start) * 1000
            
            client_id = str(result[0])
            span.set_attribute("db.execution_time_ms", round(duration_ms, 3))
            span.set_attribute("db.client_id", client_id)
            
            cur.close()
            conn.close()
            
            logger.info(f"Created onboarding: {client_id}")
            return jsonify({"message": "onboarding submitted", "client_id": client_id}), 201
            
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            logger.error(f"Insert failed: {e}")
            return jsonify({"error": str(e)}), 500


@app.route("/onboarding/<client_id>", methods=["GET"])
def get_onboarding(client_id):
    """Get a specific client onboarding record."""
    with tracer.start_as_current_span("db.select") as span:
        span.set_attribute(SpanAttributes.DB_SYSTEM, "cockroachdb")
        span.set_attribute(SpanAttributes.DB_NAME, DB_NAME)
        span.set_attribute(SpanAttributes.DB_OPERATION, "SELECT")
        span.set_attribute("client.id", client_id)
        
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            start = time.perf_counter()
            cur.execute("SELECT * FROM client_onboarding WHERE id = %s", (client_id,))
            row = cur.fetchone()
            duration_ms = (time.perf_counter() - start) * 1000
            
            span.set_attribute("db.execution_time_ms", round(duration_ms, 3))
            span.set_attribute("db.found", row is not None)
            
            cur.close()
            conn.close()
            
            if not row:
                return jsonify({"error": "Not found"}), 404
            
            logger.info(f"Fetched onboarding: {client_id}")
            return jsonify(serialize_row(dict(row)))
            
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            logger.error(f"Select failed: {e}")
            return jsonify({"error": str(e)}), 500


@app.route("/onboarding", methods=["GET"])
def get_onboarding_by_email():
    """Get client onboarding by email address."""
    email = request.args.get("email")
    if not email:
        return jsonify({"error": "Email query parameter required"}), 400
    
    with tracer.start_as_current_span("db.select") as span:
        span.set_attribute(SpanAttributes.DB_SYSTEM, "cockroachdb")
        span.set_attribute(SpanAttributes.DB_NAME, DB_NAME)
        span.set_attribute(SpanAttributes.DB_OPERATION, "SELECT")
        span.set_attribute("query.email", email)
        
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            start = time.perf_counter()
            cur.execute("SELECT * FROM client_onboarding WHERE email_address = %s", (email,))
            row = cur.fetchone()
            duration_ms = (time.perf_counter() - start) * 1000
            
            span.set_attribute("db.execution_time_ms", round(duration_ms, 3))
            span.set_attribute("db.found", row is not None)
            
            cur.close()
            conn.close()
            
            if not row:
                return jsonify({"error": "Not found"}), 404
            
            logger.info(f"Fetched by email: {email}")
            return jsonify(serialize_row(dict(row)))
            
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            logger.error(f"Select by email failed: {e}")
            return jsonify({"error": str(e)}), 500


@app.route("/onboarding/<client_id>", methods=["PUT"])
def update_onboarding(client_id):
    """Update an existing client onboarding record."""
    data = request.get_json(force=True) or {}
    if not data:
        return jsonify({"error": "No fields to update"}), 400
    
    # Remove fields that shouldn't be updated
    data.pop('id', None)
    data.pop('created_at', None)
    
    # Validate column names against allowlist to prevent SQL injection
    invalid_fields = set(data.keys()) - ALLOWED_UPDATE_FIELDS
    if invalid_fields:
        return jsonify({"error": f"Invalid fields: {', '.join(invalid_fields)}"}), 400
    
    with tracer.start_as_current_span("db.update") as span:
        span.set_attribute(SpanAttributes.DB_SYSTEM, "cockroachdb")
        span.set_attribute(SpanAttributes.DB_NAME, DB_NAME)
        span.set_attribute(SpanAttributes.DB_OPERATION, "UPDATE")
        span.set_attribute("client.id", client_id)
        span.set_attribute("db.fields_updated", len(data))
        
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            # Build dynamic UPDATE
            fields = [f"{k} = %s" for k in data.keys()]
            fields.append("updated_at = now()")
            values = list(data.values()) + [client_id]
            
            sql = f"UPDATE client_onboarding SET {', '.join(fields)} WHERE id = %s"
            
            start = time.perf_counter()
            cur.execute(sql, values)
            rows_affected = cur.rowcount
            conn.commit()
            duration_ms = (time.perf_counter() - start) * 1000
            
            span.set_attribute("db.execution_time_ms", round(duration_ms, 3))
            span.set_attribute("db.rows_affected", rows_affected)
            
            cur.close()
            conn.close()
            
            if rows_affected == 0:
                return jsonify({"error": "Not found"}), 404
            
            logger.info(f"Updated onboarding: {client_id}")
            return jsonify({"message": "updated", "rows_affected": rows_affected})
            
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            logger.error(f"Update failed: {e}")
            return jsonify({"error": str(e)}), 500


@app.route("/onboarding/<client_id>", methods=["DELETE"])
def delete_onboarding(client_id):
    """Delete a client onboarding record."""
    with tracer.start_as_current_span("db.delete") as span:
        span.set_attribute(SpanAttributes.DB_SYSTEM, "cockroachdb")
        span.set_attribute(SpanAttributes.DB_NAME, DB_NAME)
        span.set_attribute(SpanAttributes.DB_OPERATION, "DELETE")
        span.set_attribute("client.id", client_id)
        
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            start = time.perf_counter()
            cur.execute("DELETE FROM client_onboarding WHERE id = %s", (client_id,))
            rows_affected = cur.rowcount
            conn.commit()
            duration_ms = (time.perf_counter() - start) * 1000
            
            span.set_attribute("db.execution_time_ms", round(duration_ms, 3))
            span.set_attribute("db.rows_affected", rows_affected)
            
            cur.close()
            conn.close()
            
            if rows_affected == 0:
                return jsonify({"error": "Not found"}), 404
            
            logger.info(f"Deleted onboarding: {client_id}")
            return jsonify({"message": "deleted"})
            
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            logger.error(f"Delete failed: {e}")
            return jsonify({"error": str(e)}), 500


@app.route("/onboarding/list", methods=["GET"])
def list_onboardings():
    """List all client onboarding records with pagination."""
    limit = request.args.get("limit", 10, type=int)
    offset = request.args.get("offset", 0, type=int)
    
    with tracer.start_as_current_span("db.select") as span:
        span.set_attribute(SpanAttributes.DB_SYSTEM, "cockroachdb")
        span.set_attribute(SpanAttributes.DB_NAME, DB_NAME)
        span.set_attribute(SpanAttributes.DB_OPERATION, "SELECT")
        span.set_attribute("db.limit", limit)
        span.set_attribute("db.offset", offset)
        
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            start = time.perf_counter()
            cur.execute(
                "SELECT * FROM client_onboarding ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, offset)
            )
            rows = cur.fetchall()
            duration_ms = (time.perf_counter() - start) * 1000
            
            span.set_attribute("db.execution_time_ms", round(duration_ms, 3))
            span.set_attribute("db.results_count", len(rows))
            
            cur.close()
            conn.close()
            
            results = [serialize_row(dict(row)) for row in rows]
            
            logger.info(f"Listed {len(results)} onboardings")
            return jsonify({"count": len(results), "data": results})
            
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            logger.error(f"List failed: {e}")
            return jsonify({"error": str(e)}), 500


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
