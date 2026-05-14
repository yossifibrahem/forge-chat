// DOM rendering — the only module that touches #messages.
// API calls, persistence, and chat orchestration live elsewhere.

import { applyMarkdown } from './markdown.js';
import { $, createElement, remove, setVisible } from './dom.js';
import { ICONS } from './icons.js';
import { state } from './state.js';
import { escapeHtml, formatBytes, fileExtensionLabel } from './format.js';
import {
  getToolDisplayLabel, getToolMetaText, formatArgsHtml, renderToolResultHtml, visibleToolArgs,
} from './mcp_tool_ui.js';
export { getToolDisplayLabel } from './mcp_tool_ui.js';

function getToolIconSvg(toolName) {
  const tool = state.mcpTools.find(t => t.name === toolName);
  if (!tool) return ICONS.tabMcp;
  const iconKey = state.mcpServerSettings[tool.server]?.icon || 'tabMcp';
  return ICONS[iconKey] || ICONS.tabMcp;
}

const SUGGESTION_CHIPS = [
  { icon: ICONS.chipCode,       label: 'Code',       prompt: 'Help me write some code' },
  { icon: ICONS.chipPencil,      label: 'Write',      prompt: 'Help me write something' },
  { icon: ICONS.chipInfo,    label: 'Explain',    prompt: 'Explain a concept to me' },
  { icon: ICONS.chipBox,    label: 'Analyze',    prompt: 'Analyze this for me' },
  { icon: ICONS.chipHelp, label: 'Brainstorm', prompt: 'Help me brainstorm ideas about' },
];

const BOTTOM_THRESHOLD = 32;
let stickToBottom = true;
// Canceller functions for any strips currently awaiting user approval
const activeApprovalCancellers = new Set();

const messagesEl = () => $('#messages');
const formatTime = () => new Date().toLocaleTimeString('en', { hour: '2-digit', minute: '2-digit' });
const isNearBottom = el => el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_THRESHOLD;

document.addEventListener('DOMContentLoaded', () => {
  messagesEl()?.addEventListener('scroll', event => {
    stickToBottom = isNearBottom(event.currentTarget);
  }, { passive: true });
});

export function scrollToBottom(force = false) {
  const el = messagesEl();
  if (!el || (!force && !stickToBottom)) return;
  if (!force && state.isStreaming && !state.autoScrollStreaming) return;

  requestAnimationFrame(() => {
    if (force || stickToBottom) {
      el.scrollTop = el.scrollHeight;
      stickToBottom = true;
    }
  });
}

export function clearMessages() {
  messagesEl().innerHTML = `
    <div id="empty-state">
      <div class="es-logo">Lu<em>men</em></div>
      <div class="es-sub">Your AI assistant — ready to help</div>
    </div>`;

  // Switch input dock to centered mode
  document.getElementById('main')?.classList.add('is-empty');

  // Populate suggestion chips below the dock
  const suggestionsBar = document.getElementById('suggestions-bar');
  if (suggestionsBar) {
    suggestionsBar.innerHTML = SUGGESTION_CHIPS.map(chip => `
      <button class="suggestion-chip" data-prompt="${escapeHtml(chip.prompt)}">
        ${chip.icon}${escapeHtml(chip.label)}
      </button>`).join('');

    suggestionsBar.querySelectorAll('.suggestion-chip').forEach(btn => {
      btn.addEventListener('click', () => {
        const input = document.getElementById('user-input');
        if (input) {
          input.value = btn.dataset.prompt;
          input.focus();
          input.dispatchEvent(new Event('input'));
        }
      });
    });
  }
  // Ensure input listeners update initial UI state (e.g. disable send button)
  const inputEl = document.getElementById('user-input');
  if (inputEl) {
    inputEl.value = inputEl.value || '';
    inputEl.dispatchEvent(new Event('input'));
  }
}

function createMessageRow({ avatarClass, avatarIcon, roleLabel, isUser = false }) {
  remove('#empty-state');
  // Exit centered mode when conversation starts
  document.getElementById('main')?.classList.remove('is-empty');

  const row = createElement('div', { className: `msg-row${isUser ? ' user-row' : ''}` });
  row.innerHTML = `
    <div class="msg-meta">
      <div class="msg-avatar ${avatarClass}">${avatarIcon}</div>
      <span class="msg-role-label">${roleLabel}</span>
      <span class="msg-time">${formatTime()}</span>
    </div>`;

  messagesEl().appendChild(row);
  return row;
}

function getOrCreateAssistantRow() {
  const rows = [...messagesEl().children].filter(child => child.classList.contains('msg-row'));
  const last = rows.at(-1);
  return last && !last.classList.contains('user-row')
    ? last
    : createMessageRow({ avatarClass: 'ai-av', avatarIcon: ICONS.ai, roleLabel: 'Assistant' });
}

function prepareAssistantRow() {
  const row = getOrCreateAssistantRow();
  row.querySelector('.msg-footer')?.remove();
  return row;
}

function createMessageAction(icon, onClick) {
  const btn = createElement('button', { className: 'msg-action-btn', html: `${icon}` });
  btn.addEventListener('click', onClick);
  return btn;
}

function createCopyAction(getText) {
  const btn = createMessageAction(ICONS.copy, () => {
    navigator.clipboard.writeText(getText());
    btn.innerHTML = ICONS.check;
    setTimeout(() => { btn.innerHTML = ICONS.copy; }, 1500);
  });
  return btn;
}

function addMessageFooter(row, actions = []) {
  row.querySelector('.msg-footer')?.remove();
  const footer = createElement('div', { className: 'msg-footer' });
  actions.forEach(action => footer.appendChild(action));
  row.appendChild(footer);
}

function addUserFooter(row, getText, logIndex, getContent = () => null) {
  addMessageFooter(row, [
    createCopyAction(getText),
    createMessageAction(ICONS.edit, () => {
      if (logIndex < 0) return;
      startInlineEdit(row, logIndex, getText(), getContent());
    }),
  ]);
}

function addAssistantFooter(row, getText, logIndex) {
  const actions = [createCopyAction(getText)];

  if (logIndex >= 0) {
    actions.push(createMessageAction(ICONS.refresh, () => {
      row.dispatchEvent(new CustomEvent('chat:regenerate', { bubbles: true, detail: { logIndex } }));
    }));
  }

  addMessageFooter(row, actions);
}

function startInlineEdit(row, logIndex, currentText, currentContent = null) {
  // Save and remove existing content and footer
  const contentEl = row.querySelector('.msg-content');
  const footerEl  = row.querySelector('.msg-footer');
  if (!contentEl) return;

  // Extract persisted attachments from the original content object so they
  // survive the edit cycle and are not silently dropped on resend.
  const preservedContent = currentContent && typeof currentContent === 'object' && !Array.isArray(currentContent)
    ? currentContent
    : {};
  const attachments = normalizeContentAttachments(preservedContent);
  const imageUrls = attachments.filter(entry => entry.kind === 'image').map(entry => entry.url).filter(Boolean);
  const files = attachments.filter(entry => entry.kind === 'file');

  contentEl.style.display = 'none';
  footerEl?.remove();

  // Build edit UI
  const editWrap = createElement('div', { className: 'msg-edit-wrap' });
  const textarea = createElement('textarea', { className: 'msg-edit-textarea' });
  textarea.value = currentText;
  textarea.rows = Math.min(Math.max(currentText.split('\n').length, 2), 10);

  const actions = createElement('div', { className: 'msg-edit-actions' });
  const saveBtn   = createElement('button', { className: 'msg-edit-save',   text: 'Send' });
  const cancelBtn = createElement('button', { className: 'msg-edit-cancel', text: 'Cancel' });

  const cancelEdit = () => {
    editWrap.remove();
    contentEl.style.display = '';
    addUserFooter(row, () => currentText, logIndex, () => currentContent);
  };

  saveBtn.addEventListener('click', () => {
    const newText = textarea.value.trim();
    if (!newText && !attachments.length) return;
    editWrap.remove();
    contentEl.style.display = '';
    // Include the original ordered attachment list so editAndResend can restore it exactly.
    row.dispatchEvent(new CustomEvent('chat:edit-resend', { bubbles: true, detail: { logIndex, newText, imageUrls, files, attachments } }));
  });

  cancelBtn.addEventListener('click', cancelEdit);

  textarea.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveBtn.click(); }
    if (e.key === 'Escape') cancelEdit();
  });

  actions.appendChild(cancelBtn);
  actions.appendChild(saveBtn);

  // Show attached files/images above the editable text, matching the normal
  // message layout where attachments appear first and text sits underneath.
  if (attachments.length) {
    const attachmentStrip = createElement('div', { className: 'msg-edit-attachments msg-attachments-grid' });
    attachments.forEach(attachment => attachmentStrip.appendChild(renderAttachmentCard(attachment, { edit: true })));
    editWrap.appendChild(attachmentStrip);
  }

  editWrap.appendChild(textarea);
  editWrap.appendChild(actions);
  row.appendChild(editWrap);

  // Auto-resize textarea
  setTimeout(() => {
    textarea.style.height = 'auto';
    textarea.style.height = textarea.scrollHeight + 'px';
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
  }, 0);
}

function toggleCollapsible(block, body, chevron) {
  const isOpen = block.classList.toggle('open');
  if (chevron) chevron.innerHTML = isOpen ? ICONS.chevronDown : ICONS.chevronRight;
  setVisible(body, isOpen);
  return isOpen;
}

// ── Block Grouping ─────────────────────────────────────────────────────────────
// Consecutive thinking blocks and tool strips are collapsed into one expandable group
// as soon as they appear, then their contents can morph in-place while streaming.

function isGroupableBlock(el) {
  return !!el && (
    el.classList.contains('thinking-block') ||
    el.classList.contains('tool-strip')
  );
}

function makeGroupSummary(elements) {
  let thinks = 0, tools = 0;
  elements.forEach(el => {
    if (el.classList.contains('thinking-block')) thinks++;
    else if (el.classList.contains('tool-strip')) tools++;
  });
  const parts = [];
  if (thinks) parts.push(`${thinks} thinking`);
  if (tools) parts.push(`${tools} tool use`);
  return parts.join(' + ');
}

function getBlockLabel(el) {
  if (!el) return '';

  if (el.classList.contains('thinking-block')) {
    return el.querySelector('.thinking-label')?.textContent?.trim() || 'Thinking';
  }

  if (!el.classList.contains('tool-strip')) return '';

  const name = el.dataset.displayName || el.dataset.toolName || 'tool';
  if (el.classList.contains('tool-strip-using')) return name;
  if (el.classList.contains('tool-strip-running')) return name;
  if (el.classList.contains('tool-strip-approval')) return name;
  return el.querySelector('.tr-tool-name')?.textContent?.trim() || name;
}

function getLastBlockLabel(elements) {
  return getBlockLabel(elements[elements.length - 1]);
}

function createGroupBlock(elements) {
  const summary = makeGroupSummary(elements);
  const label   = getLastBlockLabel(elements);
  const expanded = state.blocksDefaultExpanded;

  const group = createElement('div', { className: `block-group${expanded ? ' open' : ''}` });
  group.innerHTML = `
    <button class="group-header">
      <span class="group-chevron">${expanded ? ICONS.chevronDown : ICONS.chevronRight}</span>
      <span class="group-icon">${ICONS.layers}</span>
      <span class="group-label">${escapeHtml(label)}</span>
      <span class="group-sep">·</span>
      <span class="group-desc">${escapeHtml(summary)}</span>
    </button>
    <div class="group-body" style="${expanded ? '' : 'display:none'}"></div>`;

  const header  = group.querySelector('.group-header');
  const body    = group.querySelector('.group-body');
  const chevron = group.querySelector('.group-chevron');

  header.addEventListener('click', () => {
    const isOpen = group.classList.toggle('open');
    chevron.innerHTML = isOpen ? ICONS.chevronDown : ICONS.chevronRight;
    setVisible(body, isOpen);
  });

  return group;
}

function updateGroupLabel(group) {
  const body     = group?.querySelector('.group-body');
  const elements = body ? [...body.children].filter(isGroupableBlock) : [];
  const lbl = group?.querySelector('.group-label');
  const dsc = group?.querySelector('.group-desc');
  if (lbl) lbl.textContent = getLastBlockLabel(elements);
  if (dsc) dsc.textContent = makeGroupSummary(elements);
}

function popApprovalOutOfGroup(strip) {
  const group = strip.closest('.block-group');
  const body = group?.querySelector('.group-body');
  if (!group || !body) return;

  const placeholder = createElement('span', { className: 'group-popout-placeholder' });
  placeholder.hidden = true;
  body.insertBefore(placeholder, strip);
  group.after(strip);

  strip._groupPlaceholder = placeholder;
  updateGroupLabel(group);
}

function restorePoppedApproval(strip) {
  const placeholder = strip._groupPlaceholder;
  if (!placeholder?.parentNode) return;

  const group = placeholder.closest('.block-group');
  placeholder.parentNode.replaceChild(strip, placeholder);
  delete strip._groupPlaceholder;
  updateGroupLabel(group);
}

function previousBlockSibling(el) {
  let prev = el.previousElementSibling;
  while (prev?.classList.contains('msg-content') && !prev.textContent.trim()) {
    prev = prev.previousElementSibling;
  }
  return prev;
}

function tryGroupBlock(el) {
  if (!isGroupableBlock(el)) return;

  const row = el.parentElement;
  if (!row) return;

  if (row.classList.contains('group-body')) {
    updateGroupLabel(row.closest('.block-group'));
    return;
  }

  const prev = previousBlockSibling(el);
  if (!prev) return;

  if (prev.classList.contains('block-group')) {
    prev.querySelector('.group-body')?.appendChild(el);
    updateGroupLabel(prev);
  } else if (isGroupableBlock(prev)) {
    const group = createGroupBlock([prev, el]);
    row.insertBefore(group, prev);
    const body = group.querySelector('.group-body');
    body.appendChild(prev);
    body.appendChild(el);
  }
}

function attachCollapsible(block, { headerSelector, bodySelector, chevronSelector, markManualToggle = false }) {
  const header = block.querySelector(headerSelector);
  const body = block.querySelector(bodySelector);
  const chevron = block.querySelector(chevronSelector);

  header?.addEventListener('click', () => {
    if (markManualToggle) block.dataset.manualToggle = '1';
    toggleCollapsible(block, body, chevron);
  });
}

function createThinkingMarkup({ label, chevron, body = '', streaming = false, display = 'none' }) {
  return `
    <button class="thinking-header">
      <span class="thinking-chevron">${chevron}</span>
      <span class="thinking-icon">${ICONS.bulb}</span>
      <span class="thinking-label">${label}</span>
      ${streaming ? '<span class="thinking-pulse"></span>' : ''}
    </button>
    <pre class="thinking-body" style="display:${display}">${body}</pre>`;
}

export function createThinkingBlock() {
  const expanded = state.blocksDefaultExpanded;
  const row = prepareAssistantRow();
  const block = createElement('div', {
    className: `thinking-block thinking-streaming${expanded ? ' open' : ''}`,
    html: createThinkingMarkup({
      label:     'Thinking…',
      chevron:   expanded ? ICONS.chevronDown : ICONS.chevronRight,
      streaming: true,
      display:   expanded ? 'block' : 'none',
    }),
  });

  attachCollapsible(block, {
    headerSelector:  '.thinking-header',
    bodySelector:    '.thinking-body',
    chevronSelector: '.thinking-chevron',
    markManualToggle: true,
  });

  row.appendChild(block);
  if (state.groupSequentialBlocks) tryGroupBlock(block);
  scrollToBottom();
  return block.querySelector('.thinking-body');
}

export function updateThinkingBlock(bodyEl, text) {
  bodyEl.textContent = text;
  scrollToBottom();
}

export function finalizeThinkingBlock(bodyEl, fullText) {
  const block = bodyEl.closest('.thinking-block');
  if (!block) return;

  block.classList.remove('thinking-streaming');
  block.querySelector('.thinking-label').textContent = 'Thought process';
  block.querySelector('.thinking-pulse')?.remove();
  bodyEl.textContent = fullText;

  // Always collapse after streaming unless the user manually toggled it during streaming.
  // blocksDefaultExpanded only controls static/history blocks, not live stream finalization.
  if (!block.dataset.manualToggle) {
    block.classList.remove('open');
    block.querySelector('.thinking-chevron').innerHTML = ICONS.chevronRight;
    setVisible(bodyEl, false);
  }

  updateGroupLabel(block.closest('.block-group'));
}

function appendThinkingBlock(reasoningText) {
  if (!reasoningText) return;

  const expanded = state.blocksDefaultExpanded;
  const row = prepareAssistantRow();
  const block = createElement('div', {
    className: `thinking-block${expanded ? ' open' : ''}`,
    html: createThinkingMarkup({
      label:   'Thought process',
      chevron: expanded ? ICONS.chevronDown : ICONS.chevronRight,
      body:    escapeHtml(reasoningText),
      display: expanded ? 'block' : 'none',
    }),
  });

  attachCollapsible(block, {
    headerSelector:  '.thinking-header',
    bodySelector:    '.thinking-body',
    chevronSelector: '.thinking-chevron',
  });

  row.appendChild(block);
  // Eagerly group with adjacent blocks (history replay path).
  if (state.groupSequentialBlocks) tryGroupBlock(block);
  scrollToBottom();
}

function normalizeContentAttachments(content = {}) {
  if (!content || typeof content !== 'object' || Array.isArray(content)) return [];
  if (Array.isArray(content.attachments)) {
    return content.attachments
      .map(entry => entry?.kind ? entry : null)
      .filter(Boolean);
  }
  return [
    ...(Array.isArray(content.files) ? content.files.map(file => ({ kind: 'file', ...file })) : []),
    ...(Array.isArray(content.imageUrls) ? content.imageUrls.map(url => ({ kind: 'image', url })) : []),
  ];
}

function renderAttachmentCard(attachment, { edit = false } = {}) {
  if (attachment.kind === 'image') {
    const card = createElement('div', {
      className: `attachment-card attachment-card--image${edit ? ' msg-edit-image-card' : ''}`,
      html: `<img class="attachment-card-thumb${edit ? ' msg-edit-image-thumb' : ''}" alt="" />
             <div class="attachment-card-overlay">
               <span class="attachment-card-name"></span>
             </div>`,
    });
    const img = card.querySelector('img');
    img.src = attachment.url || '';
    img.alt = attachment.name || 'image';
    card.querySelector('.attachment-card-name').textContent = attachment.name || 'image';
    card.title = attachment.name ? `Open ${attachment.name}` : 'Open image';
    card.style.cursor = 'zoom-in';
    card.addEventListener('click', () => {
      if (attachment.url) window.open(attachment.url, '_blank');
    });
    return card;
  }

  const card = createElement('div', { className: `attachment-card attachment-card--file${edit ? ' msg-edit-file-card' : ''}` });
  card.title = attachment.path ? `Available to tools at ${attachment.path}` : '';
  const badge = fileExtensionLabel(attachment.name || 'file');
  const size = formatBytes(attachment.size || 0, { emptyZero: true });
  card.innerHTML = `
    <div class="attachment-card-body">
      <div class="attachment-card-name"></div>
      <div class="attachment-card-footer">
        <span class="attachment-card-badge">${escapeHtml(badge)}</span>
        ${size ? `<span class="attachment-card-size">${size}</span>` : ''}
      </div>
    </div>`;
  card.querySelector('.attachment-card-name').textContent = attachment.name || 'file';
  return card;
}

function getRawText(content) {
  if (typeof content === 'string') return content;
  if (content && typeof content === 'object' && !Array.isArray(content)) return content.text || '';
  if (Array.isArray(content)) return content.filter(p => p.type === 'text').map(p => p.text).join('\n');
  return '';
}

function appendContentParts(contentEl, content) {
  // Multipart attachments: { text, attachments: [...] } with legacy support for
  // { text, imageUrls: [...], files: [...] }.
  if (content && typeof content === 'object' && !Array.isArray(content) && ('attachments' in content || 'imageUrls' in content || 'files' in content)) {
    const attachments = normalizeContentAttachments(content);

    if (attachments.length) {
      const attachmentsWrap = createElement('div', { className: 'msg-attachments-grid' });
      attachments.forEach(attachment => attachmentsWrap.appendChild(renderAttachmentCard(attachment)));
      contentEl.appendChild(attachmentsWrap);
    }

    if (content.text) {
      const textChunk = createElement('div');
      applyMarkdown(textChunk, content.text);
      contentEl.appendChild(textChunk);
    }
    return;
  }

  if (typeof content === 'string') {
    applyMarkdown(contentEl, content);
    return;
  }

  if (!Array.isArray(content)) return;
  const textParts = content.filter(p => p.type === 'text').map(p => p.text).join('\n');
  applyMarkdown(contentEl, textParts);
}


export function appendMessage(role, content, logIndex = -1) {
  if (!content) return null;

  const isUser = role === 'user';
  const row = isUser
    ? createMessageRow({ avatarClass: 'user-av', avatarIcon: ICONS.user, roleLabel: 'You', isUser: true })
    : prepareAssistantRow();

  if (logIndex >= 0) row.dataset.logIndex = logIndex;
  row.querySelector('.msg-footer')?.remove();

  const contentEl = createElement('div', { className: 'msg-content' });
  appendContentParts(contentEl, content);
  row.appendChild(contentEl);

  if (isUser) {
    addUserFooter(row, () => getRawText(content), logIndex, () => content);
  } else {
    addAssistantFooter(row, () => getRawText(content), logIndex);
  }
  scrollToBottom(isUser);
  return contentEl;
}

export function createStreamingMessage() {
  const row = prepareAssistantRow();
  const contentEl = createElement('div', { className: 'msg-content', html: '&nbsp;' });
  row.appendChild(contentEl);
  scrollToBottom();
  return contentEl;
}

export function finalizeStreamingMessage(contentEl, text) {
  // If this turn produced no text (tool-only round), the placeholder element
  // is no longer needed and must be removed so it doesn't act as a barrier
  // between the preceding group and the next thinking/tool blocks.
  if (!text || !text.trim()) {
    contentEl.remove();
    return;
  }

  applyMarkdown(contentEl, text);

  const row = contentEl.parentElement;
  row.querySelector('.msg-footer')?.remove();
  addAssistantFooter(row, () => text, -1);
}

export function setStreamingMessageLogIndex(contentEl, logIndex) {
  const row = contentEl?.parentElement;
  if (!row) return;
  row.dataset.logIndex = logIndex;
  // Update the regenerate button's logIndex closure by replacing the footer
  const footerEl = row.querySelector('.msg-footer');
  if (!footerEl) return;
  const getText = () => {
    const el = row.querySelector('.msg-content');
    return el ? el.textContent : '';
  };
  footerEl.remove();
  addAssistantFooter(row, getText, logIndex);
}

function createToolResultBody(toolName, args, result) {
  const displayArgs = visibleToolArgs(toolName, args);
  const sections = [];

  if (Object.keys(displayArgs).length) {
    sections.push(`
      <div class="tr-section">
        <div class="tr-section-label">Arguments</div>
        <div class="tr-args">${formatArgsHtml(displayArgs)}</div>
      </div>`);
  }

  sections.push(`
    <div class="tr-section">
      <div class="tr-section-label">Result</div>
      ${renderToolResultHtml(result, toolName, args)}
    </div>`);

  return sections.join('');
}

function applyToolResultStrip(strip, toolName, args, result, displayName = '') {
  const expanded = state.blocksDefaultExpanded;
  // Adapter system takes priority; fall back to stored displayName for old history entries.
  const label = getToolDisplayLabel(toolName, args) || displayName;

  strip.className = `tool-strip tool-strip-result tool-inline${expanded ? ' open' : ''}`;
  strip.innerHTML = `
    <button class="tr-summary">
      <span class="tr-chevron">${expanded ? ICONS.chevronDown : ICONS.chevronRight}</span>
      <span class="tool-icon">${getToolIconSvg(toolName)}</span>
      <span class="tr-tool-name">${escapeHtml(label)}</span>
    </button>
    <div class="tr-body" style="${expanded ? '' : 'display:none'}">${createToolResultBody(toolName, args, result)}</div>`;

  attachCollapsible(strip, {
    headerSelector:  '.tr-summary',
    bodySelector:    '.tr-body',
    chevronSelector: '.tr-chevron',
  });
}

function regroupToolStrip(strip) {
  if (strip.closest('.block-group')) {
    updateGroupLabel(strip.closest('.block-group'));
  } else if (state.groupSequentialBlocks) {
    tryGroupBlock(strip);
  }
}

// appendToolResult is used by renderAllMessages for history replay
function appendToolResultInline(toolName, args, result, displayName = '') {
  const row = prepareAssistantRow();
  const strip = createElement('div');
  applyToolResultStrip(strip, toolName, args, result, displayName);
  row.appendChild(strip);
  // Eagerly group with adjacent blocks (history replay path).
  regroupToolStrip(strip);
  scrollToBottom();
}

export function renderAllMessages(displayLog) {
  messagesEl().innerHTML = '';
  // Exit centered empty state since we are loading an existing conversation
  if (displayLog.length > 0) {
    document.getElementById('main')?.classList.remove('is-empty');
  } else {
    clearMessages();
    return;
  }
  displayLog.forEach((entry, idx) => {
    if (entry.type === 'message') {
      // Skip whitespace-only assistant messages on history replay —
      // they are tool-only turn artifacts that break block grouping.
      // (Streaming already removes them via finalizeStreamingMessage.)
      if (entry.role === 'assistant' && !String(entry.content ?? '').trim()) return;
      appendMessage(entry.role, entry.content, idx);
    }
    if (entry.type === 'tool_result') appendToolResultInline(entry.name, entry.args, entry.result, entry.displayName);
    if (entry.type === 'thinking') appendThinkingBlock(entry.content);
  });
  scrollToBottom(true);
}

// ── Unified Tool Strip ────────────────────────────────────────────────────────
// Each tool call gets ONE element that morphs through: using → approval → running → result.

/** Creates the strip in "using" state and appends it to the current assistant row. */
export function createToolStrip(toolName, displayName = '') {
  const row = prepareAssistantRow();
  const strip = createElement('div', { className: 'tool-strip tool-strip-using' });
  strip.dataset.toolName = toolName;
  strip.dataset.displayName = displayName || toolName;
  strip.innerHTML = `
    <span class="tool-icon">${getToolIconSvg(toolName)}</span>
    <span class="tui-name">${escapeHtml(displayName || toolName)}</span>
    <span class="thinking-pulse"></span>`;
  row.appendChild(strip);
  if (state.groupSequentialBlocks) tryGroupBlock(strip);
  scrollToBottom();
  return strip;
}

/** Morphs strip into approval state. Returns a Promise<boolean> that resolves when the user decides. */
export function toolStripSetApproval(strip, call) {
  return new Promise(resolve => {
    let args = {};
    try { args = JSON.parse(call.function.arguments || '{}'); } catch {}
    const hasArgs = Object.keys(args).length > 0;
    const displayName = getToolDisplayLabel(call.function.name, args);
    const metaText = getToolMetaText(call.function.name, args);
    strip.dataset.toolName = call.function.name;
    strip.dataset.displayName = displayName;


    strip.className = 'tool-strip tool-strip-approval tc-item open';
    strip.innerHTML = `
      <div class="tc-item-row">
        <button class="tc-item-header">
          <span class="tc-item-chevron">${ICONS.chevronDown}</span>
          <span class="tool-icon">${getToolIconSvg(call.function.name)}</span>
          <span class="tc-item-name">${escapeHtml(displayName)}</span>
          ${metaText ? `<span class="tc-item-noargs">${escapeHtml(metaText)}</span>` : (hasArgs ? '' : '<span class="tc-item-noargs">no arguments</span>')}
        </button>
        <span class="tc-actions">
          <button class="tc-allow">${ICONS.check} allow</button>
          <button class="tc-deny">${ICONS.close} deny</button>
        </span>
        <span class="tc-status" aria-live="polite"></span>
      </div>
      ${hasArgs ? `<div class="tc-item-args" style="display:block">${formatArgsHtml(args)}</div>` : ''}`;

    if (hasArgs) {
      attachCollapsible(strip, {
        headerSelector: '.tc-item-header',
        bodySelector: '.tc-item-args',
        chevronSelector: '.tc-item-chevron',
      });
    }

    popApprovalOutOfGroup(strip);

    let settled = false;
    const decide = allowed => {
      if (settled) return;
      settled = true;
      activeApprovalCancellers.delete(cancel);

      strip.querySelectorAll('.tc-allow, .tc-deny').forEach(btn => {
        btn.disabled = true;
        setVisible(btn, false);
      });
      const status = strip.querySelector('.tc-status');
      if (status) {
        status.className = `tc-status ${allowed ? 'allowed' : 'denied'}`;
        status.innerHTML = allowed ? `${ICONS.check} allowed` : `${ICONS.close} denied`;
      }

      resolve(allowed);
    };

    const cancel = () => decide(false);
    activeApprovalCancellers.add(cancel);

    strip.querySelector('.tc-allow')?.addEventListener('click', () => decide(true));
    strip.querySelector('.tc-deny')?.addEventListener('click',  () => decide(false));
    scrollToBottom();
  });
}


/** Morphs strip from approval → running state. */
export function toolStripSetRunning(strip, args = {}) {
  restorePoppedApproval(strip);
  const name = strip.dataset.toolName || '';
  const displayName = getToolDisplayLabel(name, args);
  strip.dataset.displayName = displayName;
  const hasArgs = Object.keys(args).length > 0;
  strip.className = 'tool-strip tool-strip-running';
  strip.innerHTML = `
    <div class="tool-strip-running-row">
      ${hasArgs
        ? `<button class="tc-item-header">
             <span class="tc-item-chevron">${ICONS.chevronRight}</span>
             <span class="tool-icon">${getToolIconSvg(name)}</span>
             <span class="tui-name">${escapeHtml(displayName)}</span>
           </button>`
        : `<span class="tool-icon">${getToolIconSvg(name)}</span>
           <span class="tui-name">${escapeHtml(displayName)}</span>`}
      <span class="thinking-pulse"></span>
    </div>
    ${hasArgs ? `<div class="tc-item-args" style="display:none">${formatArgsHtml(args)}</div>` : ''}`;

  if (hasArgs) {
    attachCollapsible(strip, {
      headerSelector: '.tc-item-header',
      bodySelector:   '.tc-item-args',
      chevronSelector: '.tc-item-chevron',
    });
  }
  updateGroupLabel(strip.closest('.block-group'));
  scrollToBottom();
}
export function toolStripFinalize(strip, toolName, args, result, displayName = '') {
  restorePoppedApproval(strip);
  applyToolResultStrip(strip, toolName, args, result, displayName);
  regroupToolStrip(strip);
  scrollToBottom();
}

/** Cancels all strips currently waiting for user approval (called on stop). */
export function cancelAllToolApprovals() {
  activeApprovalCancellers.forEach(cancel => cancel());
  activeApprovalCancellers.clear();
}