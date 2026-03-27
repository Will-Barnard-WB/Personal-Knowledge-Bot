"""Claude Agent SDK runner for inbound WhatsApp/Telegram payloads.

This module keeps the runtime thin:
- project behaviour lives primarily in `CLAUDE.md` + `.claude/skills/`
- Python stages message context and invokes the SDK loop
- every inbound message goes through the SDK query loop
"""
from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path

import structlog
from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    ResultMessage,
    AssistantMessage,
    TextBlock,
)

from app.config import Settings

log = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """You are replying inside a personal WhatsApp or Telegram knowledge bot.

Follow the project instructions in CLAUDE.md.
Use the project skills in .claude/skills when they match the request.
Those skills may run bundled Python scripts through Bash.

Return only the user-facing reply text.
"""


def _stage_message_context(payload: dict, temp_dir: str) -> Path:
    base_dir = Path(temp_dir)
    body = (payload.get("body") or "").strip()
    message_type = payload["type"]

    context_payload: dict[str, object] = {
        "user_id": payload["from_"],
        "message_type": message_type,
        "body": body,
        "url": payload.get("url") or None,
    }

    if message_type == "audio" and payload.get("audio_bytes"):
        filename = payload.get("audio_filename", "voice.ogg")
        audio_path = base_dir / filename
        audio_path.write_bytes(payload["audio_bytes"])
        context_payload["audio_file"] = str(audio_path)
        context_payload["audio_filename"] = filename

    if message_type == "image" and payload.get("media_data"):
        mimetype = payload.get("media_mimetype", "image/jpeg")
        ext = mimetype.split("/")[-1] if "/" in mimetype else "jpg"
        if ext == "jpeg":
            ext = "jpg"
        image_path = base_dir / f"image.{ext}"
        image_path.write_bytes(base64.b64decode(payload["media_data"]))
        context_payload["image_file"] = str(image_path)
        context_payload["media_mimetype"] = mimetype

    context_path = base_dir / "message_context.json"
    context_path.write_text(json.dumps(context_payload, indent=2))
    return context_path


def _build_initial_prompt(context_path: Path) -> str:
    context = json.loads(context_path.read_text())

    return "\n".join([
        "Handle this inbound WhatsApp or Telegram message for the Personal Knowledge Bot.",
        f"Context JSON: {context_path}",
        f"User ID: {context['user_id']}",
        f"Message type: {context['message_type']}",
        f"Message body: {(context.get('body') or '(empty)')}",
        "Choose the relevant project skill automatically. Use the bundled Bash-driven workflow from that skill instead of improvising your own process.",
        "If no skill fits perfectly, prefer the closest matching project skill rather than ad-hoc behavior.",
    ])


async def run_message_with_agent_sdk(payload: dict, settings: Settings) -> str:
    """Run one inbound message through Claude Agent SDK using project skills."""

    project_root = Path(__file__).resolve().parents[2]

    options = ClaudeAgentOptions(
        model=settings.claude_fast_model,
        system_prompt={"type": "preset", "preset": "claude_code", "append": _SYSTEM_PROMPT},
        allowed_tools=[
            "Skill",
            "Bash",
        ],
        setting_sources=["project"],
        max_turns=8,
        permission_mode="bypassPermissions",
        cwd=str(project_root),
    )

    final_result: str | None = None
    with tempfile.TemporaryDirectory(prefix="pkb-agent-") as temp_dir:
        context_path = _stage_message_context(payload, temp_dir)
        prompt = _build_initial_prompt(context_path)

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage) and message.result:
                candidate = message.result.strip()
                if candidate:
                    final_result = candidate
            elif isinstance(message, AssistantMessage):
                blocks = [b.text for b in message.content if isinstance(b, TextBlock)]
                if blocks:
                    candidate = "\n".join(blocks).strip()
                    if candidate:
                        final_result = candidate

    if not final_result:
        log.warning("sdk_no_user_facing_result", user_id=payload["from_"])
        return "⚠️ I processed your message but couldn't generate a clear reply. Please try again."

    log.info("sdk_turn_complete", user_id=payload["from_"], response_chars=len(final_result))
    return final_result
