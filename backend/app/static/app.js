const state = {
  conversations: [],
  currentConversationId: null,
  isStreaming: false,
  streamReader: null,
  assistantElement: null,
  providerInfoByName: {},
};

const els = {
  conversationList: document.getElementById("conversationList"),
  newConversationBtn: document.getElementById("newConversationBtn"),
  messages: document.getElementById("messages"),
  messageInput: document.getElementById("messageInput"),
  sendBtn: document.getElementById("sendBtn"),
  cancelBtn: document.getElementById("cancelBtn"),
  providerSelect: document.getElementById("providerSelect"),
  modelInput: document.getElementById("modelInput"),
  statusText: document.getElementById("statusText"),
  statsCards: document.getElementById("statsCards"),
  throughputChart: document.getElementById("throughputChart"),
  recentLogs: document.getElementById("recentLogs"),
};

const defaultModels = {
  gemini: "gemini-3.5-flash",
  openai: "gpt-4.1-mini",
  anthropic: "claude-3-5-sonnet-20241022",
  mock: "mock-echo-v1",
};

function getProviderInfo(providerName) {
  return state.providerInfoByName[providerName] || null;
}

function isProviderConfigured(providerName) {
  const info = getProviderInfo(providerName);
  return Boolean(info && info.configured);
}

function getFallbackProvider() {
  const providers = Object.values(state.providerInfoByName);
  const firstConfigured = providers.find((provider) => provider.configured);
  if (firstConfigured) return firstConfigured.name;
  return providers.length ? providers[0].name : "mock";
}

function defaultModelFor(providerName) {
  const info = getProviderInfo(providerName);
  return info?.default_model || defaultModels[providerName] || "";
}

function ensureConfiguredProvider({ updateStatus = false } = {}) {
  const selected = els.providerSelect.value;
  if (!selected) return false;
  if (isProviderConfigured(selected)) return true;

  const fallback = getFallbackProvider();
  if (fallback && fallback !== selected) {
    els.providerSelect.value = fallback;
    els.modelInput.value = defaultModelFor(fallback);
    if (updateStatus) {
      setStatus(`Provider '${selected}' has no API key. Switched to '${fallback}'.`);
    }
    return true;
  }

  if (updateStatus) {
    setStatus(`Provider '${selected}' is not configured. Add API key or choose another provider.`);
  }
  return false;
}

function fmtTime(value) {
  if (!value) return "";
  return new Date(value).toLocaleString();
}

function escapeHtml(str) {
  return str
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setStatus(text) {
  els.statusText.textContent = text;
}

function toggleInput(disabled) {
  els.sendBtn.disabled = disabled;
  els.messageInput.disabled = disabled;
  els.cancelBtn.disabled = !disabled;
}

function renderConversations() {
  els.conversationList.innerHTML = "";
  for (const conversation of state.conversations) {
    const li = document.createElement("li");
    li.className = "conversation-item";
    if (conversation.id === state.currentConversationId) {
      li.classList.add("active");
    }
    li.innerHTML = `
      <div class="conversation-title">${escapeHtml(conversation.title)}</div>
      <div class="conversation-preview">${escapeHtml(conversation.last_message_preview || "")}</div>
      <div class="conversation-time">${fmtTime(conversation.updated_at)}</div>
    `;
    li.onclick = () => selectConversation(conversation.id);
    els.conversationList.appendChild(li);
  }
}

function appendMessage(role, content) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = content;
  els.messages.appendChild(div);
  els.messages.scrollTop = els.messages.scrollHeight;
  return div;
}

function renderMessages(messages) {
  els.messages.innerHTML = "";
  for (const message of messages) {
    appendMessage(message.role, message.content);
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Request failed (${response.status}): ${text}`);
  }
  return response.json();
}

async function loadProviders() {
  const allProviders = await fetchJson("/api/providers");
  state.providerInfoByName = Object.fromEntries(allProviders.map((provider) => [provider.name, provider]));
  const providers = allProviders.filter((provider) => provider.configured);
  els.providerSelect.innerHTML = "";
  let selectedProvider = null;

  if (!providers.length) {
    throw new Error("No configured providers found. Add an API key or use mock.");
  }

  for (const provider of providers) {
    const option = document.createElement("option");
    option.value = provider.name;
    option.textContent = provider.name;
    if (selectedProvider === null) {
      selectedProvider = provider.name;
    }
    els.providerSelect.appendChild(option);
  }

  if (!selectedProvider) {
    selectedProvider = providers[0]?.name || "mock";
  }
  els.providerSelect.value = selectedProvider;
  els.modelInput.value = defaultModelFor(selectedProvider);
}

async function loadConversations() {
  state.conversations = await fetchJson("/api/conversations");
  renderConversations();
}

async function createConversation() {
  const created = await fetchJson("/api/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider: els.providerSelect.value,
      model: els.modelInput.value.trim() || undefined,
    }),
  });
  state.currentConversationId = created.id;
  await loadConversations();
  await selectConversation(created.id);
  return created.id;
}

async function selectConversation(conversationId) {
  state.currentConversationId = conversationId;
  const conversation = await fetchJson(`/api/conversations/${conversationId}`);
  renderMessages(conversation.messages);
  if (conversation.provider) {
    if (isProviderConfigured(conversation.provider)) {
      els.providerSelect.value = conversation.provider;
      els.modelInput.value = conversation.model || defaultModelFor(conversation.provider);
    } else {
      ensureConfiguredProvider({ updateStatus: true });
    }
  }
  if (!conversation.provider && conversation.model && !els.modelInput.value.trim()) {
    els.modelInput.value = conversation.model;
  }
  renderConversations();
}

function parseSSEBuffer(buffer, onEvent) {
  let pending = buffer;
  let boundary = pending.indexOf("\n\n");
  while (boundary !== -1) {
    const rawEvent = pending.slice(0, boundary).trim();
    pending = pending.slice(boundary + 2);
    boundary = pending.indexOf("\n\n");
    if (!rawEvent) continue;

    const dataLine = rawEvent
      .split("\n")
      .map((line) => line.trim())
      .find((line) => line.startsWith("data:"));
    if (!dataLine) continue;

    try {
      const eventData = JSON.parse(dataLine.slice(5).trim());
      onEvent(eventData);
    } catch (error) {
      console.error("Invalid SSE payload", error);
    }
  }
  return pending;
}

async function sendMessage() {
  const text = els.messageInput.value.trim();
  if (!text || state.isStreaming) return;
  if (!ensureConfiguredProvider({ updateStatus: true })) return;

  state.isStreaming = true;
  toggleInput(true);
  setStatus("Sending...");

  let conversationId = state.currentConversationId;
  if (!conversationId) {
    conversationId = await createConversation();
  }

  appendMessage("user", text);
  els.messageInput.value = "";
  state.assistantElement = appendMessage("assistant", "");

  try {
    const response = await fetch(`/api/conversations/${conversationId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        provider: els.providerSelect.value,
        model: els.modelInput.value.trim() || undefined,
      }),
    });
    if (!response.ok || !response.body) {
      const errorText = await response.text();
      throw new Error(errorText || "Unable to stream response");
    }

    const reader = response.body.getReader();
    state.streamReader = reader;
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = parseSSEBuffer(buffer, (eventData) => {
        if (eventData.type === "start") {
          setStatus(`Streaming ${eventData.provider}/${eventData.model}`);
          return;
        }
        if (eventData.type === "chunk") {
          state.assistantElement.textContent += eventData.text;
          els.messages.scrollTop = els.messages.scrollHeight;
          return;
        }
        if (eventData.type === "done") {
          const suffix = eventData.status === "cancelled" ? " (cancelled)" : "";
          setStatus(`Completed${suffix}`);
          return;
        }
        if (eventData.type === "error") {
          state.assistantElement.textContent = `Error: ${eventData.message}`;
          setStatus("Error");
        }
      });
    }

    if (!state.assistantElement.textContent.trim()) {
      state.assistantElement.textContent = "(no output)";
    }
  } catch (error) {
    state.assistantElement.textContent = `Error: ${error.message}`;
    setStatus("Error");
  } finally {
    state.streamReader = null;
    state.isStreaming = false;
    toggleInput(false);
    await loadConversations();
    await selectConversation(conversationId);
    await refreshDashboard();
  }
}

async function cancelConversation() {
  if (!state.currentConversationId || !state.isStreaming) return;
  await fetchJson(`/api/conversations/${state.currentConversationId}/cancel`, { method: "POST" });
  setStatus("Cancel requested...");
}

function renderStats(summary) {
  const stats = [
    { label: "Requests", value: String(summary.total_requests) },
    { label: "Completed", value: String(summary.completed_requests) },
    { label: "Errors", value: String(summary.error_requests) },
    { label: "Cancelled", value: String(summary.cancelled_requests) },
    { label: "Avg Latency", value: summary.avg_latency_ms ? `${summary.avg_latency_ms} ms` : "-" },
    { label: "P95 Latency", value: summary.p95_latency_ms ? `${summary.p95_latency_ms} ms` : "-" },
    { label: "Error Rate", value: `${summary.error_rate}%` },
    { label: "Queue Depth", value: String(summary.queue_depth) },
  ];

  els.statsCards.innerHTML = stats
    .map(
      (item) => `
      <div class="stat-card">
        <div class="stat-label">${escapeHtml(item.label)}</div>
        <div class="stat-value">${escapeHtml(item.value)}</div>
      </div>
    `
    )
    .join("");
}

function renderThroughput(points) {
  if (!points.length) {
    els.throughputChart.innerHTML = "<small>No data yet</small>";
    return;
  }
  const trimmed = points.slice(-40);
  const maxCount = Math.max(...trimmed.map((item) => item.count), 1);
  els.throughputChart.innerHTML = trimmed
    .map(
      (item) =>
        `<div class="bar" title="${item.minute}: ${item.count}" style="height:${Math.max(
          8,
          (item.count / maxCount) * 100
        )}%"></div>`
    )
    .join("");
}

function statusTag(status) {
  if (status === "completed") return '<span class="tag tag-ok">completed</span>';
  if (status === "cancelled") return '<span class="tag tag-cancelled">cancelled</span>';
  return '<span class="tag tag-error">error</span>';
}

function renderRecentLogs(logs) {
  if (!logs.length) {
    els.recentLogs.innerHTML = '<div class="log-row">No logs yet</div>';
    return;
  }
  els.recentLogs.innerHTML = logs
    .map(
      (log) => `
      <div class="log-row">
        <div>${statusTag(log.status)} ${escapeHtml(log.provider)}/${escapeHtml(log.model)}</div>
        <div class="log-meta">
          latency=${log.latency_ms ?? "-"}ms | tokens=${log.total_tokens ?? "-"} | ${escapeHtml(log.request_id)}
        </div>
      </div>
    `
    )
    .join("");
}

async function refreshDashboard() {
  const summary = await fetchJson("/api/dashboard/summary?hours=24");
  const logs = await fetchJson("/api/logs/recent?limit=15");
  renderStats(summary);
  renderThroughput(summary.throughput);
  renderRecentLogs(logs);
}

els.newConversationBtn.onclick = async () => {
  await createConversation();
  els.messages.innerHTML = "";
};
els.sendBtn.onclick = sendMessage;
els.cancelBtn.onclick = cancelConversation;
els.providerSelect.onchange = () => {
  ensureConfiguredProvider({ updateStatus: true });
  const provider = els.providerSelect.value;
  if (!els.modelInput.value.trim() || els.modelInput.value === defaultModelFor("mock")) {
    els.modelInput.value = defaultModelFor(provider);
  }
};
els.messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

async function bootstrap() {
  try {
    await loadProviders();
    await loadConversations();
    if (state.conversations.length) {
      await selectConversation(state.conversations[0].id);
    }
    await refreshDashboard();
    setStatus("Ready");
    setInterval(refreshDashboard, 15000);
  } catch (error) {
    setStatus(`Failed to load: ${error.message}`);
  }
}

bootstrap();
