import { sanitizeText, toAbsoluteUrl } from "./util.js";

function guessMessageNodes(container) {
  // LinkedIn-specific selectors first
  try {
    const host = location.hostname;
    if (/(^|\.)linkedin\.com$/.test(host)) {
      const liCandidates = container.querySelectorAll([
        "li.msg-s-event-listitem",
        "div.msg-s-message-group__message",
        "div.msg-s-event-listitem__message-bubble",
        "div.msg-s-message-list-content li",
      ].join(","));
      if (liCandidates.length) return [...liCandidates];
    }
  } catch(_) {}

  // Generic
  const candidates = container.querySelectorAll(
    [
      "[role='listitem']",
      "[data-message]",
      "[data-testid*='message']",
      ".message, .msg, .chat-message, .bubble, .im_message, .Message, .c-message_kit__message"
    ].join(",")
  );
  if (candidates.length) return [...candidates];

  return [...container.children].filter(n => n.textContent.trim().length > 0);
}

function findTimestamp(el) {
  // LinkedIn-specific
  const liTime = el.querySelector("time[datetime], time, span.msg-s-message-group__timestamp");
  if (liTime) {
    const dt = liTime.getAttribute("datetime") || liTime.getAttribute("title") || liTime.textContent;
    if (dt) return sanitizeText(dt);
  }
  const liAttr = el.getAttribute("data-time");
  if (liAttr) return liAttr;

  // Generic
  const t1 = el.querySelector("time[datetime]");
  if (t1) return t1.getAttribute("datetime");
  const t2 = el.querySelector("[data-timestamp], [data-time], [data-utime]");
  if (t2) return t2.getAttribute("data-timestamp") || t2.getAttribute("data-time") || t2.getAttribute("data-utime");
  const labeled = el.getAttribute("aria-label") || "";
  if (/\d{1,4}[:\/.\-]\d{1,2}/.test(labeled)) return labeled;
  const text = el.textContent;
  const timeLike = text.match(/\b(\d{1,2}:\d{2}(?:\s?[AP]M)?)\b/);
  if (timeLike) return timeLike[0];
  return null;
}

function findSender(el) {
  // LinkedIn-specific
  const liSender = el.querySelector("a.msg-s-message-group__profile-link, span.msg-s-message-group__name, span[dir][data-anonymize]");
  if (liSender) return sanitizeText(liSender.textContent || "");

  // Generic
  const s = el.querySelector(".sender, .author, .from, .nickname, .name, [data-author], [data-sender], [aria-label*='来自']");
  if (!s) return null;
  return sanitizeText(s.textContent || s.getAttribute("aria-label") || "");
}

function extractAttachments(el) {
  const list = [];
  const medias = el.querySelectorAll("img, video, audio, a[download], a[href]");
  for (const m of medias) {
    if (m.tagName === "IMG") {
      list.push({ type: "image", url: toAbsoluteUrl(m.currentSrc || m.src) });
    } else if (m.tagName === "VIDEO") {
      const src = m.currentSrc || (m.querySelector("source")?.src) || m.src;
      if (src) list.push({ type: "video", url: toAbsoluteUrl(src) });
    } else if (m.tagName === "A") {
      const href = m.getAttribute("href");
      if (!href) continue;
      const abs = toAbsoluteUrl(href);
      const isMedia = /\.(png|jpe?g|gif|webp|svg|mp4|mov|webm|mp3|wav|ogg)(\?|$)/i.test(abs);
      list.push({ type: isMedia ? "file/media" : "file", url: abs, name: m.textContent.trim() || undefined });
    } else if (m.tagName === "AUDIO") {
      const src = m.currentSrc || (m.querySelector("source")?.src) || m.src;
      if (src) list.push({ type: "audio", url: toAbsoluteUrl(src) });
    }
  }
  return dedupe(list);
}

function dedupe(arr) {
  const seen = new Set();
  return arr.filter(x => {
    const k = `${x.type}|${x.url}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

export function extractFromContainer(container, opts = {}) {
  const nodes = guessMessageNodes(container);
  const messages = nodes.map((node, idx) => {
    const text = sanitizeText(node.textContent || "");
    const html = node.innerHTML;
    const timestamp = findTimestamp(node);
    const sender = findSender(node);
    const attachments = extractAttachments(node);
    return { index: idx, sender, text, html, timestamp, attachments };
  }).filter(m => m.text.length > 0 || m.attachments.length > 0);

  return { count: messages.length, messages };
}
