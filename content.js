import { startPicking } from "./selector.js";
import { extractFromContainer } from "./extractor.js";
import { nowISO } from "./util.js";

const state = {
  containerSelector: null,
  lastExtract: null,
  lastJson: null,
};

function originKey() {
  try { return new URL(location.href).origin; } catch { return "*"; }
}

async function loadSavedSelector() {
  const key = "cpe::" + originKey();
  return new Promise(resolve => {
    try {
      chrome.storage.sync.get([key], (res) => resolve(res[key] || null));
    } catch (e) { resolve(null); }
  });
}

function autoDetectContainer() {
  // LinkedIn messaging containers (优先)
  const found = document.querySelector([
    "div.msg-s-message-list-content",
    "section.msg-s-message-list",
    "div.msg-conversation__container",
    "main[role='main'] .msg-convo-wrapper",
    "div .msg-s-message-list__events-list"
  ].join(","));
  if (found) return found;

  // 其它常见聊天容器兜底
  return document.querySelector("[role='list'], .chat-list, .messages, .conversation, .msg-list");
}

// 内容脚本启动时，尝试加载上次保存的选择器
loadSavedSelector().then(sel => { if (sel) state.containerSelector = sel; });

// 监听弹窗指令
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.source !== "CPE_POPUP") return;

  if (msg.type === "START_PICK") {
    startPicking();
    sendResponse({ ok: true });
    return true;
  }

  if (msg.type === "EXTRACT") {
    // 1) 优先使用用户设置的选择器
    let container = state.containerSelector ? document.querySelector(state.containerSelector) : null;

    // 2) 兜底：自动识别容器（LinkedIn 优先）
    if (!container) {
      container = autoDetectContainer();
      if (container) {
        // 若有 id 就用 #id 作为记忆（避免复杂选择器失效）
        state.containerSelector = (container.id ? `#${container.id}` : null) || state.containerSelector;
      }
    }

    if (!container) return sendResponse({ ok: false, error: "未选择或找不到容器（已尝试自动识别失败）" });

    const data = extractFromContainer(container);
    const payload = {
      pageTitle: document.title,
      pageUrl: location.href,
      scrapedAt: nowISO(),
      containerSelector: state.containerSelector,
      ...data,
    };
    state.lastExtract = payload;
    sendResponse({ ok: true, payload });
    return true;
  }

  if (msg.type === "SET_SELECTOR") {
    state.containerSelector = msg.selector;
    // 立刻持久化，减少丢失
    try { chrome.storage.sync.set({ ["cpe::" + originKey()]: state.containerSelector }); } catch {}
    sendResponse({ ok: true });
    return true;
  }
});

// 选择器覆盖层的事件回传到弹窗
window.addEventListener("message", (e) => {
  if (e.source !== window) return;
  const data = e.data || {};
  if (data.source !== "CPE_SELECTOR") return;

  if (data.type === "CONTAINER_PICKED") {
    state.containerSelector = data.selector;
    try { chrome.storage.sync.set({ ["cpe::" + originKey()]: state.containerSelector }); } catch {}
    chrome.runtime.sendMessage({ source: "CPE_CONTENT", type: "CONTAINER_PICKED", selector: data.selector });
  }
  if (data.type === "CANCEL") {
    chrome.runtime.sendMessage({ source: "CPE_CONTENT", type: "PICK_CANCELLED" });
  }
});
