// DOM rendering — the only module that touches #messages.
// API calls, persistence, and chat orchestration live elsewhere.
//
// Large sub-concerns are split into focused modules:
//   renderer_core.js        – scroll helpers and createMessageRow
//   renderer_groups.js      – block grouping, collapsible logic
//   renderer_thinking.js    – thinking block create/update/finalize
//   renderer_attachments.js – attachment cards and content parts
//   renderer_tools.js       – tool strip states (using/approval/running/result)

import { applyMarkdown } from './markdown.js';
import { $, createElement, remove, setVisible } from './dom.js';
import { ICONS } from './icons.js';
import { state } from './state.js';
import { escapeHtml } from './format.js';

import { scrollToBottom as _scrollToBottom, messagesEl, stickToBottom, createMessageRow } from './renderer_core.js';
import { prepareAssistantRow, tryGroupBlock } from './renderer_groups.js';
import { getRawText, appendContentParts, normalizeContentAttachments, renderAttachmentCard } from './renderer_attachments.js';
import { appendThinkingBlock } from './renderer_thinking.js';
import { appendToolResultInline } from './renderer_tools.js';

export { createThinkingBlock, updateThinkingBlock, finalizeThinkingBlock } from './renderer_thinking.js';
export { createToolStrip, toolStripSetApproval, toolStripSetRunning, toolStripFinalize, cancelAllToolApprovals } from './renderer_tools.js';

// Wrap scrollToBottom with the same signature expected by callers
export function scrollToBottom(force = false) { _scrollToBottom(force); }

const SUGGESTION_CHIPS = [
  { icon: ICONS.chipCode,   label: 'Code',       prompt: 'Help me write some code' },
  { icon: ICONS.chipPencil, label: 'Write',       prompt: 'Help me write something' },
  { icon: ICONS.chipInfo,   label: 'Explain',     prompt: 'Explain a concept to me' },
  { icon: ICONS.chipBox,    label: 'Analyze',     prompt: 'Analyze this for me' },
  { icon: ICONS.chipHelp,   label: 'Brainstorm',  prompt: 'Help me brainstorm ideas about' },
];

export function clearMessages() {
  messagesEl().innerHTML = `
    <div id="empty-state">
      <div class="es-logo">Lu<em>men</em></div>
      <div class="es-sub">Your AI assistant — ready to help</div>
    </div>`;

  document.getElementById('main')?.classList.add('is-empty');

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
  const inputEl = document.getElementById('user-input');
  if (inputEl) {
    inputEl.value = inputEl.value || '';
    inputEl.dispatchEvent(new Event('input'));
  }
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
  const contentEl = row.querySelector('.msg-content');
  const footerEl  = row.querySelector('.msg-footer');
  if (!contentEl) return;

  const preservedContent = currentContent && typeof currentContent === 'object' && !Array.isArray(currentContent)
    ? currentContent
    : {};
  const attachments = normalizeContentAttachments(preservedContent);
  const imageUrls = attachments.filter(entry => entry.kind === 'image').map(entry => entry.url).filter(Boolean);
  const files = attachments.filter(entry => entry.kind === 'file');

  contentEl.style.display = 'none';
  footerEl?.remove();

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
    row.dispatchEvent(new CustomEvent('chat:edit-resend', { bubbles: true, detail: { logIndex, newText, imageUrls, files, attachments } }));
  });

  cancelBtn.addEventListener('click', cancelEdit);

  textarea.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveBtn.click(); }
    if (e.key === 'Escape') cancelEdit();
  });

  actions.appendChild(cancelBtn);
  actions.appendChild(saveBtn);

  if (attachments.length) {
    const attachmentStrip = createElement('div', { className: 'msg-edit-attachments msg-attachments-grid' });
    attachments.forEach(attachment => attachmentStrip.appendChild(renderAttachmentCard(attachment, { edit: true })));
    editWrap.appendChild(attachmentStrip);
  }

  editWrap.appendChild(textarea);
  editWrap.appendChild(actions);
  row.appendChild(editWrap);

  setTimeout(() => {
    textarea.style.height = 'auto';
    textarea.style.height = textarea.scrollHeight + 'px';
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
  }, 0);
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
  _scrollToBottom(isUser);
  return contentEl;
}

export function createStreamingMessage() {
  const row = prepareAssistantRow();
  const contentEl = createElement('div', { className: 'msg-content', html: '&nbsp;' });
  row.appendChild(contentEl);
  _scrollToBottom();
  return contentEl;
}

export function finalizeStreamingMessage(contentEl, text) {
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
  const footerEl = row.querySelector('.msg-footer');
  if (!footerEl) return;
  const getText = () => {
    const el = row.querySelector('.msg-content');
    return el ? el.textContent : '';
  };
  footerEl.remove();
  addAssistantFooter(row, getText, logIndex);
}

export function renderAllMessages(displayLog) {
  messagesEl().innerHTML = '';
  if (displayLog.length > 0) {
    document.getElementById('main')?.classList.remove('is-empty');
  } else {
    clearMessages();
    return;
  }
  displayLog.forEach((entry, idx) => {
    if (entry.type === 'message') {
      if (entry.role === 'assistant' && !String(entry.content ?? '').trim()) return;
      appendMessage(entry.role, entry.content, idx);
    }
    if (entry.type === 'tool_result') appendToolResultInline(entry.name, entry.args, entry.result, entry.displayName);
    if (entry.type === 'thinking') appendThinkingBlock(entry.content);
  });
  _scrollToBottom(true);
}
