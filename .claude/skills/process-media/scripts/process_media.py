#!/usr/bin/env python3
"""Extract useful content from audio, image, or URL message context."""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import tempfile
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Optional

import structlog
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

log = structlog.get_logger(__name__)

_VISION_PROMPT = """Analyse this image and respond with a JSON object containing exactly these keys:
{
  \"description\": \"<1–3 sentence plain English description>\",
  \"visible_text\": \"<any text visible in the image, or empty string>\",
  \"topics\": [\"<topic1>\", \"<topic2>\"],
  \"tags\": [\"<tag1>\", \"<tag2>\", \"<tag3>\"],
  \"category\": \"<one of: screenshot | diagram | photo | document | meme | chart | other>\"
}

Respond with JSON only — no markdown fences, no additional commentary."""


async def scrape_link(url: str) -> dict:
    def _scrape_sync() -> dict:
        import json as json_module
        import trafilatura  # type: ignore

        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return {
                "title": "Unable to fetch",
                "author": None,
                "date": None,
                "site_name": None,
                "text": f"Could not download content from {url}",
                "url": url,
            }

        raw_json = trafilatura.extract(
            downloaded,
            output_format="json",
            include_metadata=True,
            include_comments=False,
            no_fallback=False,
        )

        if raw_json:
            data = json_module.loads(raw_json)
            return {
                "title": data.get("title") or "Untitled",
                "author": data.get("author"),
                "date": data.get("date"),
                "site_name": data.get("sitename"),
                "text": data.get("text") or "",
                "url": data.get("url") or url,
            }

        plain = trafilatura.extract(downloaded)
        return {
            "title": "Untitled",
            "author": None,
            "date": None,
            "site_name": None,
            "text": plain or f"[No content extracted from {url}]",
            "url": url,
        }

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _scrape_sync)
    log.info("scrape_complete", url=url, title=result["title"], chars=len(result["text"]))
    return result


@lru_cache(maxsize=1)
def _load_whisper_model(model_name: str = "base"):
    from faster_whisper import WhisperModel  # type: ignore

    log.info("whisper_model_loading", model=model_name, device="cpu")
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    log.info("whisper_model_ready", model=model_name, device="cpu")
    return model


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str = "voice.ogg",
    language: Optional[str] = None,
    model_name: str = "base",
) -> str:
    def _transcribe_sync() -> str:
        model = _load_whisper_model(model_name)
        suffix = os.path.splitext(filename)[1] or ".ogg"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            segments, _info = model.transcribe(
                tmp_path,
                language=language,
                vad_filter=True,
            )
            return " ".join(segment.text.strip() for segment in segments).strip()
        finally:
            os.unlink(tmp_path)

    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, _transcribe_sync)
    log.info("transcription_complete", chars=len(text))
    return text


async def analyze_image(
    image_data: str,
    mimetype: str,
    focus: Optional[str] = None,
    model: str = "claude-haiku-4-5",
) -> dict:
    prompt = _VISION_PROMPT
    if focus:
        prompt = f"The user wants to know: {focus}\\n\\n" + prompt

    workspace_root = Path(__file__).resolve().parents[4]
    ext = mimetype.split("/")[-1] if "/" in mimetype else "jpg"
    if ext == "jpeg":
        ext = "jpg"

    raw = ""
    temp_dir = workspace_root / ".tmp_media"
    temp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = temp_dir / f"vision_{uuid.uuid4().hex}.{ext}"
    with open(tmp_path, "wb") as tmp:
        tmp.write(base64.b64decode(image_data))

    try:
        full_prompt = (
            f"Analyze the image at this path: {tmp_path}. "
            "Use the Read tool to inspect it first.\\n\\n"
            + prompt
        )

        options = ClaudeAgentOptions(
            model=model,
            allowed_tools=["Read"],
            permission_mode="bypassPermissions",
            setting_sources=["project"],
            cwd=str(workspace_root),
            max_turns=3,
        )

        async for message in query(prompt=full_prompt, options=options):
            if isinstance(message, ResultMessage) and message.result:
                raw = message.result.strip()
    finally:
        if tmp_path.exists():
            os.unlink(tmp_path)

    if not raw:
        raw = '{"description":"Unable to analyze image","visible_text":"","topics":[],"tags":[],"category":"other"}'

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("vision_json_parse_failed", raw=raw[:200])
        result = {
            "description": raw[:500],
            "visible_text": "",
            "topics": [],
            "tags": [],
            "category": "other",
        }

    log.info("vision_analysis_complete", category=result.get("category"))
    return result


def _load_context(path: str) -> dict:
    return json.loads(Path(path).read_text())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--output-file")
    parser.add_argument("--model", default="claude-haiku-4-5")
    parser.add_argument("--whisper-model", default="base")
    args = parser.parse_args()

    ctx = _load_context(args.context)
    message_type = ctx["message_type"]
    base_dir = Path(args.context).resolve().parent
    content_file = Path(args.output_file) if args.output_file else base_dir / "extracted_content.txt"

    if message_type == "audio":
        audio_path = ctx.get("audio_file")
        if not audio_path:
            raise SystemExit("audio_file missing from context")
        extracted = asyncio.run(
            transcribe_audio(
                audio_bytes=Path(audio_path).read_bytes(),
                filename=ctx.get("audio_filename", Path(audio_path).name),
                model_name=args.whisper_model,
            )
        )
        payload = {
            "media_type": "audio",
            "content_file": str(content_file),
            "suggested_topic": None,
            "suggested_tags": [],
            "source_url": None,
        }
    elif message_type == "image":
        image_path = ctx.get("image_file")
        if not image_path:
            raise SystemExit("image_file missing from context")
        image_bytes = Path(image_path).read_bytes()
        result = asyncio.run(
            analyze_image(
                image_data=base64.b64encode(image_bytes).decode("utf-8"),
                mimetype=ctx.get("media_mimetype", "image/jpeg"),
                focus=(ctx.get("body") or "").strip() or None,
                model=args.model,
            )
        )
        visible_text = (result.get("visible_text") or "").strip()
        extracted = (result.get("description") or "").strip()
        if visible_text:
            extracted = f"{extracted}\n\nVisible text:\n{visible_text}".strip()
        payload = {
            "media_type": "image",
            "content_file": str(content_file),
            "suggested_topic": (result.get("topics") or [None])[0],
            "suggested_tags": result.get("tags") or [],
            "source_url": None,
        }
    elif message_type == "url":
        url = ctx.get("url") or ctx.get("body")
        if not url:
            raise SystemExit("url missing from context")
        result = asyncio.run(scrape_link(url))
        title = (result.get("title") or "Untitled").strip()
        extracted = f"{title}\n\n{(result.get('text') or '').strip()}".strip()
        payload = {
            "media_type": "url",
            "content_file": str(content_file),
            "suggested_topic": title,
            "suggested_tags": [],
            "source_url": result.get("url") or url,
        }
    else:
        raise SystemExit(f"Unsupported message_type: {message_type}")

    content_file.write_text(extracted)
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
