// Chat — message sending, SSE stream reading, tool-call orchestration.

import { api }   from './api.js';
import { state } from './state.js';
import { ICONS } from './icons.js';
import {
  createStreamingMessage, appendMessage,
  cancelAllToolApprovals, finalizeStreamingMessage, setStreamingMessageLogIndex,
  escapeHtml, scrollToBottom, renderAllMessages,
  createThinkingBlock, updateThinkingBlock, finalizeThinkingBlock,
  createToolStrip, toolStripSetApproval, toolStripSetRunning, toolStripFinalize, getToolDisplayLabel,
} from './renderer.js';
import { applyMarkdown } from './markdown.js';
import { executeTool, isServerEnabled, isServerAutoApprove } from './mcp.js';
import { buildMcpSystemPrompt as buildMcpPrompt } from './mcp_policy.js';
import { persistConversation, createNewConversation } from './conversations.js';

let turnAbortController = null;
let turnCancelled = false;

// ── Pending attachments ──────────────────────────────────────────────────────

let pendingImages = [];
// Each entry: { previewUrl: string, uploadPromise: Promise<{ref, url, mediaType}|null> }
let pendingFiles = [];
// Each entry: { file: File, name: string, size: number }

function getImagePreviewBar() { return document.getElementById('image-preview-bar'); }

function formatBytes(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unit = units.shift();
  while (value >= 1024 && units.length) {
    value /= 1024;
    unit = units.shift();
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${unit}`;
}

function refreshImagePreviewBar() {
  const bar = getImagePreviewBar();
  if (!bar) return;
  if (!pendingImages.length && !pendingFiles.length) { bar.hidden = true; bar.innerHTML = ''; return; }
  bar.hidden = false;
  bar.innerHTML = '';

  pendingImages.forEach((img, idx) => {
    const wrap = document.createElement('div');
    wrap.className = 'img-preview-wrap';
    wrap.innerHTML = `
      <img class="img-preview-thumb img-preview-uploading" src="${img.previewUrl}" />
      <button class="img-preview-remove" title="Remove">
        ${ICONS.close}
      </button>`;

    const thumb = wrap.querySelector('.img-preview-thumb');
    img.uploadPromise.then(result => {
      if (result) thumb.classList.remove('img-preview-uploading');
      else        thumb.classList.add('img-preview-error');
    });

    wrap.querySelector('.img-preview-remove').addEventListener('click', () => {
      pendingImages.splice(idx, 1);
      refreshImagePreviewBar();
    });
    bar.appendChild(wrap);
  });

  pendingFiles.forEach((entry, idx) => {
    const wrap = document.createElement('div');
    wrap.className = 'file-preview-wrap';
    wrap.innerHTML = `
      <div class="file-preview-icon">${ICONS.file || '📄'}</div>
      <div class="file-preview-meta">
        <div class="file-preview-name" title="${escapeHtml(entry.name)}">${escapeHtml(entry.name)}</div>
        <div class="file-preview-size">${formatBytes(entry.size)}</div>
      </div>
      <button class="img-preview-remove" title="Remove">
        ${ICONS.close}
      </button>`;

    wrap.querySelector('.img-preview-remove').addEventListener('click', () => {
      pendingFiles.splice(idx, 1);
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
    pendingFiles.push({ file, name: file.name || 'file', size: file.size || 0 });
  }
  refreshImagePreviewBar();
}

async function addImageFiles(files) {
  for (const file of Array.from(files)) {
    if (!file.type.startsWith('image/')) continue;
    try {
      const { dataUrl, mediaType } = await readFile(file);
      const uploadPromise = uploadImage(dataUrl, mediaType);
      pendingImages.push({ previewUrl: dataUrl, uploadPromise });
      refreshImagePreviewBar(); // show thumb immediately, upload in background
    } catch {}
  }
}

export function initImageAttachments() {
  const attachBtn  = document.getElementById('attach-btn');
  const imageInput = document.getElementById('image-input');
  const textarea   = document.getElementById('user-input');

  attachBtn?.addEventListener('click', () => imageInput?.click());
  imageInput?.addEventListener('change', e => {
    const files = Array.from(e.target.files || []);
    addImageFiles(files.filter(file => file.type.startsWith('image/')));
    addRegularFiles(files.filter(file => !file.type.startsWith('image/')));
    imageInput.value = '';
  });

  textarea?.addEventListener('paste', e => {
    const items = Array.from(e.clipboardData?.items || []);
    const fileItems = items.filter(i => i.kind === 'file');
    if (!fileItems.length) return;
    const files = fileItems.map(i => i.getAsFile()).filter(Boolean);
    const imageFiles = files.filter(file => file.type.startsWith('image/'));
    const regularFiles = files.filter(file => !file.type.startsWith('image/'));
    if (!imageFiles.length && !regularFiles.length) return;
    e.preventDefault();
    addImageFiles(imageFiles);
    addRegularFiles(regularFiles);
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

async function buildApiMessages() {
  const messages = [];
  const systemParts = [state.systemPrompt, buildMcpPrompt({ tools: state.mcpTools, isServerEnabled })].filter(Boolean);
  if (systemParts.length) messages.push({ role: 'system', content: systemParts.join('\n\n') });
  messages.push(...state.messages.map(prepareMessageForApi));
  return expandImageRefs(messages);
}

// ── Streaming state ───────────────────────────────────────────────────────────

function setStreaming(active) {
  state.isStreaming = active;
  document.getElementById('send-btn').hidden = active;
  document.getElementById('stop-btn').hidden = !active;
}

function finishAssistantTurn() {
  turnAbortController?.abort();
  turnAbortController = null;
  state.streamId = null;
  setStreaming(false);
}

async function generateConversationTitle() {
  try {
    const result = await api.post('/api/generate-title', {
      api_base: state.apiBase,
      api_key:  state.apiKey,
      model:    state.model || 'gpt-4o',
      messages: state.messages.slice(0, 4),
    });
    if (result.title && !result.error) {
      document.getElementById('chat-title-input').value = result.title;
      await persistConversation();
    }
  } catch { /* silently skip title generation on failure */ }
}

async function runAssistantTurnAndPersist() {
  const isFirstMessage = state.messages.length === 1;
  setStreaming(true);
  turnCancelled = false;

  try {
    await runChatLoop();
    await persistConversation();
    if (isFirstMessage && !turnCancelled) {
      await generateConversationTitle();
    }
  } finally {
    finishAssistantTurn();
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
  if (!userText.trim() && !pendingImages.length && !pendingFiles.length) return;
  if (state.isStreaming) return;
  if (!state.convId) await createNewConversation();

  setStreaming(true);

  const textToSend   = userText.trim();
  const imagesToSend = pendingImages.splice(0);
  const filesToSend  = pendingFiles.splice(0);
  refreshImagePreviewBar();

  // Await any in-progress image uploads and copy regular files into the chat workspace.
  let uploadedFiles = [];
  try {
    uploadedFiles = await uploadConversationFiles(state.convId, filesToSend);
  } catch (err) {
    pendingImages.unshift(...imagesToSend);
    pendingFiles.unshift(...filesToSend);
    refreshImagePreviewBar();
    setStreaming(false);
    const errorText = `File upload failed: ${err.message}`;
    state.displayLog.push({ type: 'message', role: 'assistant', content: errorText });
    appendMessage('assistant', errorText, state.displayLog.length - 1);
    return;
  }

  const uploadedRefs = await Promise.all(imagesToSend.map(img => img.uploadPromise));
  const validRefs    = uploadedRefs.filter(Boolean); // drop any that failed

  let apiContent;
  let displayContent;

  if (validRefs.length > 0) {
    // API payload: user-visible text + image_ref blocks. File paths are injected
    // later by buildApiMessages() from message attachment metadata.
    apiContent = [];
    if (textToSend) apiContent.push({ type: 'text', text: textToSend });
    validRefs.forEach(r => apiContent.push({ type: 'image_ref', ref: r.ref }));

    // Display payload: clean chat text + attachment chips.
    displayContent = { text: textToSend, imageUrls: validRefs.map(r => r.url), files: uploadedFiles };
  } else {
    apiContent     = textToSend;
    displayContent = uploadedFiles.length ? { text: textToSend, files: uploadedFiles } : textToSend;
  }

  state.messages.push({ role: 'user', content: apiContent, attachments: uploadedFiles });
  state.displayLog.push({ type: 'message', role: 'user', content: displayContent });
  appendMessage('user', displayContent, state.displayLog.length - 1);

  await runAssistantTurnAndPersist();
}

// ── SSE helpers ───────────────────────────────────────────────────────────────

/** Parses a single SSE event and mutates the streaming context. Returns false on terminal error. */
function processSSEEvent(raw, ctx) {
  const evt = JSON.parse(raw);

  if (evt.type === 'reasoning') {
    ctx.accReasoning += evt.content;
    if (!ctx.reasoningBodyEl) ctx.reasoningBodyEl = createThinkingBlock();
    updateThinkingBlock(ctx.reasoningBodyEl, ctx.accReasoning);

  } else if (evt.type === 'text') {
    if (ctx.reasoningBodyEl) {
      finalizeThinkingBlock(ctx.reasoningBodyEl, ctx.accReasoning);
      ctx.reasoningBodyEl = null;
    }
    ctx.accText += evt.content;
    const el = ctx.getContentEl();
    applyMarkdown(el, ctx.accText);
    scrollToBottom();

  } else if (evt.type === 'tool_start') {
    // Create the strip immediately so users see "using <tool> [pulse]" during streaming.
    // Store by insertion order — tool_calls arrives later with the full ordered call list.
    ctx.toolStrips.push(createToolStrip(evt.name));

  } else if (evt.type === 'tool_calls') {
    ctx.toolCalls = evt.calls;

  } else if (evt.type === 'error') {
    const el = ctx.getContentEl();
    el.innerHTML = `<span class="inline-error">Error: ${escapeHtml(evt.message)}</span>`;
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
        if (!processSSEEvent(raw, ctx)) return false;
      } catch { /* malformed SSE line — skip */ }
    }
  }
  return true;
}

// ── SSE loop ──────────────────────────────────────────────────────────────────

async function runChatLoop() {
  let contentEl = null;

  const ctx = {
    accText:        '',
    accReasoning:   '',
    reasoningBodyEl: null,
    toolCalls:      null,
    toolStrips:     [],   // one strip element per tool_start event, in order
    getContentEl:   () => { if (!contentEl) contentEl = createStreamingMessage(); return contentEl; },
  };

  state.streamId = crypto.randomUUID();

  try {
    turnAbortController = new AbortController();

    const resp = await api.stream('/api/chat/stream', {
      api_base:  state.apiBase,
      api_key:   state.apiKey,
      model:     state.model || 'gpt-4o',
      messages:  await buildApiMessages(),
      tools:     buildToolsPayload(),
      stream_id: state.streamId,
      conv_id:   state.convId,
    }, { signal: turnAbortController.signal });

    if (!resp.ok) throw new Error(await readResponseError(resp));

    const success = await readSSEStream(resp, ctx);
    if (!success || turnCancelled) return;

    if (ctx.reasoningBodyEl) finalizeThinkingBlock(ctx.reasoningBodyEl, ctx.accReasoning);
    if (contentEl)           finalizeStreamingMessage(contentEl, ctx.accText);

    if (ctx.toolCalls?.length > 0) {
      await handleToolCalls(ctx.toolCalls, ctx.accText, ctx.accReasoning, ctx.toolStrips);
    } else if (ctx.accText) {
      if (ctx.accReasoning) state.displayLog.push({ type: 'thinking', content: ctx.accReasoning });
      state.messages.push({ role: 'assistant', content: ctx.accText });
      state.displayLog.push({ type: 'message', role: 'assistant', content: ctx.accText });
      setStreamingMessageLogIndex(contentEl, state.displayLog.length - 1);
    }
  } catch (err) {
    if (turnCancelled || err.name === 'AbortError') return;

    const el = ctx.getContentEl();
    el.innerHTML = `<span class="inline-error">Network error: ${escapeHtml(err.message)}</span>`;
  }
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

export async function editAndResend(logIndex, newText, imageUrls = []) {
  if (state.isStreaming) return;
  if (!newText.trim() && !imageUrls.length) return;
  if (!state.convId) await createNewConversation();

  const messagesIndex = logIndexToMessagesIndex(logIndex);
  state.displayLog.splice(logIndex);
  state.messages.splice(messagesIndex);
  renderAllMessages(state.displayLog);

  // If there are no images, fall through to the normal sendMessage path.
  if (!imageUrls.length) {
    await sendMessage(newText);
    return;
  }

  // Rebuild the user turn with the original image refs so images are preserved.
  const textToSend = newText.trim();
  const refs = imageUrls.map(imageUrlToRef).filter(Boolean);

  const apiContent = [];
  if (textToSend) apiContent.push({ type: 'text', text: textToSend });
  refs.forEach(ref => apiContent.push({ type: 'image_ref', ref }));

  const displayContent = { text: textToSend, imageUrls };

  state.messages.push({ role: 'user', content: apiContent });
  state.displayLog.push({ type: 'message', role: 'user', content: displayContent });
  appendMessage('user', displayContent, state.displayLog.length - 1);

  await runAssistantTurnAndPersist();
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
  await runAssistantTurnAndPersist();
}

// ── Tool-call orchestration ───────────────────────────────────────────────────

function parseToolArgs(rawArgs) {
  try { return JSON.parse(rawArgs || '{}'); } catch { return {}; }
}

async function handleToolCalls(calls, precedingText, precedingReasoning = '', toolStrips = []) {
  if (precedingReasoning) state.displayLog.push({ type: 'thinking', content: precedingReasoning });
  if (precedingText)      state.displayLog.push({ type: 'message', role: 'assistant', content: precedingText });

  // Ensure every call has a strip — fall back to creating one if tool_start didn't fire for it.
  const strips = calls.map((call, i) => toolStrips[i] ?? createToolStrip(call.function.name));

  // Determine auto-approval per call.
  const autoApprovedFlags = calls.map(tc => {
    const toolDef = state.mcpTools.find(t => t.name === tc.function.name);
    return !!(toolDef && isServerAutoApprove(toolDef.server));
  });

  // Launch all approval UIs simultaneously; auto-approved resolve immediately.
  const decisionPromises = calls.map((call, i) =>
    autoApprovedFlags[i] ? Promise.resolve(true) : toolStripSetApproval(strips[i], call)
  );

  const decisions = await Promise.all(decisionPromises);
  if (turnCancelled) return;

  state.messages.push({
    role:       'assistant',
    content:    precedingText || null,
    tool_calls: calls.map(tc => ({
      id:       tc.id,
      type:     'function',
      function: { name: tc.function.name, arguments: tc.function.arguments },
    })),
  });

  for (let i = 0; i < calls.length; i++) {
    if (turnCancelled) return;

    const tc   = calls[i];
    const args = parseToolArgs(tc.function.arguments);
    let result;

    if (decisions[i]) {
      toolStripSetRunning(strips[i], args);
      result = await executeTool(tc, { signal: turnAbortController?.signal });
    } else {
      result = 'Tool execution denied by user.';
    }

    const displayName = getToolDisplayLabel(tc.function.name, args);
    toolStripFinalize(strips[i], tc.function.name, args, result, displayName);
    state.displayLog.push({ type: 'tool_result', name: tc.function.name, displayName, args, result });
    state.messages.push({ role: 'tool', tool_call_id: tc.id, content: result });
  }

  if (!turnCancelled) await runChatLoop();
}