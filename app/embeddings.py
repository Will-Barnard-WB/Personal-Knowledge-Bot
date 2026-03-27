"""
Shared semantic embedding module.

Uses sentence-transformers (all-MiniLM-L6-v2) for 384-dim embeddings.
Model is downloaded once (~80 MB) and cached in ~/.cache/huggingface/.

This module is the single source of truth for embeddings — imported by:
  - app/agent/subagents/synthesis_agent.py  (article storage)
  - .claude/skills/capture-note/scripts/capture_note.py  (note storage)
  - .claude/skills/search-kb/scripts/search_kb.py  (query search)
"""
from __future__ import annotations

import asyncio
from functools import lru_cache

import structlog

log = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def _load_model():
    """Load the embedding model once and cache it for the process lifetime."""
    from sentence_transformers import SentenceTransformer  # type: ignore
    log.info("embedding_model_loading", model="all-MiniLM-L6-v2")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    log.info("embedding_model_ready", dim=384)
    return model


async def embed_text(text: str) -> list[float]:
    """
    Encode text into a 384-dim normalised vector using all-MiniLM-L6-v2.

    normalize_embeddings=True returns unit vectors, making cosine similarity
    equivalent to dot product — compatible with pgvector's cosine_distance.
    """
    def _encode(t: str) -> list[float]:
        model = _load_model()
        vec = model.encode(t[:8192], normalize_embeddings=True)
        return vec.tolist()

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _encode, text)
