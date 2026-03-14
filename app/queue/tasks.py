"""
ARQ task definitions.

Each function defined here is an async "job" that the ARQ worker picks up
from the Redis queue and executes.  ARQ injects `ctx` (the worker context,
containing shared resources like the DB engine) as the first argument.

Pattern demonstrated:
  - Message queue: inbound webhooks enqueue jobs here, completely decoupling
    HTTP latency from AI processing time
  - Rate-controlled concurrency: WorkerSettings.max_jobs limits parallel LLM calls
  - Reliable delivery: Redis persistence means jobs survive worker restarts
"""
import structlog
import httpx

from app.config import get_settings
from app.agent.sdk_runner import run_message_with_agent_sdk

log = structlog.get_logger(__name__)


async def process_message(ctx: dict, payload: dict) -> None:
    """
    Core ARQ task: process one inbound WhatsApp message end-to-end.

    Steps:
      1. Run the Orchestrator Agent (selects appropriate skill + does AI work)
      2. Send the reply back to the user via the WhatsApp gateway's /send endpoint
      3. If anything fails, send a friendly error message

    The ctx dict is populated by WorkerSettings.on_startup and contains:
      - ctx["settings"]: app Settings
      - ctx["http_client"]: shared httpx.AsyncClient for gateway calls
    """
    from_ = payload["from_"]
    msg_type = payload["type"]
    log.info("task_started", from_=from_, type=msg_type)

    settings: "Settings" = ctx["settings"]
    http_client: httpx.AsyncClient = ctx["http_client"]

    try:
        reply = await run_message_with_agent_sdk(payload, settings)

    except Exception as exc:
        log.exception("task_orchestration_failed", from_=from_, error=str(exc))
        reply = (
            "❌ Sorry, something went wrong while processing your message. "
            "Please try again in a moment."
        )

    # Send reply back through the gateway
    await _send_reply(http_client, settings.gateway_url, from_, reply)
    log.info("task_completed", from_=from_)


async def _send_reply(
    client: httpx.AsyncClient,
    gateway_url: str,
    to: str,
    message: str,
) -> None:
    """
    POST the processed reply to the WhatsApp gateway's /send endpoint.
    The gateway then calls client.sendMessage() on the WhatsApp socket.
    """
    try:
        resp = await client.post(
            f"{gateway_url}/send",
            json={"to": to, "message": message},
            timeout=15.0,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        log.error("send_reply_failed", to=to, error=str(e))
