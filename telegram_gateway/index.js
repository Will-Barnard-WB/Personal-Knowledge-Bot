/**
 * Telegram Gateway — Personal Knowledge Bot
 *
 * Responsibilities mirror the WhatsApp gateway but leverage the Telegram Bot API:
 *  1. Listen for inbound direct messages from the owner account
 *  2. Normalize media/text payloads and forward them to the Python webhook
 *  3. Expose POST /send so the Python worker can deliver replies via Telegram
 */

"use strict";

const path = require("path");
require("dotenv").config({ path: path.resolve(__dirname, "../.env") });

const TelegramBot = require("node-telegram-bot-api");
const express = require("express");
const axios = require("axios");
const FormData = require("form-data");
const fs = require("fs");

const TELEGRAM_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const WEBHOOK_URL = process.env.TELEGRAM_WEBHOOK_URL || process.env.WEBHOOK_URL || "http://localhost:8000/telegram-webhook";
const GATEWAY_PORT = parseInt(process.env.TELEGRAM_GATEWAY_PORT || "3001", 10);
const MEDIA_DIR = path.join(__dirname, "media");
const OWNER_ID = (process.env.MY_TELEGRAM_ID || "").trim();

if (!TELEGRAM_TOKEN) {
  console.error("TELEGRAM_BOT_TOKEN not set. Please add it to your .env file.");
  process.exit(1);
}

if (!OWNER_ID) {
  console.error("MY_TELEGRAM_ID not set. Refusing to start to avoid replying to strangers.");
  process.exit(1);
}

if (!fs.existsSync(MEDIA_DIR)) fs.mkdirSync(MEDIA_DIR, { recursive: true });

const bot = new TelegramBot(TELEGRAM_TOKEN, { polling: true });

bot.on("polling_error", (err) => {
  console.error("Polling error:", err?.message || err);
});

function isOwner(id) {
  return String(id).trim() === OWNER_ID;
}

function guessMimeType(filePath, fallback = "application/octet-stream") {
  const ext = path.extname(filePath || "").toLowerCase();
  switch (ext) {
    case ".ogg":
    case ".oga":
      return "audio/ogg";
    case ".mp3":
      return "audio/mpeg";
    case ".m4a":
      return "audio/mp4";
    case ".wav":
      return "audio/wav";
    case ".jpg":
    case ".jpeg":
      return "image/jpeg";
    case ".png":
      return "image/png";
    case ".webp":
      return "image/webp";
    default:
      return fallback;
  }
}

async function downloadTelegramFile(fileId) {
  const file = await bot.getFile(fileId);
  const fileUrl = `https://api.telegram.org/file/bot${TELEGRAM_TOKEN}/${file.file_path}`;
  const response = await axios.get(fileUrl, { responseType: "arraybuffer" });
  const buffer = Buffer.from(response.data);
  const filename = `${file.file_unique_id || fileId}${path.extname(file.file_path || "")}` || `${fileId}`;
  const mimetype = guessMimeType(file.file_path, "application/octet-stream");
  return { buffer, filename, mimetype, remotePath: file.file_path };
}

async function handleVoiceOrAudio(msg, form) {
  const audio = msg.voice || msg.audio;
  if (!audio) return false;

  const { buffer, filename, mimetype } = await downloadTelegramFile(audio.file_id);
  const targetPath = path.join(MEDIA_DIR, filename || `${audio.file_id}.ogg`);
  fs.writeFileSync(targetPath, buffer);
  form.append("media_file", fs.createReadStream(targetPath), {
    filename: path.basename(targetPath),
    contentType: audio.mime_type || mimetype,
  });
  form.append("body", msg.caption || msg.text || "");
  form.append("type", "audio");
  return true;
}

async function handlePhoto(msg, form) {
  const photos = msg.photo;
  if (!photos || !photos.length) return false;
  const bestPhoto = photos[photos.length - 1];
  try {
    const { buffer, filename, mimetype } = await downloadTelegramFile(bestPhoto.file_id);
    const targetPath = path.join(MEDIA_DIR, filename || `${bestPhoto.file_id}.jpg`);
    fs.writeFileSync(targetPath, buffer);
    form.append("media_file", fs.createReadStream(targetPath), {
      filename: path.basename(targetPath),
      contentType: mimetype || "image/jpeg",
    });
    form.append("media_data", buffer.toString("base64"));
    form.append("media_mimetype", mimetype || "image/jpeg");
    form.append("body", msg.caption || "");
    form.append("type", "image");
    return true;
  } catch (err) {
    console.error("Failed to save photo:", err?.message || err);
    return false;
  }
}

function detectUrl(text) {
  if (!text) return null;
  const match = text.match(/https?:\/\/[^\s]+/);
  return match ? match[0] : null;
}

async function forwardToWebhook(msg) {
  const form = new FormData();
  const from = String(msg.from.id);
  form.append("from", from);
  form.append("message_id", String(msg.message_id));
  form.append("reply_to", String(msg.chat.id));

  let handled = false;
  if (msg.voice || msg.audio) {
    handled = await handleVoiceOrAudio(msg, form);
  } else if (msg.photo) {
    handled = await handlePhoto(msg, form);
  }

  if (!handled) {
    const body = msg.text || msg.caption || "";
    const url = detectUrl(body);
    form.append("body", body);
    if (url) {
      form.append("type", "url");
      form.append("url", url);
    } else if (msg.document) {
      form.append("type", "text");
      form.append("body", body || msg.document.file_name || "[Document attached]");
    } else {
      form.append("type", "text");
    }
  }

  await axios.post(WEBHOOK_URL, form, {
    headers: form.getHeaders(),
    timeout: 10_000,
  });
}

const ACK_RESPONSE = "⏳ Got it! Processing...";
const ERR_RESPONSE = "❌ Oops — something went wrong. Please try again.";

bot.on("message", async (msg) => {
  if (!msg || !msg.chat || msg.chat.type !== "private") return;
  if (!msg.from || !isOwner(msg.from.id)) {
    console.log(`⛔ Ignored message from ${msg.from?.id || "unknown"} (not owner)`);
    return;
  }

  try {
    await bot.sendMessage(msg.chat.id, ACK_RESPONSE, { reply_to_message_id: msg.message_id });
  } catch (err) {
    console.error("Failed to send ACK:", err?.message || err);
  }

  try {
    await forwardToWebhook(msg);
    console.log(`✅ Forwarded Telegram message ${msg.message_id}`);
  } catch (err) {
    console.error("Error forwarding Telegram message:", err?.message || err);
    try {
      await bot.sendMessage(msg.chat.id, ERR_RESPONSE, { reply_to_message_id: msg.message_id });
    } catch (replyErr) {
      console.error("Failed to send failure notice:", replyErr?.message || replyErr);
    }
  }
});

const app = express();
app.use(express.json());

app.post("/send", async (req, res) => {
  const { to, message } = req.body;
  if (!to || !message) {
    return res.status(400).json({ error: "Missing 'to' or 'message'" });
  }
  if (String(to).trim() !== OWNER_ID) {
    console.warn(`Blocked reply to ${to} — only allowed to reply to owner ${OWNER_ID}`);
    return res.status(403).json({ error: "Bot can only reply to its owner." });
  }

  try {
    await bot.sendMessage(to, message);
    console.log(`📤 Sent Telegram reply to ${to} (${message.length} chars)`);
    res.json({ ok: true });
  } catch (err) {
    console.error("Failed to send Telegram reply:", err?.message || err);
    res.status(500).json({ error: err?.message || "Unknown error" });
  }
});

app.get("/health", (req, res) => {
  res.json({ status: "ok", telegram: "CONNECTED" });
});

app.listen(GATEWAY_PORT, () => {
  console.log(`🚀 Telegram gateway listening on port ${GATEWAY_PORT}`);
  console.log(`   → Forwards inbound messages to: ${WEBHOOK_URL}`);
  console.log("   → Python worker calls POST /send to reply");
});
