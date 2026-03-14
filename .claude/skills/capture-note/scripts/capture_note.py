#!/usr/bin/env python3
"""Save a note from the current WhatsApp message context."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Optional

import structlog

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.database import get_db  # noqa: E402
from app.models.note import Note  # noqa: E402

log = structlog.get_logger(__name__)


async def embed_text(text: str) -> list[float]:
    def _embed_sync(t: str) -> list[float]:
        dim = 384
        values = [0.0] * dim
        tokens = t.lower().split()
        if not tokens:
            return values

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx_a = int.from_bytes(digest[0:2], "big") % dim
            idx_b = int.from_bytes(digest[2:4], "big") % dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            values[idx_a] += sign
            values[idx_b] += 0.5 * sign

        norm = sum(v * v for v in values) ** 0.5
        if norm > 0:
            values = [v / norm for v in values]
        return values

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _embed_sync, text[:8192])


async def save_note(
    user_id: str,
    content: str,
    media_type: str,
    topic: Optional[str] = None,
    tags: Optional[list[str]] = None,
    source_url: Optional[str] = None,
) -> Note:
    embedding = await embed_text(content)

    async with get_db() as session:
        note = Note(
            user_id=user_id,
            media_type=media_type,
            content=content,
            embedding=embedding,
            topic=topic,
            source_url=source_url,
            tags=tags or [],
        )
        session.add(note)
        await session.flush()
        await session.refresh(note)

    log.info(
        "note_saved",
        note_id=note.id,
        user_id=user_id,
        media_type=media_type,
        topic=topic,
        chars=len(content),
    )
    return note


def _load_context(path: str) -> dict:
    return json.loads(Path(path).read_text())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--media-type", default="text")
    parser.add_argument("--topic")
    parser.add_argument("--source-url")
    parser.add_argument("--content")
    parser.add_argument("--content-file")
    parser.add_argument("--tags", nargs="*", default=[])
    args = parser.parse_args()

    ctx = _load_context(args.context)
    content = args.content
    if args.content_file:
        content = Path(args.content_file).read_text()
    if not content:
        content = (ctx.get("body") or "").strip()

    if not content:
        raise SystemExit("No content available to save")

    note = asyncio.run(
        save_note(
            user_id=ctx["user_id"],
            content=content,
            media_type=args.media_type,
            topic=args.topic,
            tags=args.tags,
            source_url=args.source_url or ctx.get("url") or None,
        )
    )

    print(json.dumps({
        "note_id": note.id,
        "topic": note.topic,
        "media_type": note.media_type,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
