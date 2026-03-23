"""
Telegram ARQ task definitions.

The logic mirrors app.queue.tasks but enforces Telegram-specific owner IDs and
uses the Telegram gateway's /send endpoint for replies.
"""
import base64
import json
import tempfile
from pathlib import Path

import httpx
import structlog
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
from sqlalchemy import text

from app.agent.sdk_runner import run_message_with_agent_sdk
from app.database import get_db
from app.models.note import Note

log = structlog.get_logger(__name__)


async def _count_recent_notes(user_id: str, media_type: str) -> int:
    async with get_db() as session:
        result = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM notes
                WHERE user_id = :user_id
                  AND media_type = :media_type
                  AND created_at >= now() - interval '10 minutes'
                """
            ),
            {"user_id": user_id, "media_type": media_type},
        )
        return int(result.scalar_one())


async def _analyze_image_for_fallback(payload: dict, settings: "Settings") -> tuple[str, str, list[str]]:
    media_data = payload.get("media_data")
    if not media_data:
        return (payload.get("body") or "[Image received via Telegram DM]", "Image", ["image", "fallback-save"])

    mimetype = payload.get("media_mimetype", "image/jpeg")
    ext = mimetype.split("/")[-1] if "/" in mimetype else "jpg"
    if ext == "jpeg":
        ext = "jpg"

    system_prompt = (
        "Analyze the provided image and return JSON with keys: "
        "description (string), visible_text (string), topic (string), tags (array of short strings). "
        "Return JSON only."
    )

    with tempfile.TemporaryDirectory(prefix="pkb-image-fallback-") as temp_dir:
        image_path = Path(temp_dir) / f"image.{ext}"
        image_path.write_bytes(base64.b64decode(media_data))

        prompt = (
            f"Analyze image at path: {image_path}\n"
            "Use Read tool first. Return JSON only."
        )

        options = ClaudeAgentOptions(
            model=settings.claude_fast_model,
            allowed_tools=["Read"],
            permission_mode="bypassPermissions",
            setting_sources=["project"],
            max_turns=3,
            cwd=str(Path(__file__).resolve().parents[2]),
            system_prompt={"type": "preset", "preset": "claude_code", "append": system_prompt},
        )

        raw_result = ""
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage) and message.result:
                raw_result = message.result.strip()

    description = ""
    visible_text = ""
    topic = "Image"
    tags: list[str] = ["image", "fallback-save"]
    if raw_result:
        try:
            parsed = json.loads(raw_result)
            description = (parsed.get("description") or "").strip()
            visible_text = (parsed.get("visible_text") or "").strip()
            topic = (parsed.get("topic") or "Image").strip() or "Image"
            parsed_tags = parsed.get("tags") or []
            if isinstance(parsed_tags, list):
                tags = [str(tag).strip() for tag in parsed_tags if str(tag).strip()]
                tags = list(dict.fromkeys(tags + ["image", "fallback-save"]))[:6]
        except json.JSONDecodeError:
            description = raw_result[:4000]

    body = (payload.get("body") or "").strip()
    content_parts = []
    if description:
        content_parts.append(description)
    if visible_text:
        content_parts.append(f"Visible text:\n{visible_text}")
    if body:
        content_parts.append(f"User context:\n{body}")
    content = "\n\n".join(content_parts).strip() or "[Image received via Telegram DM]"

    return content, topic, tags


async def _save_image_fallback_note(payload: dict, settings: "Settings") -> None:
    content, topic, tags = await _analyze_image_for_fallback(payload, settings)

    async with get_db() as session:
        note = Note(
            user_id=payload["from_"],
            media_type="image",
            content=content,
            embedding=None,
            topic=topic,
            source_url=None,
            tags=tags,
        )
        session.add(note)
        await session.flush()
        await session.refresh(note)

    log.info(
        "telegram_fallback_image_note_saved",
        note_id=note.id,
        from_=payload["from_"],
        message_id=payload.get("message_id"),
        topic=topic,
    )


async def process_telegram_message(ctx: dict, payload: dict) -> None:
    """Process one inbound Telegram message end-to-end."""

    settings: "Settings" = ctx["settings"]
    http_client: httpx.AsyncClient = ctx["http_client"]

    from_ = str(payload["from_"])  # Telegram IDs are numeric but we store strings
    reply_to = payload.get("reply_to") or from_
    msg_type = payload["type"]
    owner_id = str(settings.my_telegram_id or "").strip()

    if not owner_id:
        log.error("telegram_task_blocked_missing_owner_id")
        return

    if from_ != owner_id:
        log.warning("telegram_task_ignored_non_owner", from_=from_, owner_id=owner_id)
        return

    log.info("telegram_task_started", from_=from_, type=msg_type)

    notes_before = None
    if msg_type == "image":
        notes_before = await _count_recent_notes(from_, "image")

    try:
        reply = await run_message_with_agent_sdk(payload, settings)
    except Exception as exc:  # pragma: no cover — defensive logging only
        log.exception("telegram_task_orchestration_failed", from_=from_, error=str(exc))
        reply = (
            "❌ Sorry, something went wrong while processing your Telegram message. "
            "Please try again in a moment."
        )

    if msg_type == "image":
        try:
            notes_after = await _count_recent_notes(from_, "image")
            if notes_before is not None and notes_after <= notes_before:
                await _save_image_fallback_note(payload, settings)
        except Exception as exc:  # pragma: no cover — fallback best effort
            log.exception(
                "telegram_fallback_image_note_save_failed",
                from_=from_,
                error=str(exc),
                message_id=payload.get("message_id"),
            )

    await _send_reply(http_client, settings.telegram_gateway_url, reply_to, reply)
    log.info("telegram_task_completed", from_=from_)


async def _send_reply(
    client: httpx.AsyncClient,
    gateway_url: str,
    to: str,
    message: str,
) -> None:
    try:
        resp = await client.post(
            f"{gateway_url}/send",
            json={"to": to, "message": message},
            timeout=15.0,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:  # pragma: no cover — network failure logging
        log.error("telegram_send_reply_failed", to=to, error=str(exc))
