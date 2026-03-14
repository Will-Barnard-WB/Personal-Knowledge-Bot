/**
 * WhatsApp Gateway — Personal Knowledge Bot
 *
 * Responsibilities:
 *  1. Connect to WhatsApp via whatsapp-web.js (QR scan once, session persisted)
 *  2. On every inbound message: download media, POST payload to Python /webhook
 *  3. Expose POST /send endpoint so the Python worker can reply to the user
 *
 * Architecture note: This service is intentionally thin — all intelligence
 * lives in the Python FastAPI + Claude agent stack.
 */

"use strict";

require("dotenv").config({ path: require("path").resolve(__dirname, "../.env") });

const { Client, LocalAuth, MessageMedia } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");
const express = require("express");
const axios = require("axios");
const FormData = require("form-data");
const fs = require("fs");
const path = require("path");

// ─── Config ────────────────────────────────────────────────────────────────────
const WEBHOOK_URL = process.env.WEBHOOK_URL || "http://localhost:8000/webhook";
const GATEWAY_PORT = parseInt(process.env.GATEWAY_PORT || "3000", 10);
const MEDIA_DIR = path.join(__dirname, "media");
// Bodies of messages the bot is about to send — registered BEFORE the async
// send so message_create always sees them before the event fires.
const BOT_PENDING_BODIES = new Set();

function registerBotReply(body) {
  BOT_PENDING_BODIES.add(body);
  setTimeout(() => BOT_PENDING_BODIES.delete(body), 30_000);
}

if (!fs.existsSync(MEDIA_DIR)) fs.mkdirSync(MEDIA_DIR, { recursive: true });

// ─── WhatsApp Client ────────────────────────────────────────────────────────────
const client = new Client({
  authStrategy: new LocalAuth({ dataPath: ".wwebjs_auth" }),
  puppeteer: {
    headless: true,
    // On Raspberry Pi, use the system Chromium instead of Puppeteer's bundled one.
    // On macOS/Linux with Puppeteer's own Chromium, comment this line out.
    ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
    ],
  },
});

client.on("qr", (qr) => {
  console.log("\n📱 Scan this QR code with your WhatsApp app:\n");
  qrcode.generate(qr, { small: true });
});

client.on("authenticated", () => {
  console.log("✅ WhatsApp authenticated — session saved to .wwebjs_auth/");
});

client.on("ready", () => {
  console.log("🟢 WhatsApp client ready and listening for messages");
});

client.on("auth_failure", (msg) => {
  console.error("❌ WhatsApp authentication failed:", msg);
  process.exit(1);
});

client.on("disconnected", (reason) => {
  console.warn("⚠️  WhatsApp disconnected:", reason);
});

// ─── Message Handler ────────────────────────────────────────────────────────────
client.on("message_create", async (msg) => {
  // Ignore status updates
  if (msg.isStatus) return;

  // Only process messages YOU send to yourself — ignore everyone else.
  if (!msg.fromMe) return;

  // Skip the bot's own auto-replies to prevent loops.
  // registerBotReply() is called BEFORE the async send so the body is
  // already in the set when message_create fires.
  if (BOT_PENDING_BODIES.has(msg.body)) {
    BOT_PENDING_BODIES.delete(msg.body);
    return;
  }

  const from = msg.from; // e.g. "447700900000@c.us"
  console.log(`📩 Message from ${from} | type: ${msg.type}`);

  // Immediately acknowledge — avoids WhatsApp showing "pending" state.
  // Register body BEFORE sending to avoid race with message_create.
  const ACK = "⏳ Got it! Processing...";
  const ERR = "❌ Oops — something went wrong. Please try again.";
  registerBotReply(ACK);
  await msg.reply(ACK);

  try {
    await forwardToWebhook(from, msg);
  } catch (err) {
    console.error("Error forwarding message:", err.message);
    registerBotReply(ERR);
    await msg.reply(ERR);
  }
});

/**
 * Build a multipart/form-data payload and POST it to the Python webhook.
 * Supports: text, audio (ptt/audio), image, document (treated as text extraction).
 */
async function forwardToWebhook(from, msg) {
  const form = new FormData();
  form.append("from", from);
  form.append("message_id", msg.id._serialized);

  let msgType = "text";

  if (["ptt", "audio"].includes(msg.type)) {
    // Voice note / audio file
    msgType = "audio";
    const media = await msg.downloadMedia();
    const ext = media.mimetype.split("/")[1].split(";")[0] || "ogg";
    const filePath = path.join(MEDIA_DIR, `${msg.id._serialized}.${ext}`);
    fs.writeFileSync(filePath, Buffer.from(media.data, "base64"));
    form.append("media_file", fs.createReadStream(filePath), {
      filename: path.basename(filePath),
      contentType: media.mimetype,
    });
    form.append("body", msg.body || "");
  } else if (msg.type === "image") {
    // Photo — send as base64 for Claude vision
    msgType = "image";
    const media = await msg.downloadMedia();
    form.append("media_data", media.data); // base64 string
    form.append("media_mimetype", media.mimetype);
    form.append("body", msg.body || msg.caption || ""); // caption if any
  } else if (msg.type === "document") {
    // Documents — treat body as text for now
    msgType = "text";
    form.append("body", msg.body || msg.caption || "[Document attached]");
  } else {
    // Plain text — check if it contains a URL
    const body = msg.body || "";
    const urlMatch = body.match(/https?:\/\/[^\s]+/);
    msgType = urlMatch ? "url" : "text";
    form.append("body", body);
    if (urlMatch) form.append("url", urlMatch[0]);
  }

  form.append("type", msgType);

  const response = await axios.post(WEBHOOK_URL, form, {
    headers: form.getHeaders(),
    timeout: 10_000, // 10s — Python just enqueues, so this should be fast
  });

  console.log(`✅ Forwarded to webhook | status: ${response.status} | type: ${msgType}`);
}

// ─── Express server — receives replies from the Python worker ──────────────────
const app = express();
app.use(express.json());

/**
 * POST /send
 * Body: { "to": "447700900000@c.us", "message": "Your article is ready..." }
 *
 * Called by the Python ARQ worker after processing completes.
 */
app.post("/send", async (req, res) => {
  const { to, message } = req.body;

  if (!to || !message) {
    return res.status(400).json({ error: "Missing 'to' or 'message'" });
  }

  try {
    registerBotReply(message);
    await client.sendMessage(to, message);
    console.log(`📤 Sent reply to ${to} (${message.length} chars)`);
    res.json({ ok: true });
  } catch (err) {
    console.error("Failed to send message:", err.message);
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /health — simple health check
 */
app.get("/health", (req, res) => {
  const state = client.info ? "CONNECTED" : "CONNECTING";
  res.json({ status: "ok", whatsapp: state });
});

app.listen(GATEWAY_PORT, () => {
  console.log(`🚀 Gateway HTTP server listening on port ${GATEWAY_PORT}`);
  console.log(`   → Forwards inbound messages to: ${WEBHOOK_URL}`);
  console.log(`   → Python worker calls POST /send to reply`);
});

// ─── Boot WhatsApp client ──────────────────────────────────────────────────────
client.initialize();
