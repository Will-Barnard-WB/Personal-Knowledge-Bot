"""
/telegram-webhook router — receives inbound messages from the Telegram gateway.

Flow mirrors the WhatsApp webhook but enforces Telegram-specific owner IDs so
that the stacks stay isolated. Messages are enqueued to the ARQ worker and the
HTTP request returns immediately.
"""
from typing import Optional

import structlog
from arq import ArqRedis
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.config import get_settings
from app.rate_limiter import RateLimiter
from app.schemas import WebhookResponse

log = structlog.get_logger(__name__)
router = APIRouter()


def _normalize_telegram_id(value: Optional[str]) -> str:
    if value is None:
        return ""
    normalized = str(value).strip()
    return normalized


async def _get_arq_pool(request: Request) -> ArqRedis:
    return request.app.state.arq_pool


async def _get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


@router.post("/telegram-webhook", response_model=WebhookResponse)
async def telegram_webhook(
    from_: str = Form(..., alias="from"),
    message_id: str = Form(...),
    reply_to: Optional[str] = Form(None),
    type: str = Form(...),
    body: str = Form(""),
    url: Optional[str] = Form(None),
    media_data: Optional[str] = Form(None),
    media_mimetype: Optional[str] = Form(None),
    media_file: Optional[UploadFile] = File(None),
    arq_pool: ArqRedis = Depends(_get_arq_pool),
    rate_limiter: RateLimiter = Depends(_get_rate_limiter),
) -> WebhookResponse:
    """Accept inbound Telegram messages and enqueue them for async processing."""

    settings = get_settings()
    owner_id = _normalize_telegram_id(settings.my_telegram_id)
    from_normalized = _normalize_telegram_id(from_)

    if not owner_id:
        log.error("telegram_webhook_missing_owner_id")
        raise HTTPException(status_code=500, detail="MY_TELEGRAM_ID is not configured")

    if from_normalized != owner_id:
        log.warning("telegram_webhook_ignored_non_owner", from_=from_, owner_id=owner_id)
        return WebhookResponse(ok=False, message="Ignored: bot only accepts DM from the owner")

    log.info("telegram_webhook_received", from_=from_, type=type, message_id=message_id)

    # Rate limit the sender ID
    result = await rate_limiter.check(from_)
    if not result.allowed:
        log.warning("telegram_webhook_rate_limited", from_=from_)
        return WebhookResponse(
            ok=False,
            message=(
                f"⚠️ You've hit the rate limit ({settings.rate_limit_max_requests} "
                f"messages per {settings.rate_limit_window_seconds}s). Please slow down!"
            ),
        )

    audio_bytes: Optional[bytes] = None
    audio_filename: Optional[str] = None
    if media_file is not None:
        audio_bytes = await media_file.read()
        audio_filename = media_file.filename

    job_payload = {
        "from_": from_,
        "reply_to": reply_to,
        "message_id": message_id,
        "type": type,
        "body": body,
        "url": url,
        "media_data": media_data,
        "media_mimetype": media_mimetype,
        "audio_bytes": audio_bytes,
        "audio_filename": audio_filename,
    }

    job = await arq_pool.enqueue_job(
        "process_telegram_message",
        job_payload,
        _job_id=message_id,
    )

    job_id = job.job_id if job else message_id
    log.info("telegram_webhook_enqueued", job_id=job_id, from_=from_, type=type)

    return WebhookResponse(ok=True, job_id=job_id, message="Queued for processing")


# Backwards compatibility alias so the gateway can still call /webhook without
# needing an immediate config change. Hidden from the OpenAPI schema to avoid
# confusion now that /telegram-webhook is the preferred path.
router.add_api_route(
    "/webhook",
    telegram_webhook,
    methods=["POST"],
    include_in_schema=False,
)
