"""
OpenTelemetry tracing setup for FluxKart.

Exports traces to Jaeger via OTLP gRPC.
Endpoint configured via JAEGER_OTLP_ENDPOINT env var (default: http://jaeger:4317).

Auto-instrumented:
  - FastAPI     — all HTTP requests, route params, status codes
  - asyncpg     — all PostgreSQL queries with SQL text
  - Redis       — all Redis commands (GET, SET, EVAL, etc.)

Manual spans:
  - RabbitMQ publish  (in reservation_service.py)
  - RabbitMQ consume  (in order_consumer.py)
"""

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor

from app.config import settings

_tracer: trace.Tracer | None = None


def setup_tracing(app=None, service_name: str = "fluxkart-api") -> None:
    """
    Initializes OpenTelemetry tracing.

    Call once at startup — before any requests are handled.

    Args:
        app:          FastAPI app instance (pass for HTTP auto-instrumentation).
                      None for consumer process (no HTTP).
        service_name: Identifies the service in Jaeger UI.
    """
    global _tracer

    resource = Resource.create({
        "service.name":           service_name,
        "service.version":        "0.1.0",
        "deployment.environment": settings.app_env,
    })

    exporter = OTLPSpanExporter(
        endpoint=settings.jaeger_otlp_endpoint,
        insecure=True,
    )

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(
            exporter,
            max_queue_size=2048,
            max_export_batch_size=512,
            export_timeout_millis=5000,
        )
    )
    trace.set_tracer_provider(provider)

    AsyncPGInstrumentor().instrument()
    RedisInstrumentor().instrument()

    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls="health,metrics",
        )

    _tracer = trace.get_tracer(service_name)


def get_tracer() -> trace.Tracer:
    global _tracer
    if _tracer is None:
        return trace.get_tracer("fluxkart")
    return _tracer