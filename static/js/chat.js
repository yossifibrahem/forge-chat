// Chat — message sending, SSE stream reading, tool-call orchestration.

import { api }   from './api.js';
import { state } from './state.js';
import { ICONS } from './icons.js';
import {
  createStreamingMessage, appendMessage,
  cancelAllToolApprovals, finalizeStreamingMessage, setStreamingMessageLogIndex,
  escapeHtml, scrollToBottom, renderAllMessages,
  createThinkingBlock, updateThinkingBlock, finalizeThinkingBlock,
  createToolStrip, toolStripFinalize, toolStripSetApproval, toolStripSetRunning,
} from './renderer.js';
import { applyMarkdown } from './markdown.js';
import { isServerEnabled, isServerAutoApprove } from './mcp.js';
import { buildMcpSystemPrompt as buildMcpPrompt } from './mcp_policy.js';
import { persistConversationFor, createNewConversation } from './conversations.js';
import { refreshFilePanel } from './file_panel.js';
import { formatBytes, fileExtensionLabel } from './format.js';

let turnAbortController = null;
let turnCancelled = false;
const activeTurns = new Map();

// ── Pending attachments ──────────────────────────────────────────────────────

// Keep one ordered list so mixed uploads render in the exact order the user picked them.
// Image entry: { kind: 'image', previewUrl, uploadPromise, name, size }
// File entry:  { kind: 'file', file, name, size }
let pendingAttachments = [];
let pendingAttachmentAdds = Promise.resolve();

function getImagePreviewBar() { return document.getElementById('image-preview-bar'); }

function refreshImagePreviewBar() {
  const bar = getImagePreviewBar();
  if (!bar) return;
  if (!pendingAttachments.length) { bar.hidden = true; bar.innerHTML = ''; return; }
  bar.hidden = false;
  bar.innerHTML = '';

  pendingAttachments.forEach((entry, idx) => {
    const wrap = document.createElement('div');
    wrap.className = `composer-attachment-card ${entry.kind === 'image' ? 'composer-image-card' : 'composer-file-card'}`;

    if (entry.kind === 'image') {
      wrap.innerHTML = `
        <img class="composer-attachment-thumb img-preview-uploading" src="${entry.previewUrl}" alt="" />
        <div class="composer-attachment-meta composer-attachment-meta-overlay">
          <div class="composer-attachment-name" title="${escapeHtml(entry.name || 'image')}">${escapeHtml(entry.name || 'image')}</div>
          <div class="composer-attachment-subtle">${formatBytes(entry.size || 0)}</div>
        </div>
        <button class="img-preview-remove" title="Remove attachment" aria-label="Remove attachment">
          ${ICONS.close}
        </button>`;

      const thumb = wrap.querySelector('.composer-attachment-thumb');
      entry.uploadPromise.then(result => {
        if (result) thumb.classList.remove('img-preview-uploading');
        else        thumb.classList.add('img-preview-error');
      });
    } else {
      wrap.innerHTML = `
        <div class="composer-attachment-meta">
          <div class="composer-attachment-name" title="${escapeHtml(entry.name || 'file')}">${escapeHtml(entry.name || 'file')}</div>
          <div class="composer-attachment-subtle">${formatBytes(entry.size || 0)}</div>
          <div class="composer-attachment-badge-row">
            <span class="composer-attachment-badge">${escapeHtml(fileExtensionLabel(entry.name || 'file'))}</span>
          </div>
        </div>
        <button class="img-preview-remove" title="Remove attachment" aria-label="Remove attachment">
          ${ICONS.close}
        </button>`;
    }

    wrap.querySelector('.img-preview-remove').addEventListener('click', () => {
      pendingAttachments.splice(idx, 1);
      refreshImagePreviewBar();
    });
    bar.appendChild(wrap);
  });
}

/** Read a File into a base64 data-URL, returning { dataUrl, mediaType, name }. */
function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = () => resolve({ dataUrl: reader.result, mediaType: file.type || 'image/png', name: file.name });
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

/** Upload base64 image to the server; returns { ref, url, mediaType } or null on failure. */
async function uploadImage(dataUrl, mediaType) {
  const base64 = dataUrl.split(',')[1];
  try {
    const result = await api.post('/api/images', { data: base64, media_type: mediaType });
    if (result.error) return null;
    return { ref: result.ref, url: result.url, mediaType };
  } catch {
    return null;
  }
}

async function uploadConversationFiles(convId, entries) {
  if (!entries.length) return [];
  const form = new FormData();
  entries.forEach(entry => form.append('files', entry.file, entry.name));

  const response = await fetch(`/api/conversations/${encodeURIComponent(convId)}/files`, {
    method: 'POST',
    body: form,
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result.error) {
    throw new Error(result.error || `Failed to upload file(s) (${response.status})`);
  }
  return Array.isArray(result.files) ? result.files : [];
}

function addRegularFiles(files) {
  for (const file of Array.from(files)) {
    if (!file || file.type.startsWith('image/')) continue;
    pendingAttachments.push({ kind: 'file', file, name: file.name || 'file', size: file.size || 0 });
  }
  refreshImagePreviewBar();
}

async function addImageFiles(files) {
  for (const file of Array.from(files)) {
    if (!file.type.startsWith('image/')) continue;
    try {
      const { dataUrl, mediaType } = await readFile(file);
      const uploadPromise = uploadImage(dataUrl, mediaType);
      pendingAttachments.push({ kind: 'image', previewUrl: dataUrl, uploadPromise, name: file.name || 'image', size: file.size || 0 });
      refreshImagePreviewBar(); // show thumb immediately, upload in background
    } catch {}
  }
}

async function addAttachmentFiles(files) {
  // Sequential processing preserves the user's selected order across mixed image/file uploads.
  for (const file of Array.from(files)) {
    if (!file) continue;
    if (file.type.startsWith('image/')) await addImageFiles([file]);
    else addRegularFiles([file]);
  }
}

export function initImageAttachments() {
  const attachBtn       = document.getElementById('attach-btn');
  const attachmentInput = document.getElementById('attachment-input') || document.getElementById('image-input');
  const textarea        = document.getElementById('user-input');

  attachBtn?.addEventListener('click', () => attachmentInput?.click());
  attachmentInput?.addEventListener('change', e => {
    const files = Array.from(e.target.files || []);
    pendingAttachmentAdds = pendingAttachmentAdds.then(() => addAttachmentFiles(files)).catch(() => {});
    attachmentInput.value = '';
  });

  textarea?.addEventListener('paste', e => {
    const items = Array.from(e.clipboardData?.items || []);
    const fileItems = items.filter(i => i.kind === 'file');
    if (!fileItems.length) return;
    const files = fileItems.map(i => i.getAsFile()).filter(Boolean);
    if (!files.length) return;
    e.preventDefault();
    pendingAttachmentAdds = pendingAttachmentAdds.then(() => addAttachmentFiles(files)).catch(() => {});
  });
}

// ── Payload builders ──────────────────────────────────────────────────────────

function buildToolsPayload() {
  return state.mcpTools
    .filter(tool => isServerEnabled(tool.server))
    .map(tool => ({
      type: 'function',
      function: {
        name:        tool.name,
        description: tool.description,
        parameters:  tool.inputSchema || { type: 'object', properties: {} },
      },
    }));
}

function buildMcpToolMetaPayload() {
  return state.mcpTools
    .filter(tool => isServerEnabled(tool.server))
    .map(tool => ({
      name: tool.name,
      server: tool.server,
      autoApprove: isServerAutoApprove(tool.server),
    }));
}

/** Fetch a server-stored image and return it as a base64 data-URL. */
async function imageRefToDataUrl(ref) {
  const resp = await fetch(`/api/images/${ref}`);
  const blob = await resp.blob();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

/** Expand image_ref content blocks into image_url blocks the OpenAI API understands. */
async function expandImageRefs(messages) {
  return Promise.all(messages.map(async msg => {
    if (!Array.isArray(msg.content)) return msg;
    const expanded = await Promise.all(msg.content.map(async part => {
      if (part.type !== 'image_ref') return part;
      try {
        const url = await imageRefToDataUrl(part.ref);
        return { type: 'image_url', image_url: { url } };
      } catch {
        return null; // skip unresolvable refs rather than crashing
      }
    }));
    return { ...msg, content: expanded.filter(Boolean) };
  }));
}

function formatAttachmentContext(files = []) {
  const validFiles = files.filter(file => file?.path);
  if (!validFiles.length) return '';
  return [
    'Attached file(s) available in the chat workspace:',
    ...validFiles.map(file => `- ${file.name || 'file'}: ${file.path}`),
  ].join('\n');
}

function appendTextToContent(content, extraText) {
  if (!extraText) return content;
  if (typeof content === 'string') return [content, extraText].filter(Boolean).join('\n\n');

  if (Array.isArray(content)) {
    const parts = content.map(part => ({ ...part }));
    const textPart = parts.find(part => part.type === 'text');
    if (textPart) textPart.text = [textPart.text || '', extraText].filter(Boolean).join('\n\n');
    else parts.unshift({ type: 'text', text: extraText });
    return parts;
  }

  return extraText;
}

function prepareMessageForApi(message) {
  const { attachments, ...cleanMessage } = message;
  const fileContext = message.role === 'user' ? formatAttachmentContext(attachments || []) : '';
  return fileContext
    ? { ...cleanMessage, content: appendTextToContent(cleanMessage.content, fileContext) }
    : cleanMessage;
}

async function buildApiMessages(turnMessages) {
  const messages = [];
  const systemParts = [state.systemPrompt, buildMcpPrompt({ tools: state.mcpTools, isServerEnabled })].filter(Boolean);
  if (systemParts.length) messages.push({ role: 'system', content: systemParts.join('\n\n') });

  // Apply the context-window limit: 0 means send the full history.
  const contextWindow = state.contextMessages || 0;
  const sliced = contextWindow > 0 ? turnMessages.slice(-contextWindow) : turnMessages;

  messages.push(...sliced.map(prepareMessageForApi));
  return expandImageRefs(messages);
}

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
    toolResultIndex:    0,
    assistantDone:      false,
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

    const success = await readSSEStream(resp, ctx);
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
  reattachActiveTurn(convId);
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

// ── Main entry point ──────────────────────────────────────────────────────────

export async function sendMessage(userText) {
  await pendingAttachmentAdds;
  if (!userText.trim() && !pendingAttachments.length) return;
  if (state.isStreaming) return;
  if (!state.convId) await createNewConversation();

  const turn = createTurnContext(state.convId);
  setStreaming(true);

  const textToSend        = userText.trim();
  const attachmentsToSend = pendingAttachments.splice(0);
  const imagesToSend      = attachmentsToSend.filter(entry => entry.kind === 'image');
  const filesToSend       = attachmentsToSend.filter(entry => entry.kind === 'file');
  refreshImagePreviewBar();

  // Resolve images first so a failed image does not silently disappear from the sent message.
  const uploadedRefs = await Promise.all(imagesToSend.map(img => img.uploadPromise));
  const failedImageCount = uploadedRefs.filter(result => !result).length;
  if (failedImageCount) {
    pendingAttachments.unshift(...attachmentsToSend);
    refreshImagePreviewBar();
    setStreaming(false);
    const plural = failedImageCount === 1 ? '' : 's';
    const errorText = `Image upload failed for ${failedImageCount} attachment${plural}. Remove it or try again before sending.`;
    turn.displayLog.push({ type: 'message', role: 'assistant', content: errorText });
    syncVisibleTurn(turn);
    if (isTurnVisible(turn)) appendMessage('assistant', errorText, turn.displayLog.length - 1);
    return;
  }

  // Copy regular files into the chat workspace.
  let uploadedFiles = [];
  try {
    uploadedFiles = await uploadConversationFiles(turn.convId, filesToSend);
    if (isTurnVisible(turn)) refreshFilePanel({ keepPreview: true }).catch(() => {});
  } catch (err) {
    pendingAttachments.unshift(...attachmentsToSend);
    refreshImagePreviewBar();
    setStreaming(false);
    const errorText = `File upload failed: ${err.message}`;
    turn.displayLog.push({ type: 'message', role: 'assistant', content: errorText });
    syncVisibleTurn(turn);
    if (isTurnVisible(turn)) appendMessage('assistant', errorText, turn.displayLog.length - 1);
    return;
  }

  const displayAttachments = [];
  let imageCursor = 0;
  let fileCursor = 0;
  attachmentsToSend.forEach(entry => {
    if (entry.kind === 'image') {
      const uploaded = uploadedRefs[imageCursor++];
      displayAttachments.push({
        kind: 'image',
        url: uploaded.url,
        ref: uploaded.ref,
        mediaType: uploaded.mediaType,
        name: entry.name || 'image',
        size: entry.size || 0,
      });
    } else {
      const uploaded = uploadedFiles[fileCursor++];
      if (uploaded) displayAttachments.push({ kind: 'file', ...uploaded });
    }
  });

  const imageAttachments = displayAttachments.filter(entry => entry.kind === 'image');

  let apiContent;
  if (imageAttachments.length > 0) {
    // API payload: user-visible text + image_ref blocks. File paths are injected
    // later by buildApiMessages() from message attachment metadata.
    apiContent = [];
    if (textToSend) apiContent.push({ type: 'text', text: textToSend });
    imageAttachments.forEach(entry => apiContent.push({ type: 'image_ref', ref: entry.ref }));
  } else {
    apiContent = textToSend;
  }

  const displayContent = displayAttachments.length
    ? {
        text: textToSend,
        attachments: displayAttachments,
        // Legacy fields keep older renderer/history paths working.
        imageUrls: imageAttachments.map(entry => entry.url),
        files: uploadedFiles,
      }
    : textToSend;

  turn.messages.push({ role: 'user', content: apiContent, attachments: uploadedFiles });
  turn.displayLog.push({ type: 'message', role: 'user', content: displayContent });
  syncVisibleTurn(turn);
  if (isTurnVisible(turn)) appendMessage('user', displayContent, turn.displayLog.length - 1);
  await persistTurnConversation(turn);

  await runAssistantTurnAndPersist(turn);
}

// ── SSE helpers ───────────────────────────────────────────────────────────────

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
    const stripIndex = ctx.toolStartNames.indexOf(evt.name);
    let strip = stripIndex >= 0 ? ctx.toolStrips[stripIndex] : null;
    if (!strip && ctx.isVisible()) strip = createToolStrip(evt.name);

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

  } else if (evt.type === 'tool_result') {
    if (ctx.reasoningBodyEl) {
      finalizeThinkingBlock(ctx.reasoningBodyEl, ctx.accReasoning);
      ctx.reasoningBodyEl = null;
    }
    if (ctx.contentEl) {
      finalizeStreamingMessage(ctx.contentEl, ctx.accText);
      ctx.contentEl = null;
    }

    const stripIndex = ctx.toolResultIndex || 0;
    let strip = ctx.toolStrips[stripIndex];
    if (!strip && ctx.isVisible()) strip = createToolStrip(evt.name);
    // Pass no displayName — renderer.js derives the label via getToolDisplayLabel()
    // which consults the tool_adapters/ system (each adapter declares its own labelArg).
    if (strip) toolStripFinalize(strip, evt.name, evt.args || {}, evt.result || '');
    ctx.toolResultIndex = stripIndex + 1;

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

async function readResponseError(resp) {
  const text = await resp.text().catch(() => '');
  if (!text) return resp.statusText || `HTTP ${resp.status}`;

  try {
    const data = JSON.parse(text);
    return data.error || text;
  } catch {
    return text;
  }
}

/** Reads the SSE response body line-by-line, calling processSSEEvent for each data event. */
async function readSSEStream(resp, ctx) {
  if (!resp.body) throw new Error('Streaming response has no body.');
  const reader  = resp.body.getReader();
  const decoder = new TextDecoder();
  let   buffer  = '';

  outer: while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split('\n');
    buffer = lines.pop(); // keep incomplete line

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const raw = line.slice(6).trim();
      if (raw === '[DONE]') break outer;

      try {
        if (!await processSSEEvent(raw, ctx)) return false;
      } catch { /* malformed SSE line — skip */ }
    }
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
      api_base:  state.apiBase,
      api_key:   state.apiKey,
      model:     state.model || 'gpt-4o',
      temperature:  state.temperature ?? 0.7,
      max_tokens:   state.maxTokens   || 0,
      messages:              await buildApiMessages(turn.messages),
      conversation_messages: turn.messages,
      display_log:           turn.displayLog,
      title:                 turn.title,
      tools:                 buildToolsPayload(),
      mcp_tool_meta:         buildMcpToolMetaPayload(),
      stream_id:             streamId,
      conv_id:               turn.convId,
      auto_generate_titles:  state.autoGenerateTitles ?? true,
      request_timeout:       state.requestTimeout || 120,
    }, { signal: turnAbortController.signal });

    if (!resp.ok) throw new Error(await readResponseError(resp));

    const success = await readSSEStream(resp, ctx);
    if (!success || turnCancelled) return;

    if (!ctx.assistantDone) finalizeAssistantAnswer(ctx);
  } catch (err) {
    if (turnCancelled || err.name === 'AbortError') return ctx;

    const el = ctx.getContentEl();
    if (el) el.innerHTML = `<span class="inline-error">Network error: ${escapeHtml(err.message)}</span>`;
  }

  return ctx;
}

// ── Index helpers ────────────────────────────────────────────────────────────

/** Maps a displayLog index to the corresponding state.messages index. */
function logIndexToMessagesIndex(logIndex) {
  let count = 0;
  for (let i = 0; i < logIndex; i++) {
    const entry = state.displayLog[i];
    if (entry && (entry.type === 'message' || entry.type === 'tool_result')) count++;
  }
  return count;
}

// ── Edit & Resend ─────────────────────────────────────────────────────────────

/**
 * Extract the image ref from a server image URL, e.g. "/api/images/<ref>" → "<ref>".
 * Returns null if the URL doesn't match the expected pattern.
 */
function imageUrlToRef(url) {
  const match = url && url.match(/\/api\/images\/([^/?#]+)/);
  return match ? match[1] : null;
}

export async function editAndResend(logIndex, newText, imageUrls = [], files = [], attachments = null) {
  if (state.isStreaming) return;

  const normalizedAttachments = Array.isArray(attachments)
    ? attachments
    : [
        ...(files || []).map(file => ({ kind: 'file', ...file })),
        ...(imageUrls || []).map(url => ({ kind: 'image', url, ref: imageUrlToRef(url) })),
      ];

  if (!newText.trim() && !normalizedAttachments.length) return;
  if (!state.convId) await createNewConversation();

  const messagesIndex = logIndexToMessagesIndex(logIndex);
  state.displayLog.splice(logIndex);
  state.messages.splice(messagesIndex);
  renderAllMessages(state.displayLog);

  // Rebuild the user turn with the original attachments so they are preserved.
  const textToSend = newText.trim();
  const fileAttachments = normalizedAttachments.filter(entry => entry.kind === 'file');
  const imageAttachments = normalizedAttachments.filter(entry => entry.kind === 'image');
  const refs = imageAttachments.map(entry => entry.ref || imageUrlToRef(entry.url)).filter(Boolean);

  let apiContent;
  if (refs.length) {
    apiContent = [];
    if (textToSend) apiContent.push({ type: 'text', text: textToSend });
    refs.forEach(ref => apiContent.push({ type: 'image_ref', ref }));
  } else {
    apiContent = textToSend;
  }

  const displayContent = normalizedAttachments.length
    ? {
        text: textToSend,
        attachments: normalizedAttachments,
        imageUrls: imageAttachments.map(entry => entry.url).filter(Boolean),
        files: fileAttachments,
      }
    : textToSend;

  const turn = createTurnContext(state.convId);
  turn.messages.push({ role: 'user', content: apiContent, attachments: fileAttachments });
  turn.displayLog.push({ type: 'message', role: 'user', content: displayContent });
  syncVisibleTurn(turn);
  if (isTurnVisible(turn)) appendMessage('user', displayContent, turn.displayLog.length - 1);
  await persistTurnConversation(turn);

  await runAssistantTurnAndPersist(turn);
}

// ── Regenerate ────────────────────────────────────────────────────────────────

export async function regenerateFrom(logIndex) {
  if (state.isStreaming) return;

  // Walk back to find the index right after the last user message — that's
  // where the whole assistant turn (thinking + tool calls + responses) begins.
  let turnStart = 0;
  for (let i = logIndex - 1; i >= 0; i--) {
    const entry = state.displayLog[i];
    if (entry.type === 'message' && entry.role === 'user') {
      turnStart = i + 1;
      break;
    }
  }

  const messagesIndex = logIndexToMessagesIndex(turnStart);
  state.displayLog.splice(turnStart);
  state.messages.splice(messagesIndex);
  renderAllMessages(state.displayLog);

  if (!state.convId) return;
  const turn = createTurnContext(state.convId);
  await persistTurnConversation(turn);
  await runAssistantTurnAndPersist(turn);
}
