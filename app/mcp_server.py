"""
Personal Knowledge Bot — MCP server (stdio transport).

Exposes fine-grained multi-modal tools that the Claude agent SDK can call
directly, as an alternative to the coarse Bash-script skill invocations.

Tools exposed:
  - transcribe_audio   Whisper transcription of an audio file
  - analyze_image      Claude vision analysis of an image file
  - extract_url        trafilatura content extraction from a URL
  - capture_note       Save a note to the knowledge base with embedding
  - search_kb          Semantic search over saved notes and articles

Run via:  python -m app.mcp_server
Registered in .claude/settings.json under mcpServers.personal-kb.

Higher-level skills (generate-article, set-reminder) remain as Bash/Skill tools.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import Optional

import structlog
from mcp.server.fastmcp import FastMCP

log = structlog.get_logger(__name__)

# ── Resolve repo root and add skill script directories to sys.path ────────────

_REPO_ROOT = Path(__file__).resolve().parents[1]

for _scripts_dir in (
    str(_REPO_ROOT / ".claude" / "skills" / "process-media" / "scripts"),
    str(_REPO_ROOT / ".claude" / "skills" / "capture-note" / "scripts"),
    str(_REPO_ROOT / ".claude" / "skills" / "search-kb" / "scripts"),
):
    if _scripts_dir not in sys.path:
        sys.path.insert(0, _scripts_dir)

# Import reusable async functions from existing skill scripts.
# These are imported at module level so model loaders (Whisper, sentence-transformers)
# are initialised lazily on first call, not at import time.
from process_media import (  # type: ignore[import]  # noqa: E402
    analyze_image as _analyze_image,
    scrape_link as _scrape_link,
    transcribe_audio as _transcribe_audio,
)
from capture_note import save_note as _save_note  # type: ignore[import]  # noqa: E402
from search_kb import search_knowledge_base as _search_kb  # type: ignore[import]  # noqa: E402

# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP("personal-kb")


@mcp.tool()
async def transcribe_audio(
    audio_path: str,
    filename: Optional[str] = None,
) -> dict:
    """
    Transcribe an audio file to text using Whisper (faster-whisper, CPU, base model).

    Args:
        audio_path: Absolute path to the audio file (ogg, mp3, wav, m4a, etc.)
        filename:   Original filename for format detection; defaults to the basename of audio_path.

    Returns:
        {"transcript": "<transcribed text>"}
    """
    path = Path(audio_path)
    fname = filename or path.name
    audio_bytes = path.read_bytes()

    transcript = await _transcribe_audio(audio_bytes=audio_bytes, filename=fname)
    log.info("mcp_transcribe_audio", path=audio_path, chars=len(transcript))
    return {"transcript": transcript}


@mcp.tool()
async def analyze_image(
    image_path: str,
    focus: Optional[str] = None,
) -> dict:
    """
    Analyse an image with a Claude vision model.

    Args:
        image_path: Absolute path to the image file.
        focus:      Optional user question to guide analysis (e.g. "What brand is shown?").

    Returns:
        {"description": str, "visible_text": str, "topics": list[str], "tags": list[str], "category": str}
        category is one of: screenshot | diagram | photo | document | meme | chart | other
    """
    path = Path(image_path)
    image_bytes = path.read_bytes()
    image_data = base64.b64encode(image_bytes).decode("utf-8")

    ext = path.suffix.lstrip(".").lower()
    mimetype = f"image/{'jpeg' if ext == 'jpg' else ext}"

    result = await _analyze_image(image_data=image_data, mimetype=mimetype, focus=focus)
    log.info("mcp_analyze_image", path=image_path, category=result.get("category"))
    return result


@mcp.tool()
async def extract_url(url: str) -> dict:
    """
    Fetch and extract readable content from a URL using trafilatura.

    Args:
        url: The URL to scrape.

    Returns:
        {"title": str, "text": str, "author": str|null, "date": str|null, "source_url": str}
    """
    result = await _scrape_link(url)
    log.info("mcp_extract_url", url=url, title=result.get("title"))
    return {
        "title": result.get("title") or "Untitled",
        "text": result.get("text") or "",
        "author": result.get("author"),
        "date": result.get("date"),
        "source_url": result.get("url") or url,
    }


@mcp.tool()
async def capture_note(
    user_id: str,
    content: str,
    media_type: str,
    topic: Optional[str] = None,
    tags: Optional[list[str]] = None,
    source_url: Optional[str] = None,
) -> dict:
    """
    Save a note to the knowledge base with a semantic embedding.

    Args:
        user_id:    The user's WhatsApp/Telegram ID.
        content:    The text content to save.
        media_type: One of "text", "audio", "image", "url".
        topic:      Optional topic label (short phrase, e.g. "Machine Learning").
        tags:       Optional keyword tags (2–4 recommended).
        source_url: Original URL if media_type is "url".

    Returns:
        {"note_id": int, "topic": str|null, "tags": list[str]}
    """
    note = await _save_note(
        user_id=user_id,
        content=content,
        media_type=media_type,
        topic=topic,
        tags=tags or [],
        source_url=source_url,
    )
    log.info("mcp_capture_note", note_id=note.id, user_id=user_id, topic=topic)
    return {
        "note_id": note.id,
        "topic": note.topic,
        "tags": note.tags or [],
    }


@mcp.tool()
async def search_kb(
    user_id: str,
    query: str,
    limit: int = 5,
) -> dict:
    """
    Semantic search over saved notes and articles.

    Args:
        user_id: The user's WhatsApp/Telegram ID.
        query:   The search query text.
        limit:   Maximum results per category (notes + articles). Default 5.

    Returns:
        {"notes": [...], "articles": [...], "total": int}
        Each note:    {id, content_preview, topic, tags, score, created_at}
        Each article: {id, title, summary, topic, score, created_at}
    """
    results = await _search_kb(
        user_id=user_id,
        query=query,
        limit=limit,
        search_type="both",
    )
    log.info("mcp_search_kb", user_id=user_id, query=query[:60], total=results["total"])
    return results


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run("stdio")
