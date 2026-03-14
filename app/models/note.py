"""
Note model — stores raw captured content before it becomes a structured article.

Fields:
  - user_id:    WhatsApp sender ID (e.g. "447700900000@c.us")
  - media_type: "text" | "audio" | "image" | "url"
  - content:    Extracted/transcribed text
  - embedding:  1536-dim vector for semantic search (sentence-transformers)
  - topic:      Auto-detected topic label (set by orchestrator agent)
  - source_url: Original URL (if media_type == "url")
  - tags:       List of keyword tags (set by orchestrator agent)
"""
import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    DateTime,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

EMBEDDING_DIM = 384


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)  # text/audio/image/url
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )
    topic: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Note id={self.id} user={self.user_id} type={self.media_type}>"
