"""
Pydantic schemas for the /webhook endpoint.
"""
from typing import Literal, Optional
from pydantic import BaseModel, Field


class WebhookPayload(BaseModel):
    """
    Parsed, normalised inbound message from the WhatsApp gateway.
    The gateway POSTs multipart/form-data; FastAPI converts it into this schema.
    """
    # WhatsApp sender ID, e.g. "447700900000@c.us"
    from_: str = Field(..., alias="from")
    message_id: str
    type: Literal["text", "audio", "image", "url"]
    # Text body of the message (or voice-note caption, empty for pure audio)
    body: str = ""
    # For 'url' type — the extracted URL from the text body
    url: Optional[str] = None
    # For 'image' type — base64-encoded image bytes
    media_data: Optional[str] = None
    media_mimetype: Optional[str] = None

    class Config:
        populate_by_name = True


class WebhookResponse(BaseModel):
    ok: bool
    job_id: Optional[str] = None
    message: str = ""
