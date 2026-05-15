// Chat — message sending, SSE stream reading, tool-call orchestration.

import { api }   from './api.js';
import { state } from './state.js';
import {
  createStreamingMessage, appendMessage,
  cancelAllToolApprovals, finalizeStreamingMessage, setStreamingMessageLogIndex,
  scrollToBottom, renderAllMessages,
  createThinkingBlock, updateThinkingBlock, finalizeThinkingBlock,
  createToolStrip, toolStripFinalize, toolStripSetApproval, toolStripSetRunning,
} from './renderer.js';
import { applyMarkdown } from './markdown.js';
import { persistConversationFor, createNewConversation } from './conversations.js';
import { refreshFilePanel } from './file_panel.js';
import { escapeHtml } from './format.js';
import { readResponseError, readSSEStream } from './stream_consumer.js';
import { initImageAttachments, hasPendingAttachments } from './chat_attachments.js';
export { initImageAttachments, hasPendingAttachments } from './chat_attachments.js';
import { buildApiMessages, buildToolsPayload, buildMcpToolMetaPayload } from './chat_payloads.js';
import { sendMessage as sendMessageImpl } from './chat_send.js';
import { editAndResend as editAndResendImpl, regenerateFrom as regenerateFromImpl } from './chat_edit.js';

let turnAbortController = null;
let turnCancelled = false;
const activeTurns = new Map();

// Attachment handling lives in chat_attachments.js.

// Payload construction lives in chat_payloads.js.

// ── Streaming state ───────────────────────────────────────────────────────────

function setStreaming(active) {
  state.isStreaming = active;

  const sendBtn = document.getElementById('send-btn');
  const stopBtn = document.getElementById('stop-btn');
  const input = document.getElementById('user-input');

  if (sendBtn) {
    sendBtn.hidden = active;
    sendBtn.disabled = active || !(input?.value || '').trim();
  }
  if (stopBtn) stopBtn.hidden = !active;
}

function isTurnVisible(turn) {
  return state.convId === turn.convId;
}

function syncVisibleTurn(turn) {
  if (!isTurnVisible(turn)) return;
  state.messages = turn.messages;
  state.displayLog = turn.displayLog;
}

function isCurrentStreamContext(turn, ctx) {
  if (!turn?.convId || !ctx) return true;
  return activeTurns.get(turn.convId)?.ctx === ctx;
}

function createStreamContext(turn) {
  const ctx = {
    accText:            '',
    accReasoning:       '',
    reasoningFinalized: false,
    reasoningBodyEl:    null,
    contentEl:          null,
    turn,
    toolStartNames:     [],
    toolStrips:         [],
    toolApprovalIndex:  0,
    toolRunningIndex:   0,
    toolResultIndex:    0,
    assistantDone:      false,
    hadToolUse:         false,
    isVisible:          () => isTurnVisible(turn),
    getContentEl:       () => {
      if (!ctx.contentEl && isTurnVisible(turn)) ctx.contentEl = createStreamingMessage();
      return ctx.contentEl;
    },
  };
  return ctx;
}

function activeTurnBaseLog(displayLog = []) {
  const lastUserIndex = [...displayLog]
    .map((entry, index) => ({ entry, index }))
    .reverse()
    .find(item => item.entry?.type === 'message' && item.entry?.role === 'user')?.index;
  return lastUserIndex === undefined ? [] : displayLog.slice(0, lastUserIndex + 1);
}

function reattachRuntime(runtime) {
  if (!runtime || !isTurnVisible(runtime.turn)) return false;

  const { turn, ctx } = runtime;
  syncVisibleTurn(turn);
  renderAllMessages(turn.displayLog);

  ctx.contentEl = null;
  ctx.reasoningBodyEl = null;
  ctx.toolStrips = [];

  if (ctx.accReasoning) {
    ctx.reasoningBodyEl = createThinkingBlock();
    updateThinkingBlock(ctx.reasoningBodyEl, ctx.accReasoning);
    if (ctx.reasoningFinalized || ctx.accText || ctx.toolStartNames.length) {
      finalizeThinkingBlock(ctx.reasoningBodyEl, ctx.accReasoning);
      ctx.reasoningBodyEl = null;
    }
  }

  if (ctx.accText) {
    ctx.contentEl = createStreamingMessage();
    applyMarkdown(ctx.contentEl, ctx.accText);
  }

  ctx.toolStartNames.forEach(name => {
    ctx.toolStrips.push(createToolStrip(name));
  });

  scrollToBottom(true);
  return true;
}

export function reattachActiveTurn(convId) {
  const runtime = activeTurns.get(convId);
  return reattachRuntime(runtime);
}

async function attachServerStream(convId, streamId, data = {}) {
  if (!convId || !streamId) return false;
  const existingRuntime = activeTurns.get(convId);
  if (existingRuntime) {
    existingRuntime.streamId ||= streamId;
    const attached = reattachActiveTurn(convId);
    if (attached && !existingRuntime.ctx?.assistantDone) {
      state.streamId = existingRuntime.streamId;
      setStreaming(true);
    }
    return attached;
  }

  const turn = {
    convId,
    title:      data.title || currentTitle(),
    messages:   data.messages || [],
    displayLog: activeTurnBaseLog(data.displayLog || []),
  };
  const ctx = createStreamContext(turn);
  activeTurns.set(convId, { turn, ctx, streamId });

  if (isTurnVisible(turn)) {
    syncVisibleTurn(turn);
    document.getElementById('chat-title-input').value = turn.title || '';
    renderAllMessages(turn.displayLog);
    setStreaming(true);
    state.streamId = streamId;
  }


  try {
    turnAbortController = new AbortController();
    const resp = await api.stream('/api/chat/stream', {
      stream_id: streamId,
      conv_id: convId,
      attach: true,
    }, { signal: turnAbortController.signal });

    if (!resp.ok) throw new Error(await readResponseError(resp));

    const success = await readSSEStream(resp, raw => processSSEEvent(raw, ctx));
    if (!success || turnCancelled) return false;

    if (!ctx.assistantDone) finalizeAssistantAnswer(ctx);
    if (isCurrentStreamContext(turn, ctx)) syncFinalAssistantFooter(turn, ctx);
    return true;
  } catch (err) {
    return false;
  } finally {
    finishAssistantTurn(turn, ctx);
  }
}

document.addEventListener('chat:conversation-opened', async event => {
  const { convId, data } = event.detail || {};
  if (data?.active_stream_id) {
    const attached = await attachServerStream(convId, data.active_stream_id, data);
    if (!attached && state.convId === convId) {
      state.messages = data.messages || [];
      state.displayLog = data.displayLog || [];
      renderAllMessages(state.displayLog);
      setStreaming(false);
    }
    return;
  }
  if (!reattachActiveTurn(convId)) {
    state.streamId = null;
    setStreaming(false);
  }
});

function currentTitle() {
  return document.getElementById('chat-title-input').value.trim() || 'Untitled';
}

function applyTurnTitle(turn, title) {
  const nextTitle = (title || '').trim();
  if (!turn || !nextTitle || turn.title === nextTitle) return;

  turn.title = nextTitle;
  if (isTurnVisible(turn)) {
    const titleInput = document.getElementById('chat-title-input');
    if (titleInput && document.activeElement !== titleInput) titleInput.value = nextTitle;
  }
  document.dispatchEvent(new CustomEvent('chat:conversation-title-updated', {
    detail: { convId: turn.convId, title: nextTitle },
  }));
}

function createTurnContext(convId) {
  return {
    convId,
    title: currentTitle(),
    messages: state.messages.slice(),
    displayLog: state.displayLog.slice(),
  };
}

async function persistTurnConversation(turn) {
  await persistConversationFor(turn.convId, {
    title: turn.title,
    messages: turn.messages,
    displayLog: turn.displayLog,
  });
}

function finishAssistantTurn(turn = null, ctx = null) {
  const isCurrent = !turn?.convId || !ctx || isCurrentStreamContext(turn, ctx);

  if (turn?.convId && isCurrent) activeTurns.delete(turn.convId);

  if ((!turn || isTurnVisible(turn)) && isCurrent) {
    turnAbortController = null;
    state.streamId = null;
    setStreaming(false);
  }
}

function lastAssistantMessageIndex(displayLog = []) {
  for (let i = displayLog.length - 1; i >= 0; i--) {
    const entry = displayLog[i];
    if (entry?.type === 'message' && entry.role === 'assistant' && String(entry.content ?? '').trim()) return i;
  }
  return -1;
}

function syncFinalAssistantFooter(turn, ctx) {
  if (!ctx?.contentEl || !isTurnVisible(turn)) return;
  const logIndex = lastAssistantMessageIndex(turn.displayLog);
  if (logIndex >= 0) setStreamingMessageLogIndex(ctx.contentEl, logIndex);
}

function finalizeAssistantAnswer(ctx, messages = null, displayLog = null) {
  if (!ctx?.turn) return;

  if (Array.isArray(messages)) ctx.turn.messages = messages;
  if (Array.isArray(displayLog)) ctx.turn.displayLog = displayLog;
  syncVisibleTurn(ctx.turn);

  if (ctx.assistantDone) {
    syncFinalAssistantFooter(ctx.turn, ctx);
    return;
  }

  ctx.assistantDone = true;

  if (ctx.reasoningBodyEl) {
    finalizeThinkingBlock(ctx.reasoningBodyEl, ctx.accReasoning);
    ctx.reasoningBodyEl = null;
  }
  if (ctx.contentEl) {
    finalizeStreamingMessage(ctx.contentEl, ctx.accText);
    syncFinalAssistantFooter(ctx.turn, ctx);
  }

  // assistant_done owns only the visible UI transition. Stream cleanup/title work may continue.
  if (isTurnVisible(ctx.turn) && isCurrentStreamContext(ctx.turn, ctx)) {
    state.streamId = null;
    setStreaming(false);
    scrollToBottom();
  }
}

async function runAssistantTurnAndPersist(turn) {
  setStreaming(true);
  turnCancelled = false;
  let ctx = null;

  try {
    ctx = await runChatLoop(turn);
    if (isCurrentStreamContext(turn, ctx)) syncFinalAssistantFooter(turn, ctx);
  } finally {
    finishAssistantTurn(turn, ctx);
  }
}

export async function stopAssistantTurn() {
  if (!state.isStreaming && !state.streamId) return;

  turnCancelled = true;
  cancelAllToolApprovals();
  turnAbortController?.abort();

  const streamId = state.streamId;
  state.streamId = null;
  setStreaming(false);

  if (streamId) {
    try { await api.post('/api/chat/cancel', { stream_id: streamId }); } catch {}
  }
}

function chatFlowDeps() {
  return {
    createNewConversation,
    createTurnContext,
    setStreaming,
    syncVisibleTurn,
    isTurnVisible,
    persistTurnConversation,
    runAssistantTurnAndPersist,
    hasPendingAttachments,
  };
}

// ── Main entry point ──────────────────────────────────────────────────────────

export async function sendMessage(userText) {
  return sendMessageImpl(userText, chatFlowDeps());
}

// ── SSE helpers ───────────────────────────────────────────────────────────────

function stripForToolEvent(ctx, evt, cursorKey) {
  const stripIndex = ctx[cursorKey] || 0;
  let strip = ctx.toolStrips[stripIndex];
  if (!strip && ctx.isVisible()) strip = createToolStrip(evt.name);
  if (strip && !ctx.toolStrips[stripIndex]) ctx.toolStrips[stripIndex] = strip;
  ctx[cursorKey] = stripIndex + 1;
  return strip;
}

/** Parses a single SSE event and mutates the streaming context. Returns false on terminal error. */
async function processSSEEvent(raw, ctx) {
  const evt = JSON.parse(raw);

  if (evt.type === 'reasoning') {
    ctx.accReasoning += evt.content;
    if (!ctx.reasoningBodyEl && ctx.isVisible()) ctx.reasoningBodyEl = createThinkingBlock();
    if (ctx.reasoningBodyEl) updateThinkingBlock(ctx.reasoningBodyEl, ctx.accReasoning);

  } else if (evt.type === 'text') {
    if (ctx.reasoningBodyEl) {
      finalizeThinkingBlock(ctx.reasoningBodyEl, ctx.accReasoning);
      ctx.reasoningBodyEl = null;
    }
    ctx.reasoningFinalized = true;
    ctx.accText += evt.content;
    const el = ctx.getContentEl();
    if (el) {
      applyMarkdown(el, ctx.accText);
      scrollToBottom();
    }

  } else if (evt.type === 'tool_start') {
    // Keep indices aligned even when the user is viewing another chat.
    ctx.toolStartNames.push(evt.name);
    ctx.toolStrips.push(ctx.isVisible() ? createToolStrip(evt.name) : null);

  } else if (evt.type === 'tool_calls') {
    // Tool execution is server-owned; frontend only renders starts/results.

  } else if (evt.type === 'tool_approval_required') {
    // Server is paused waiting for the user to approve or deny this tool call.
    // Use a cursor, not indexOf(name), so repeated calls to the same tool update
    // the matching strip instead of always reusing the first one.
    const strip = stripForToolEvent(ctx, evt, 'toolApprovalIndex');

    let approved = false;
    if (strip) {
      const fakeCall = { function: { name: evt.name, arguments: JSON.stringify(evt.args || {}) } };
      approved = await toolStripSetApproval(strip, fakeCall);
      if (approved) toolStripSetRunning(strip, evt.args || {});
    }

    // Send the decision back to the server so it can unblock and proceed.
    api.post('/api/chat/approve', {
      stream_id: state.streamId,
      call_id:   evt.call_id,
      approved,
    }).catch(() => {});

  } else if (evt.type === 'tool_running') {
    const strip = stripForToolEvent(ctx, evt, 'toolRunningIndex');
    if (strip) toolStripSetRunning(strip, evt.args || {});

  } else if (evt.type === 'tool_result') {
    if (ctx.reasoningBodyEl) {
      finalizeThinkingBlock(ctx.reasoningBodyEl, ctx.accReasoning);
      ctx.reasoningBodyEl = null;
    }
    if (ctx.contentEl) {
      finalizeStreamingMessage(ctx.contentEl, ctx.accText);
      ctx.contentEl = null;
    }

    const strip = stripForToolEvent(ctx, evt, 'toolResultIndex');
    // Pass no displayName — renderer.js derives the label via getToolDisplayLabel()
    // which consults the tool_adapters/ system (each adapter declares its own labelArg).
    if (strip) toolStripFinalize(strip, evt.name, evt.args || {}, evt.result || '');
    // Note: stripForToolEvent already increments ctx.toolResultIndex internally.

    ctx.accText = '';
    ctx.accReasoning = '';
    ctx.reasoningFinalized = false;
    if (ctx.isVisible()) refreshFilePanel({ keepPreview: true }).catch(() => {});

  } else if (evt.type === 'assistant_done') {
    finalizeAssistantAnswer(ctx, evt.messages, evt.displayLog);

  } else if (evt.type === 'title') {
    if (ctx.turn) applyTurnTitle(ctx.turn, evt.title || ctx.turn.title);

  } else if (evt.type === 'error') {
    const el = ctx.getContentEl();
    if (el) el.innerHTML = `<span class="inline-error">Error: ${escapeHtml(evt.message)}</span>`;
    return false; // signal abort
  }

  return true;
}

// ── SSE loop ──────────────────────────────────────────────────────────────────

async function runChatLoop(turn) {
  const ctx = createStreamContext(turn);
  const streamId = crypto.randomUUID();

  activeTurns.set(turn.convId, { turn, ctx, streamId });
  state.streamId = streamId;

  // A newly-started turn already has the user's message appended in-place.
  // Reattaching here would fully re-render the chat and cause the first flash
  // right after send. Reattach is only for switching/reloading into a running turn.

  try {
    turnAbortController = new AbortController();

    const resp = await api.stream('/api/chat/stream', {
      model:     state.model || 'gpt-4o',
      temperature:  state.temperature ?? 0.7,
      messages:              await buildApiMessages(turn.messages),
      conversation_messages: turn.messages,
      display_log:           turn.displayLog,
      title:                 turn.title,
      tools:                 buildToolsPayload(),
      mcp_tool_meta:         buildMcpToolMetaPayload(),
      stream_id:             streamId,
      conv_id:               turn.convId,
      auto_generate_titles:  state.autoGenerateTitles ?? true,
    }, { signal: turnAbortController.signal });

    if (!resp.ok) throw new Error(await readResponseError(resp));

    const success = await readSSEStream(resp, raw => processSSEEvent(raw, ctx));
    if (!success || turnCancelled) return;

    if (!ctx.assistantDone) finalizeAssistantAnswer(ctx);
  } catch (err) {
    if (turnCancelled || err.name === 'AbortError') return ctx;

    const el = ctx.getContentEl();
    if (el) el.innerHTML = `<span class="inline-error">Network error: ${escapeHtml(err.message)}</span>`;
  }

  return ctx;
}

// Edit/resend and regenerate flows live in chat_edit.js.

export async function editAndResend(logIndex, newText, imageUrls = [], files = [], attachments = null) {
  return editAndResendImpl(logIndex, newText, imageUrls, files, attachments, chatFlowDeps());
}

export async function regenerateFrom(logIndex) {
  return regenerateFromImpl(logIndex, chatFlowDeps());
}