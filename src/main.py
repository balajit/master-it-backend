import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

load_dotenv()

from database import init_db
from routers.courses import router as courses_router
from routers.documents import router as documents_router
from routers.learning import router as learning_router
from routers.mapping import router as mapping_router
from routers.triage import router as triage_router
from routers.users import router as users_router
from routers.v1 import router as v1_router
from learning_platform.api.app import (
    get_lp_app,
    start_book_poller,
    start_poller,
    stop_book_poller,
    stop_poller,
)

app = FastAPI(title="Master It API")

# Mount the LP sub-app at /lp so clients can reach LP endpoints through this
# host.  get_lp_app() always returns the same singleton instance, ensuring
# the shared pipeline_cache is never split across two app objects.
app.mount("/lp", get_lp_app())

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)

OTEL_ENDPOINT: str | None = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
if OTEL_ENDPOINT:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource: Resource = Resource(attributes={SERVICE_NAME: "master-it-backend"})
    provider: TracerProvider = TracerProvider(resource=resource)
    processor: BatchSpanProcessor = BatchSpanProcessor(
        OTLPSpanExporter(endpoint=f"{OTEL_ENDPOINT}/v1/traces")
    )
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    logger.info("OpenTelemetry enabled, exporting to %s", OTEL_ENDPOINT)
else:
    logger.info("OpenTelemetry disabled (set OTEL_EXPORTER_OTLP_ENDPOINT to enable)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OPENAPI_PROTECTED: bool = os.getenv("OPENAPI_PROTECTED", "false").lower() == "true"
UPLOAD_PATH: str = os.getenv("UPLOAD_PATH", "uploads")
os.makedirs(UPLOAD_PATH, exist_ok=True)

app.include_router(users_router)
app.include_router(courses_router)
app.include_router(documents_router)
app.include_router(learning_router)
app.include_router(mapping_router)
app.include_router(v1_router)
app.include_router(triage_router)


@app.on_event("startup")
async def startup() -> None:
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized.")
    logger.info("Starting file poller...")
    await start_poller()
    logger.info("File poller started.")
    logger.info("Starting book process poller...")
    await start_book_poller()
    logger.info("Book process poller started.")


@app.on_event("shutdown")
async def shutdown() -> None:
    logger.info("Stopping file poller...")
    await stop_poller()
    logger.info("File poller stopped.")
    logger.info("Stopping book process poller...")
    await stop_book_poller()
    logger.info("Book process poller stopped.")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/spec")
async def openapi_spec(request: Request) -> dict:
    if OPENAPI_PROTECTED:
        auth_header: str | None = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Not authenticated")
        token: str = auth_header.split(" ", 1)[1]
        from auth import decode_token
        from database import get_session

        payload: dict = decode_token(token)
        session: dict | None = await get_session(payload["sid"])
        if not session:
            raise HTTPException(status_code=401, detail="Session expired")

    return get_openapi(
        title=app.title,
        version="0.1.0",
        description="Master It API specification",
        routes=app.routes,
    )
