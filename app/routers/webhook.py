"""
/webhook router — receives inbound messages from the WhatsApp gateway.

Flow:
  1. Parse multipart/form-data into a WebhookPayload
  2. Check rate limit for the sender
  3. Enqueue an ARQ job for async processing
  4. Return 200 immediately (gateway ACK)

The actual processing (transcription, vision, orchestration) happens in
the ARQ worker — completely decoupled from this request/response cycle.
"""
import structlog
from arq import ArqRedis
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Request
from typing import Optional

from app.config import get_settings
from app.rate_limiter import RateLimiter
from app.schemas import WebhookPayload, WebhookResponse

log = structlog.get_logger(__name__)
router = APIRouter()


async def _get_arq_pool(request: Request) -> ArqRedis:
    """Pull the ARQ Redis pool from app state (set during startup)."""
    return request.app.state.arq_pool


async def _get_rate_limiter(request: Request) -> RateLimiter:
    """Pull the rate limiter from app state."""
    return request.app.state.rate_limiter


@router.post("/webhook", response_model=WebhookResponse)
async def webhook(
    # Form fields from the gateway
    from_: str = Form(..., alias="from"),
    message_id: str = Form(...),
    type: str = Form(...),
    body: str = Form(""),
    url: Optional[str] = Form(None),
    media_data: Optional[str] = Form(None),    # base64 image
    media_mimetype: Optional[str] = Form(None),
    # Optional binary media upload (audio files)
    media_file: Optional[UploadFile] = File(None),
    arq_pool: ArqRedis = Depends(_get_arq_pool),
    rate_limiter: RateLimiter = Depends(_get_rate_limiter),
) -> WebhookResponse:
    """
    Entry point for all inbound WhatsApp messages.

    Validates, rate-limits, then enqueues for async processing.
    Returns immediately — processing is fully async.
    """
    log.info("webhook_received", from_=from_, type=type, message_id=message_id)

    # ── Rate limit check ──────────────────────────────────────────────────────
    result = await rate_limiter.check(from_)
    if not result.allowed:
        settings = get_settings()
        log.warning("webhook_rate_limited", from_=from_)
        # Return 200 (not 429) — the gateway will send a friendly reply
        return WebhookResponse(
            ok=False,
            message=(
                f"⚠️ You've hit the rate limit ({settings.rate_limit_max_requests} messages "
                f"per {settings.rate_limit_window_seconds}s). Please slow down!"
            ),
        )

    # ── Read audio file bytes if present ─────────────────────────────────────
    audio_bytes: Optional[bytes] = None
    audio_filename: Optional[str] = None
    if media_file is not None:
        audio_bytes = await media_file.read()
        audio_filename = media_file.filename

    # ── Build serialisable payload for the queue ──────────────────────────────
    job_payload = {
        "from_": from_,
        "message_id": message_id,
        "type": type,
        "body": body,
        "url": url,
        "media_data": media_data,       # base64 image string
        "media_mimetype": media_mimetype,
        "audio_bytes": audio_bytes,     # raw bytes — ARQ / msgpack handles this
        "audio_filename": audio_filename,
    }

    # ── Enqueue ARQ job ───────────────────────────────────────────────────────
    job = await arq_pool.enqueue_job(
        "process_message",
        job_payload,
        _job_id=message_id,  # deduplication — same message won't be queued twice
    )

    job_id = job.job_id if job else message_id
    log.info("webhook_enqueued", job_id=job_id, from_=from_, type=type)

    return WebhookResponse(ok=True, job_id=job_id, message="Queued for processing")
